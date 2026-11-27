from __future__ import annotations

import re
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .parser import (AUDIO_EXTS, CATEGORY_NAMES, IMAGE_EXTS, VIDEO_EXTS,
                     classify_file, contains_media, extra_folder_kind, is_structural_folder, parse_title)
from .metadata import AniListClient, cache_artwork, lookup_anilist


def _identity(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.casefold()) or "unknownanime"


@dataclass(slots=True)
class SeriesRoot:
    category: str
    path: Path
    child_folders: tuple[Path, ...] = ()


def _media_children(folder: Path) -> list[Path]:
    try:
        return [p for p in folder.iterdir() if p.is_dir() and contains_media(p)]
    except OSError:
        return []


BUNDLE_MARKER=re.compile(r"\b(?:complete|collection|franchise|series\s*\+\s*movies?)\b",re.I)
NON_PRIMARY_VIDEO=re.compile(r"(?:^|[\s._\-\[\]()])(?:NCOP|NCED|OP\d*|ED\d*|opening|ending|trailer|preview|PV\d*|CM\d*|sample|creditless|clean[ ._-]*(?:op|ed|opening|ending)|bonus)(?:$|[\s._\-\[\]()])",re.I)


def discover_series_roots(root: Path, child_log: list[str] | None = None):
    child_log = child_log if child_log is not None else []
    def descend(folder,category):
        children=_media_children(folder)
        meaningful=[p for p in children if not is_structural_folder(p.name)]
        seasons=[p for p in children if re.fullmatch(r'(?i)(?:season|s)\s*0*\d+(?:\s+part\s*\d+)?',p.name)]
        direct=any(p.is_file() and p.suffix.lower() in VIDEO_EXTS for p in folder.iterdir())
        if not direct and (len(meaningful)>1 or len(seasons)>1 or (len(meaningful)==1 and BUNDLE_MARKER.search(folder.name))):
            child_log.append(f'CONTAINER: {folder}')
            for child in children:
                if child in meaningful or child in seasons:
                    yield from descend(child,category)
                else:
                    # Shared extras remain a reviewable source, never borrowed by a season.
                    yield SeriesRoot(category,child)
        else:
            yield SeriesRoot(category,folder,tuple(p for p in children if is_structural_folder(p.name)))
    for first in root.iterdir():
        if not first.is_dir() or not contains_media(first):continue
        if first.name.casefold() in CATEGORY_NAMES:
            for child in _media_children(first):yield from descend(child,first.name.title())
        else:yield from descend(first,'Other')


# Backwards-compatible name for external callers.
def discover_release_roots(root: Path):
    for item in discover_series_roots(root):
        yield item.category, item.path


def _write_diagnostics(path: Path | None, diagnostics: list[str], child_log: list[str]):
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Logs are safe to share; detailed local provenance lives in scoped Scanner Review.
        allowed=('AniVault scanner diagnostics','Episode count:','Extras count:','Confidence:','Rate limited:','Retry count:','Selected AniList ID:','Scan cancelled','Metadata scan paused','Metadata queue paused','AniList Metadata Matching:','AniList request diagnostics:')
        path.write_text("\n".join(line for line in diagnostics if line.startswith(allowed)),encoding='utf-8')



def select_episode_versions(db, anime_id, media):
    """Keep one automatic playback entry per numbered episode."""
    previous = {row["path"]: row for row in db.media(anime_id)}
    groups = {}
    for item in media:
        if item.kind == "episode":
            groups.setdefault((item.season, item.episode_label if item.episode_label is not None else item.episode), []).append(item)

    def rank(item):
        row = previous.get(str(item.path))
        has_progress = bool(row and (row["watched"] or row["resume_position_ms"]))
        match = re.search(r"(?i)\d+v(\d+)(?![a-z0-9])", item.path.stem)
        revision = int(match.group(1)) if match else 1
        return not has_progress, -revision, str(item.path).casefold()

    for versions in groups.values():
        if len(versions) < 2:
            continue
        automatic = []
        manual_episode = False
        for item in versions:
            override = db.connection.execute("SELECT kind FROM overrides WHERE path=?", (str(item.path),)).fetchone()
            if override is None:
                automatic.append(item)
            elif override["kind"] == "episode":
                manual_episode = True
        for alternate in sorted(automatic, key=rank)[int(not manual_episode):]:
            alternate.kind = "alternate"
            alternate.reason = "alternate or duplicate episode number"


def _scan(root: Path, db, progress=lambda *_: None, diagnostics_path: Path | None = None,
         metadata_status=lambda _message: None, should_cancel=lambda: False, *, match_online=True):
    child_log: list[str] = []
    from .reconciliation import inventory
    before=inventory(root,should_cancel)
    roots = list(discover_series_roots(root, child_log))
    diagnostics = [f"AniVault scanner diagnostics — {datetime.now(timezone.utc).isoformat()}",
                   f"Library root: {root}", ""]
    if not root.is_dir():
        metadata_status('Library root is unavailable. Existing records and progress were retained.')
        return 0
    from . import scan_state as state
    state.backup(db,'before-scan')
    original_sources=state.source_snapshot(db)
    db.start_scan(root)
    touched=[]
    pending_states=[]
    for index, series in enumerate(roots, 1):
        if should_cancel():
            db.connection.rollback()
            diagnostics.append("Scan cancelled before filesystem pass completed; database changes rolled back.")
            _write_diagnostics(diagnostics_path, diagnostics, child_log)
            return 0
        category, release = series.category, series.path
        parent_candidates = tuple(p.name for p in release.parents if p != root and p.name.casefold() not in CATEGORY_NAMES)
        parsed_title = parse_title(release.name, parent_candidates)
        media_files = [p for p in release.rglob("*") if p.is_file() and
                       p.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS]
        anime_id = state.source_id(db,release,parsed_title,media_files,category,original_sources)
        touched.append(anime_id)
        episode_count = extras_count = 0
        classification_notes = []
        parsed_media=[classify_file(file,0 if category.casefold()=="movies" else parsed_title.season, release_root=release) for file in media_files]
        videos=[item for item in parsed_media if item.path.suffix.lower() in VIDEO_EXTS]
        direct_ova = any(item.path.parent == release and item.kind == "special"
                         and re.search(r"\b(?:OVA|OAD)\b", item.path.stem, re.I) for item in videos)
        if parsed_title.format_hint is None and BUNDLE_MARKER.search(release.name) and direct_ova:
            parsed_title.format_hint = "OVA"
        if parsed_title.format_hint is None and any(item.kind == "episode" for item in videos):
            parsed_title.format_hint = "SERIES"
        # Standalone films/OVAs frequently have no episode token. Determine the
        # primary candidate relative to this release root (not all ancestors,
        # since a legitimate title may itself be named "Extra Stage"). A folder
        # may also contain samples/OPs; those never block one clear main video.
        primary=[]
        for item in videos:
            relative=item.path.relative_to(release); nested_parts=relative.parts[:-1]
            in_extras=any(extra_folder_kind(part) for part in nested_parts)
            clearly_extra=in_extras or bool(NON_PRIMARY_VIDEO.search(item.path.stem))
            if not clearly_extra: primary.append(item)
        if len(primary) == 1:
            item = primary[0]
            if (item.reason in {"bare numbered-video fallback", "explicit episode identifier"}
                    and not (item.episode_label == "0")
                    and parse_title(item.path.stem).title.casefold() == parsed_title.title.casefold()):
                item.episode = 1
                item.episode_label = None
                item.reason = "single video whose name matches the release"
        if (parsed_title.format_hint is None and primary and all(
                item.kind == "special" and re.search(r"\b(?:OVA|OAD)\b", item.path.stem, re.I)
                for item in primary)):
            parsed_title.format_hint = "OVA"
        if not any(item.kind == "episode" for item in parsed_media):
            # A named movie or OVA may be the primary playable item. Multiple
            # unnumbered videos in an ordinary series need review.
            standalone = parsed_title.format_hint in {"MOVIE", "OVA", "SPECIAL", "PICTURE_DRAMA"} or category.casefold() == "movies"
            candidates = [item for item in primary if item.kind in {"other", "movie", "special"}]
            playable = candidates if standalone else [item for item in candidates if item.kind == "other"]
            if standalone or len(primary) == len(playable) == 1:
                def natural_order(item):
                    return [int(part) if part.isdigit() else part.casefold()
                            for part in re.split(r"(\d+)", str(item.path.relative_to(release)))]

                for episode, candidate in enumerate(sorted(playable, key=natural_order), 1):
                    candidate.kind = "episode"
                    candidate.season = parsed_title.season
                    candidate.episode = episode
                    candidate.reason = "primary playable video fallback"
        select_episode_versions(db, anime_id, parsed_media)
        from .episode_identity import assign_labels
        assign_labels(parsed_media,parsed_title.format_hint=='PICTURE_DRAMA')
        for parsed_file in parsed_media:
            file=parsed_file.path
            db.upsert_media(anime_id, parsed_file)
            if parsed_file.kind == "episode": episode_count += 1
            else: extras_count += 1
            if "fallback" in parsed_file.reason or "ambiguous" in parsed_file.reason:
                classification_notes.append(f"Classification: {file.name} -> {parsed_file.kind} ({parsed_file.reason})")
        # Shared OVA/movie/special folders retain their stable parent record.
        # Distinct file identities are reviewed separately instead of borrowing one show's metadata.
        mixed=bool(parsed_title.format_hint in {'MOVIE','OVA','SPECIAL'} and len(primary)>1)
        file_matches = [(candidate, parsed_title.format_hint) for candidate in primary] if mixed else []
        if parsed_title.format_hint == 'MOVIE':
            file_matches.extend((item, 'OVA') for item in videos if item.kind == 'ova')
        for candidate, format_hint in file_matches:
            media=db.connection.execute('SELECT id FROM media WHERE path=?',(str(candidate.path),)).fetchone()
            db.connection.execute("INSERT INTO scan_file_matches(media_id,parsed_title,format_hint) VALUES(?,?,?) ON CONFLICT(media_id) DO UPDATE SET parsed_title=excluded.parsed_title,format_hint=excluded.format_hint",(media['id'],state.file_title(candidate.path,parsed_title.title),format_hint))
        saved = db.anime(anime_id)
        saved_metadata = json.loads(saved["metadata_json"] or "{}")
        matched_title = (saved_metadata.get("title", {}).get("english") or
                         saved_metadata.get("title", {}).get("romaji") or "Unmatched")
        diagnostics.extend([f"Series root: {release}", f"Raw folder: {release.name}",
                            f"Parsed title: {parsed_title.title}", f"AniList match before refresh: {matched_title}",
                            f"Episode count: {episode_count}", f"Extras count: {extras_count}",
                            *classification_notes])
        previous=state.source_state(db,anime_id)
        if previous['locked']:
            state.record(db,anime_id,state=previous['state'],report=state.safe_json(previous['report']),part=parsed_title.part,format_hint=parsed_title.format_hint,commit=False)
        if not previous['locked']:
            reason='Shared release folder: review individual files.' if mixed else 'No AniList match yet.'
            level='Needs Review' if mixed else 'Unmatched'
            if saved['anilist_id'] and not mixed:
                from .metadata import evaluate_candidate
                decision=evaluate_candidate(parsed_title.title,saved_metadata,parsed_title.season if parsed_title.season_explicit else None,parsed_title.year,alternates=(parsed_title.alternate_title,),format_hint=parsed_title.format_hint)
                level='Existing match' if decision['eligible'] and decision['score']>=.86 else 'Needs Review'
                reason='Existing link retained; original match provenance is unknown.' if level=='Existing match' else decision['reason']
            pending_states.append((anime_id, level, {'query':parsed_title.title,'reason':reason}, parsed_title))
        if saved["anilist_id"] and db.anime_scope(saved,fresh=False)=='normal':
            diagnostics.extend([f"Search title: {parsed_title.title}", "Request attempted: No",
                                "HTTP status: N/A", "API error/response: Existing match preserved",
                                "Candidate count: N/A", f"Candidate titles: {matched_title}",
                                f"Selected AniList ID: {saved['anilist_id']}", "Confidence: preserved",
                                "Failure reason: None", ""])
        else:
            diagnostics.append("PENDING ANILIST LOOKUP")
            diagnostics.append("")
        progress(index, len(roots), 'Restricted source' if db.anime_scope(saved,fresh=False)=='restricted' else parsed_title.title)
    if inventory(root,should_cancel)!=before:
        from .reconciliation import ScanChanged
        raise ScanChanged('Library changed during scan; retry reconciliation.')
    from .reconciliation import complete
    complete(db,root,touched,before)

    for anime_id, level, details, parsed in pending_states:
        previous=state.source_state(db,anime_id)
        preserved=state.safe_json(previous['report'])
        if preserved.get('query') == parsed.title and 'candidates' in preserved:
            if level == 'Unmatched' or (level == 'Existing match' and previous['state'] == 'High Confidence'):
                level, details = previous['state'], preserved
        state.record(db, anime_id, state=level, report=details, part=parsed.part,
                     format_hint=parsed.format_hint, commit=False)

    state.flag_duplicate_matches(db)
    db.finish_scan()
    db.last_scan_completed=True
    from . import metadata_jobs as jobs
    from .anilist_transport import configure
    scheduler=configure(db.path.parent)
    jobs.enqueue_existing(db,set(touched))
    metadata_status(f'Local Library Scan completed: {len(roots)} roots indexed. '+jobs.progress_text(db))
    if match_online:
        jobs.process(db,lookup=lookup_anilist,scheduler=scheduler,should_cancel=should_cancel,status=metadata_status,max_jobs=100000,include_artwork=False,max_seconds=120)
        # Standalone callers retain identification compatibility; desktop indexing
        # uses match_online=False and a separate persistent metadata worker.
    for row in db.anime_list():
        if row['id'] in touched and row['anilist_id'] and db.anime_scope(row,fresh=False)=='normal':diagnostics.append(f"Selected AniList ID: {row['anilist_id']}")
    diagnostics.extend(['AniList Metadata Matching: '+json.dumps(jobs.summary(db)), 'AniList request diagnostics: '+json.dumps(scheduler.snapshot('normal'))])
    _write_diagnostics(diagnostics_path, diagnostics, child_log)
    return len(roots)


def scan(root,db,progress=lambda *_:None,diagnostics_path=None,metadata_status=lambda _:None,should_cancel=lambda:False,*,match_online=True):
    from .reconciliation import ScanCancelled,ScanChanged,unavailable
    root=Path(root)
    db.last_scan_completed=False
    try:
        return _scan(root,db,progress,diagnostics_path,metadata_status,should_cancel,match_online=match_online)
    except ScanCancelled:
        db.connection.rollback();metadata_status('Scan cancelled; existing library retained.');return 0
    except ScanChanged:
        db.connection.rollback();unavailable(db,root,'Needs review')
        metadata_status('Library changed during scan; existing records retained. Retry after file changes finish.');return 0
    except OSError:
        db.connection.rollback();unavailable(db,root,'Source unavailable')
        metadata_status('Library scan incomplete or source unavailable. Existing records retained.')
        return 0
    except Exception:
        db.connection.rollback();raise

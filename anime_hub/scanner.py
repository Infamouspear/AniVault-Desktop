from __future__ import annotations

import re
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .parser import (AUDIO_EXTS, CATEGORY_NAMES, EXTRA_DIR_WORDS, IMAGE_EXTS, VIDEO_EXTS,
                     classify_file, contains_media, is_structural_folder, parse_title)
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


def _is_series_bundle(folder: Path, meaningful_children: list[Path]) -> bool:
    """Recognize one franchise release whose numbered stage folders belong together."""
    if len(meaningful_children)<2 or not BUNDLE_MARKER.search(folder.name): return False
    parent_words={word for word in re.findall(r"[a-z0-9]+",parse_title(folder.name).title.casefold()) if len(word)>1}
    if not parent_words: return False
    matches=0
    for child in meaningful_children:
        child_words=set(re.findall(r"[a-z0-9]+",parse_title(child.name).title.casefold()))
        if parent_words & child_words: matches+=1
    return matches>=max(2,len(meaningful_children)//2)


def discover_series_roots(root: Path, child_log: list[str] | None = None):
    """Find meaningful series roots; structural children remain under parents."""
    child_log = child_log if child_log is not None else []
    for first in root.iterdir():
        if not first.is_dir():
            continue
        if first.name.casefold() in CATEGORY_NAMES:
            for series in _media_children(first):
                if is_structural_folder(series.name):
                    # There is no meaningful parent below the category. Keep an
                    # unresolved series so its media never silently disappears.
                    child_log.append(f"UNRESOLVED STRUCTURAL ROOT: {series}")
                for nested in series.rglob("*"):
                    if nested.is_dir() and is_structural_folder(nested.name):
                        child_log.append(f"CHILD/BATCH: {nested} -> {series}")
                children=_media_children(series)
                releases=[child for child in children if parse_title(child.name).season_explicit or parse_title(child.name).format_hint in {'MOVIE','OVA'}]
                if len(releases)>1 and not any(f.is_file() and f.suffix.lower() in VIDEO_EXTS for f in series.iterdir()):
                    for release in children:yield SeriesRoot(first.name.title(),release)
                else:yield SeriesRoot(first.name.title(), series)
            continue
        if contains_media(first):
            child_releases = _media_children(first)
            direct_media = any(p.is_file() and p.suffix.lower() in VIDEO_EXTS for p in first.iterdir())
            meaningful_children = [p for p in child_releases if not is_structural_folder(p.name)]
            structural_children = [p for p in child_releases if is_structural_folder(p.name)]
            # A loose folder with several meaningful show folders is a container
            # (for example "corrupted"). Batch/season children instead prove the
            # loose folder itself is the series root.
            if (len(meaningful_children) > 1 and not direct_media
                    and not _is_series_bundle(first,meaningful_children)):
                for release in child_releases:
                    for nested in release.rglob("*"):
                        if nested.is_dir() and is_structural_folder(nested.name):
                            child_log.append(f"CHILD/BATCH: {nested} -> {release}")
                    yield SeriesRoot(first.name, release)
            else:
                attached_children=child_releases if _is_series_bundle(first,meaningful_children) else structural_children
                for child in attached_children:
                    child_log.append(f"CHILD/BATCH: {child} -> {first}")
                yield SeriesRoot("Other", first, tuple(attached_children))


# Backwards-compatible name for external callers.
def discover_release_roots(root: Path):
    for item in discover_series_roots(root):
        yield item.category, item.path


def _write_diagnostics(path: Path | None, diagnostics: list[str], child_log: list[str]):
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Logs are safe to share; detailed local provenance lives in scoped Scanner Review.
        allowed=('AniVault scanner diagnostics','Episode count:','Extras count:','Confidence:','Rate limited:','Retry count:','Selected AniList ID:','Scan cancelled','Metadata scan paused','Metadata queue paused')
        path.write_text("\n".join(line for line in diagnostics if line.startswith(allowed)),encoding='utf-8')



def scan(root: Path, db, progress=lambda *_: None, diagnostics_path: Path | None = None,
         metadata_status=lambda _message: None, should_cancel=lambda: False):
    child_log: list[str] = []
    if not root.is_dir():
        metadata_status('Library root is unavailable. Existing records and progress were retained.')
        return 0
    roots = list(discover_series_roots(root, child_log))
    diagnostics = [f"AniVault scanner diagnostics — {datetime.now(timezone.utc).isoformat()}",
                   f"Library root: {root}", ""]
    if not root.is_dir():
        metadata_status('Library root is unavailable. Existing records and progress were retained.')
        return 0
    from . import scan_state as state
    state.backup(db,'before-scan')
    db.start_scan(root)
    touched=[]
    mixed_ids=set()
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
        anime_id = state.source_id(db,release,parsed_title,media_files,category)
        touched.append(anime_id)
        episode_count = extras_count = 0
        classification_notes = []
        parsed_media=[classify_file(file,0 if category.casefold()=="movies" else parsed_title.season) for file in media_files]
        videos=[item for item in parsed_media if item.path.suffix.lower() in VIDEO_EXTS]
        if parsed_title.format_hint is None and videos and any(item.kind=='episode' for item in videos):parsed_title.format_hint='SERIES'
        # Standalone films/OVAs frequently have no episode token. Determine the
        # primary candidate relative to this release root (not all ancestors,
        # since a legitimate title may itself be named "Extra Stage"). A folder
        # may also contain samples/OPs; those never block one clear main video.
        primary=[]
        for item in videos:
            relative=item.path.relative_to(release); nested_parts=relative.parts[:-1]
            in_extras=any(EXTRA_DIR_WORDS.search(part) for part in nested_parts)
            clearly_extra=in_extras or bool(NON_PRIMARY_VIDEO.search(item.path.stem))
            if not clearly_extra: primary.append(item)
        if not any(item.kind=="episode" for item in parsed_media) and primary:
            natural=lambda item:[int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)",str(item.path.relative_to(release)))]
            for episode,candidate in enumerate(sorted(primary,key=natural),1):
                if candidate.kind in {"other","movie","special"}:
                    candidate.kind="episode"; candidate.season=parsed_title.season; candidate.episode=episode
                    candidate.reason="primary playable video fallback (deterministic order)"
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
        if mixed:
            mixed_ids.add(anime_id)
            for candidate in primary:
                media=db.connection.execute('SELECT id FROM media WHERE path=?',(str(candidate.path),)).fetchone()
                db.connection.execute("INSERT INTO scan_file_matches(media_id,parsed_title,format_hint) VALUES(?,?,?) ON CONFLICT(media_id) DO UPDATE SET parsed_title=excluded.parsed_title,format_hint=excluded.format_hint",(media['id'],state.file_title(candidate.path,parsed_title.title),parsed_title.format_hint))
        saved = db.anime(anime_id)
        saved_metadata = json.loads(saved["metadata_json"] or "{}")
        matched_title = (saved_metadata.get("title", {}).get("english") or
                         saved_metadata.get("title", {}).get("romaji") or "Unmatched")
        diagnostics.extend([f"Series root: {release}", f"Raw folder: {release.name}",
                            f"Parsed title: {parsed_title.title}", f"AniList match before refresh: {matched_title}",
                            f"Episode count: {episode_count}", f"Extras count: {extras_count}",
                            *classification_notes])
        previous=state.source_state(db,anime_id)
        if not previous['locked']:
            reason='Shared release folder: review individual files.' if mixed else 'No AniList match yet.'
            level='Needs Review' if mixed else 'Unmatched'
            if saved['anilist_id'] and not mixed:
                from .metadata import evaluate_candidate
                decision=evaluate_candidate(parsed_title.title,saved_metadata,parsed_title.season if parsed_title.season_explicit else None,parsed_title.year,alternates=(parsed_title.alternate_title,),format_hint=parsed_title.format_hint)
                level='Existing match' if decision['eligible'] and decision['score']>=.86 else 'Needs Review'
                reason='Existing link retained; original match provenance is unknown.' if level=='Existing match' else decision['reason']
            pending_states.append((anime_id,level,{'query':parsed_title.title,'reason':reason},parsed_title,mixed))
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
    db.finish_scan()
    for anime_id,level,details,parsed,mixed in pending_states:
        if mixed:mixed_ids.add(anime_id)
        state.record(db,anime_id,state=level,report=details,part=parsed.part,format_hint=parsed.format_hint,commit=False)

    db.connection.commit()
    unresolved = [row for row in db.anime_list() if row['id'] in touched and row['id'] not in mixed_ids and not row["anilist_id"] and not state.source_state(db,row['id'])['locked']]
    client = AniListClient(status_callback=metadata_status, should_cancel=should_cancel)
    client.query_cache={}
    total = len(unresolved)
    for position, row in enumerate(unresolved, 1):
        if should_cancel():
            diagnostics.append(f"Metadata scan paused after {position - 1} / {total}; completed matches were saved.")
            break
        metadata_status(f"Fetching metadata… {position} / {total}")
        report = lookup_anilist(row["parsed_search_title"] or row["title"],
                                row["detected_season"], row["detected_year"], client,
                                tuple(value for value in (row["alt_title"],) if value),
                                row["episode_count"],state.source_state(db,row['id'])['format_hint'],state.source_state(db,row['id'])['part'])
        scope='restricted' if (report.selected or {}).get('isAdult') is True else db.anime_scope(row,fresh=False)
        if scope=='restricted':
            # Never persist a private candidate list or its identity in a normal diagnostic log.
            report.candidates=[v for v in report.candidates if v.get('isAdult') is True]
        else:
            report.candidates=[v for v in report.candidates if v.get('isAdult') is not True]
        if report.selected:
            selected = report.selected
            try:
                selected = cache_artwork(selected, db.path.parent/'cache'/('restricted_artwork' if selected.get('isAdult') is True else 'artwork'))
            except Exception as exc:
                report.api_error = (report.api_error + f" Artwork cache error: {exc}").strip()
            db.set_metadata(row["id"], selected["id"], selected)
            report.selected=selected
        state.record(db,row['id'],state=report.confidence_level if not report.selected else 'High Confidence',report=state.report_data(report),method='automatic',part=state.source_state(db,row['id'])['part'],format_hint=state.source_state(db,row['id'])['format_hint'],artwork_state='Available' if report.selected and report.selected.get('cover_path') else 'Retry artwork' if report.selected else 'Awaiting identification')
        final_title = ((report.selected or {}).get("title") or {}).get("english") or \
                      ((report.selected or {}).get("title") or {}).get("romaji") or \
                      ("Pending / Rate Limited" if report.rate_limited else "Unmatched")
        diagnostics.extend([f"Metadata lookup for: {row['root_path']}",
                            f"AniList match: {final_title}", *(['Confidence: Private source'] if scope=='restricted' else report.diagnostic_lines()), ""])
        _write_diagnostics(diagnostics_path, diagnostics, child_log)
        if report.rate_limited and not report.selected:
            diagnostics.append("Metadata queue paused after repeated rate limiting; unresolved titles remain pending.")
            break
    # File-level suggestions are stored with provenance; a human confirms mixed releases.
    for anime_id in mixed_ids:
        if should_cancel():break
        row=db.anime(anime_id)
        if db.anime_scope(row,fresh=False)=='restricted':continue
        for file in db.connection.execute('SELECT f.* FROM scan_file_matches f JOIN media m ON f.media_id=m.id WHERE m.anime_id=? AND f.locked=0 AND f.anilist_id IS NULL',(anime_id,)).fetchall():
            if should_cancel():break
            report=lookup_anilist(file['parsed_title'],None,None,client,(),None,file['format_hint'])
            report.candidates=[v for v in report.candidates if v.get('isAdult') is False]
            # Suggestions from a shared folder never rewrite its inherited legacy link.
            with db.connection:db.connection.execute('UPDATE scan_file_matches SET state=?,report=? WHERE media_id=?',('Needs Review' if report.candidates else 'Unmatched',json.dumps(state.report_data(report)),file['media_id']))
            if report.api_error:break
    _write_diagnostics(diagnostics_path, diagnostics, child_log)
    return len(roots)

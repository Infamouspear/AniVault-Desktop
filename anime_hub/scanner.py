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
                yield SeriesRoot(first.name.title(), series)
            continue
        if contains_media(first):
            child_releases = _media_children(first)
            direct_media = any(p.is_file() and p.suffix.lower() in VIDEO_EXTS for p in first.iterdir())
            meaningful_children = [p for p in child_releases if not is_structural_folder(p.name)]
            structural_children = [p for p in child_releases if is_structural_folder(p.name)]
            # A loose folder with several meaningful show folders is a container
            # (for example "corrupted"). Batch/season children instead prove the
            # loose folder itself is the series root.
            if (len(meaningful_children) > 1 and not direct_media and not structural_children
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
        path.write_text("\n".join([*diagnostics, "Folders treated as child/batch folders:", *child_log]),
                        encoding="utf-8")


def scan(root: Path, db, progress=lambda *_: None, diagnostics_path: Path | None = None,
         metadata_status=lambda _message: None, should_cancel=lambda: False):
    child_log: list[str] = []
    roots = list(discover_series_roots(root, child_log))
    diagnostics = [f"AniVault scanner diagnostics — {datetime.now(timezone.utc).isoformat()}",
                   f"Library root: {root}", ""]
    db.start_scan()
    for index, series in enumerate(roots, 1):
        if should_cancel():
            db.connection.rollback()
            diagnostics.append("Scan cancelled before filesystem pass completed; database changes rolled back.")
            _write_diagnostics(diagnostics_path, diagnostics, child_log)
            return 0
        category, release = series.category, series.path
        parent_candidates = tuple(p.name for p in release.parents if p != root and p.name.casefold() not in CATEGORY_NAMES)
        parsed_title = parse_title(release.name, parent_candidates)
        identity = _identity(parsed_title.title)
        if parsed_title.season_explicit and parsed_title.season > 1:
            identity += f":s{parsed_title.season}"
        if parsed_title.title == "Unknown Anime":
            identity += hashlib.sha1(str(release).encode("utf-8")).hexdigest()[:12]
        anime_id = db.upsert_anime(identity, parsed_title.title, parsed_title.alternate_title,
                                   category, str(release), release.name, parsed_title.title,
                                   parsed_title.season if parsed_title.season_explicit else None,
                                   parsed_title.year)
        media_files = [p for p in release.rglob("*") if p.is_file() and
                       p.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS]
        episode_count = extras_count = 0
        classification_notes = []
        parsed_media=[classify_file(file,0 if category.casefold()=="movies" else parsed_title.season) for file in media_files]
        videos=[item for item in parsed_media if item.path.suffix.lower() in VIDEO_EXTS]
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
        saved = db.anime(anime_id)
        saved_metadata = json.loads(saved["metadata_json"] or "{}")
        matched_title = (saved_metadata.get("title", {}).get("english") or
                         saved_metadata.get("title", {}).get("romaji") or "Unmatched")
        diagnostics.extend([f"Series root: {release}", f"Raw folder: {release.name}",
                            f"Parsed title: {parsed_title.title}", f"AniList match before refresh: {matched_title}",
                            f"Episode count: {episode_count}", f"Extras count: {extras_count}",
                            *classification_notes])
        if saved["anilist_id"]:
            diagnostics.extend([f"Search title: {parsed_title.title}", "Request attempted: No",
                                "HTTP status: N/A", "API error/response: Existing match preserved",
                                "Candidate count: N/A", f"Candidate titles: {matched_title}",
                                f"Selected AniList ID: {saved['anilist_id']}", "Confidence: preserved",
                                "Failure reason: None", ""])
        else:
            diagnostics.append("PENDING ANILIST LOOKUP")
            diagnostics.append("")
        progress(index, len(roots), parsed_title.title)
    db.finish_scan()

    unresolved = [row for row in db.anime_list() if not row["anilist_id"]]
    client = AniListClient(status_callback=metadata_status, should_cancel=should_cancel)
    total = len(unresolved)
    for position, row in enumerate(unresolved, 1):
        if should_cancel():
            diagnostics.append(f"Metadata scan paused after {position - 1} / {total}; completed matches were saved.")
            break
        metadata_status(f"Fetching metadata… {position} / {total}")
        report = lookup_anilist(row["parsed_search_title"] or row["title"],
                                row["detected_season"], row["detected_year"], client,
                                tuple(value for value in (row["alt_title"],) if value),
                                row["episode_count"])
        if report.selected:
            selected = report.selected
            try:
                selected = cache_artwork(selected, db.path.parent/"cache"/"artwork")
            except Exception as exc:
                report.api_error = (report.api_error + f" Artwork cache error: {exc}").strip()
            db.set_metadata(row["id"], selected["id"], selected)
        final_title = ((report.selected or {}).get("title") or {}).get("english") or \
                      ((report.selected or {}).get("title") or {}).get("romaji") or \
                      ("Pending / Rate Limited" if report.rate_limited else "Unmatched")
        diagnostics.extend([f"Metadata lookup for: {row['root_path']}",
                            f"AniList match: {final_title}", *report.diagnostic_lines(), ""])
        _write_diagnostics(diagnostics_path, diagnostics, child_log)
        if report.rate_limited and not report.selected:
            diagnostics.append("Metadata queue paused after repeated rate limiting; unresolved titles remain pending.")
            break
    _write_diagnostics(diagnostics_path, diagnostics, child_log)
    return len(roots)

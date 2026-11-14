from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".webm", ".m4v", ".mov", ".mpg", ".mpeg", ".ts", ".m2ts"}
AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
CATEGORY_NAMES = {"airing", "finished", "movies", "unwatched", "watching"}

SPECIAL_WORDS = re.compile(
    r"\b(ova|oad|ona|specials?|sp(?:ecial)?s?|recap|ncop|nced|creditless|"
    r"clean\s+(?:opening|ending)|bonus|trailer|pv|cm)\b", re.I
)
SPECIAL_CODE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:S\d{1,2})?SP\d*|NC(?:OP|ED)(?:v\d+)?|"
    r"(?:CREDITLESS|CLEAN)[ ._-]*(?:OP|ED|OPENING|ENDING))(?![A-Za-z])", re.I
)
EXTRA_DIR_WORDS = re.compile(
    r"\b(extras?|specials?|scans?|artwork|booklets?|audio\s*cd|drama\s*cd|ost)\b", re.I
)

NOISE_TOKEN = re.compile(
    r"\[(?:\d{3,4}p|(?:hevc|avc|x26[45]|h\.?26[45])(?:[^\]]*)?|10\s*bit|8\s*bit|"
    r"dual[- ]?audio|multi[- ]?subs?|eng[- ]?subs?|bd(?:rip)?|blu[- ]?ray|web(?:-?dl|rip)?|"
    r"aac(?:[^\]]*)?|flac(?:[^\]]*)?|[0-9a-f]{8})\]", re.I
)
RELEASE_METADATA = re.compile(
    r"\b(?:2160p|1080p|720p|480p|blu[- ]?ray|b[dr](?:rip)?|web(?:[- .]?dl|rip)?|remux|"
    r"hevc|avc|x26[45]|h\.?26[45]|8\s*bit|10\s*bit|flac|aac|opus|ac-?3|e-?ac-?3|"
    r"dual[- ]?audio|multi[- ]?subs?|multi[- ]?audio|eng[- ]?subs?|ddp?\s*\d(?:\.\d)?|"
    r"proper|repack)\b", re.I
)
HASH_TOKEN = re.compile(r"(?:\[|\b)[0-9a-f]{8,40}(?:\]|\b)", re.I)
EPISODE_RANGE_PAREN = re.compile(r"\(\s*\d{1,4}\s*[-–—]\s*\d{1,4}\s*\)")
YEAR_PAREN = re.compile(r"\(\s*(?:19|20)\d{2}\s*\)")
REVISION_TOKEN = re.compile(r"\bv\d+\b", re.I)
DESCRIPTOR_PAREN = re.compile(
    r"\b(?:complete(?:\s+(?:series|season|movies?))?|series\s*\+\s*movies?|batch|"
    r"uncensored|multi(?:ple)?\s+subs?|dual\s+audio|collection|episodes?\s*\d*)\b", re.I
)
TRAILING_DESCRIPTOR = re.compile(
    r"(?:\s*[-–—:]?\s*)\b(?:complete(?:\s+(?:series|collection|edition))?|batch)\b\s*$", re.I
)
GROUP_PREFIX = re.compile(r"^\s*\[([^\]]+)\]\s*")
SEASON_RE = re.compile(r"\(?(?:season|s)\s*0*(\d+)(?:\s*(?:pt|part)\s*0*(\d+))?\)?", re.I)
EPISODE_PATTERNS = (
    re.compile(r"\bS(\d{1,2})E(\d{1,4})(?:v\d+)?\b", re.I),
    re.compile(r"\bEpisode\s*0*(\d{1,4})(?:v\d+)?\b", re.I),
    re.compile(r"(?:^|\s)-\s*0*(\d{1,4})(?:v\d+)?(?:\s|$)", re.I),
)


@dataclass(slots=True)
class ParsedTitle:
    title: str
    alternate_title: str = ""
    release_group: str = ""
    season: int = 1
    part: int | None = None
    year: int | None = None
    season_explicit: bool = False


@dataclass(slots=True)
class ParsedFile:
    path: Path
    kind: str
    season: int | None = None
    episode: int | None = None
    reason: str = ""


def _tidy(value: str) -> str:
    value = NOISE_TOKEN.sub(" ", value)
    value = HASH_TOKEN.sub(" ", value)
    value = EPISODE_RANGE_PAREN.sub(" ", value)
    value = YEAR_PAREN.sub(" ", value)
    value = REVISION_TOKEN.sub(" ", value)
    value = re.sub(r"\(([^()]*)\)",
                   lambda match: " " if DESCRIPTOR_PAREN.search(match.group(1)) else match.group(0), value)
    value = re.sub(r"\[[^\]]+\]", " ", value)
    value = SEASON_RE.sub(" ", value)
    # Release metadata normally begins a trailing technical suffix. Truncating
    # at its first token also removes channel layouts and release-group tails.
    technical = RELEASE_METADATA.search(value)
    if technical:
        value = value[:technical.start()]
    value = re.sub(r"[_\.]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    value = TRAILING_DESCRIPTOR.sub(" ", value)
    return value.strip(" -–—()[]")


STRUCTURAL_FOLDER = re.compile(
    r"^(?:(?:\d{1,4})\s*[-–—]\s*(?:\d{1,4})|(?:19|20)\d{2}|"
    r"(?:season|series|part|cour)\s*\d+(?:\s*(?:part|pt)\s*\d+)?|s\d{1,2}|"
    r"episodes?|eps?|extras?|specials?|sps?|scans?|artworks?|booklets?|"
    r"audio\s*cds?|drama\s*cds?|osts?|bonus(?:\s*content)?)$", re.I
)


def is_structural_folder(name: str) -> bool:
    cleaned = re.sub(r"[\[\](){}]", "", name).strip(" ._-")
    return not cleaned or bool(STRUCTURAL_FOLDER.fullmatch(cleaned))


def is_meaningful_title(value: str) -> bool:
    cleaned = value.strip()
    return bool(cleaned and not is_structural_folder(cleaned) and re.search(r"[A-Za-z0-9]", cleaned))


def parse_title(folder_name: str, parent_names: tuple[str, ...] = ()) -> ParsedTitle:
    raw = folder_name.replace("\n", " ")
    group = ""
    prefix = GROUP_PREFIX.match(raw)
    if prefix:
        group = prefix.group(1).strip()
        raw = raw[prefix.end():]

    season_match = SEASON_RE.search(raw)
    season = int(season_match.group(1)) if season_match else 1
    part = int(season_match.group(2)) if season_match and season_match.group(2) else None
    year_match = re.search(r"(?:\(|\b)((?:19|20)\d{2})(?:\)|\b)", raw)
    year = int(year_match.group(1)) if year_match else None

    # English names in release folders commonly appear in the parenthetical
    # immediately before the season marker. Exclude technical/small parentheses.
    candidates = []
    for match in re.finditer(r"\(([^()]+)\)", raw):
        text = match.group(1).strip()
        if (not SEASON_RE.search(text) and len(text) > 3
                and not RELEASE_METADATA.search(text)
                and not DESCRIPTOR_PAREN.search(text)
                and not re.fullmatch(r"(?:19|20)\d{2}|\d{1,4}\s*[-–—]\s*\d{1,4}", text)):
            candidates.append(text)
    english = candidates[-1] if candidates else ""
    before_english = raw.split(f"({english})", 1)[0] if english else raw
    alternate = _tidy(before_english)
    title = _tidy(english) if english else alternate
    if not is_meaningful_title(title):
        cleaned_parents = [_tidy(name) for name in parent_names]
        title = next((name for name in cleaned_parents if is_meaningful_title(name)), "")
    if not is_meaningful_title(title):
        title = next((name.strip() for name in parent_names if is_meaningful_title(name)), "")
    if not is_meaningful_title(title) and is_meaningful_title(folder_name):
        title = folder_name.strip()
    if not title.strip():
        title = "Unknown Anime"
    return ParsedTitle(title=title, alternate_title=alternate if english else "",
                       release_group=group, season=season, part=part, year=year,
                       season_explicit=season_match is not None)


def classify_file(path: Path, release_season: int = 1) -> ParsedFile:
    suffix = path.suffix.lower()
    context = " ".join(p.name for p in path.parents if p.name)[-500:]
    text = f"{context} {path.stem}"
    in_extra_dir = any(EXTRA_DIR_WORDS.search(parent.name) for parent in path.parents)

    if suffix in IMAGE_EXTS:
        return ParsedFile(path, "artwork", reason="image extension")
    if suffix in AUDIO_EXTS:
        return ParsedFile(path, "audio", reason="audio extension")
    if suffix not in VIDEO_EXTS:
        return ParsedFile(path, "other", reason="unsupported/non-media extension")
    if in_extra_dir or SPECIAL_CODE.search(path.stem) or SPECIAL_WORDS.search(text):
        evidence = "recognized extras folder" if in_extra_dir else "recognized special marker in name"
        return ParsedFile(path, "special", reason=evidence)

    path_season = release_season
    for parent in path.parents:
        season_match = SEASON_RE.fullmatch(parent.name.strip())
        if season_match:
            path_season = int(season_match.group(1))
            break

    match = EPISODE_PATTERNS[0].search(path.stem)
    if match:
        return ParsedFile(path, "episode", int(match.group(1)), int(match.group(2)), "SxxExx pattern")
    explicit_e = re.search(r"(?:^|[\s._-])E0*(\d{1,4})(?:v\d+)?(?=[\s._\[\]()-]|$)", path.stem, re.I)
    if explicit_e:
        return ParsedFile(path, "episode", path_season, int(explicit_e.group(1)), "explicit Exx pattern")
    for pattern in EPISODE_PATTERNS[1:]:
        match = pattern.search(path.stem)
        if match:
            return ParsedFile(path, "episode", path_season, int(match.group(1)), "explicit episode-number pattern")

    # Real releases often use just "Title 01". Ignore technical/year numbers,
    # then prefer the final plausible 1-3 digit token.
    number_source = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", path.stem)
    plausible = [int(value) for value in re.findall(r"(?<![A-Za-z0-9])0*(\d{1,3})(?![A-Za-z0-9])", number_source)
                 if int(value) not in {264, 265, 480, 720}]
    if plausible:
        return ParsedFile(path, "episode", path_season, plausible[-1], "bare numbered-video fallback")
    if release_season == 0:
        return ParsedFile(path, "movie", reason="movie-category fallback")
    return ParsedFile(path, "other", reason="ambiguous unnumbered video; no episode evidence")


def contains_media(folder: Path) -> bool:
    try:
        return any(p.is_file() and p.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS
                   for p in folder.rglob("*"))
    except OSError:
        return False


def direct_release_folders(container: Path) -> list[Path]:
    """Return likely release roots without treating a multi-release container as one show."""
    children = [p for p in container.iterdir() if p.is_dir()]
    releases = []
    for child in children:
        if contains_media(child):
            releases.append(child)
    return releases

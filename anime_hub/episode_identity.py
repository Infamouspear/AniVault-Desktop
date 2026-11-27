"""Exact source labels are text; integer ordinals drive playback and progress."""
import re
from decimal import Decimal

PICTURE_DRAMA=re.compile(r'picture[\s._-]*dramas?|visual[\s._-]*dramas?|ピクチャードラマ',re.I)
NUMBER=re.compile(r'(?<![A-Za-z0-9])(?:S[0-9]+E|stage|turn|episode|ep|e)\s*[._ -]*([0-9]+(?:\.[0-9]+)?)(?![0-9])',re.I)
FRACTION=re.compile(r'(?<![A-Za-z0-9.])([0-9]{1,4}\.[0-9]+)(?![A-Za-z0-9.])')


def source_label(stem):
    stem=re.sub(r'\[[^]]*\]',' ',stem)
    stem=re.split(r'(?i)\b(?:AAC|FLAC|HEVC|x26[45]|\d{3,4}p)\b',stem)[0]
    match=NUMBER.search(stem)
    if not match:match=FRACTION.search(stem)
    return match.group(1) if match else None


def assign_labels(files,picture=False):
    primary=[f for f in files if f.kind=='episode']
    fractional=any(f.episode_label and '.' in f.episode_label for f in primary)
    if not (picture or fractional):return
    # Preserve meaningful integer source numbers when mixed with fractions.
    for f in primary:
        if f.episode_label is None and f.episode is not None:f.episode_label=str(f.episode)
    primary.sort(key=lambda f:(f.season or 0,Decimal(f.episode_label) if f.episode_label is not None else Decimal('Infinity'),str(f.path).casefold()))
    for order,file in enumerate(primary,1):file.episode=order


def display_episode(row):
    return row['episode_label'] if 'episode_label' in row.keys() and row['episode_label'] is not None else row['episode']


def unique_anilist_rows(rows):
    result={};duplicates=set()
    for row in rows:
        identifier=row['anilist_id']
        if identifier is None:continue
        identifier=int(identifier)
        if identifier in result:duplicates.add(identifier)
        else:result[identifier]=row
    return {key:value for key,value in result.items() if key not in duplicates}

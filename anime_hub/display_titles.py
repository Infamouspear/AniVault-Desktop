"""Display-only manga titles. Stored paths, titles and scanner identities stay intact."""
import re
from pathlib import Path

TECHNICAL=re.compile(r'\b(?:digital|scans?|scanlation|retail|ripped|cb[rz]|pdf|jpe?g|png|webp|\d{3,4}p|\d{3,4}dpi|x26[45]|hevc|avc|upscaled|official|complete)\b',re.I)
GROUPS={'lucaz','akraa','danke','empire','oak','uploader','scanner'}

def clean_manga_display_title(value):
    raw=str(value or '').strip()
    if not raw:return ''
    value=Path(raw).stem if Path(raw).suffix.lower() in {'.cbz','.cbr','.pdf'} else raw
    # Annotation blocks are release metadata; preserve an entirely bracketed name.
    value=re.sub(r'\[[^\]]*\]','',value)
    def annotation(match):
        text=match[1].strip()
        if TECHNICAL.search(text) or text.casefold() in GROUPS or re.fullmatch(r'(?:19|20)\d{2}',text):return ''
        return match[0]
    value=re.sub(r'\(([^)]*)\)',annotation,value)
    value=re.sub(r'[._]+',' ',value)
    value=re.sub(r'\s+',' ',value).strip(' -–—[]()')
    return value or raw.strip('[]') or raw

def manga_display_title(row,metadata):
    title=metadata.get('title')
    if isinstance(title,dict):
        matched=title.get('userPreferred') or title.get('english') or title.get('romaji') or title.get('native')
        if matched:return matched
    explicit=metadata.get('local_title') or metadata.get('display_title') or (title if isinstance(title,str) else None)
    if explicit:return str(explicit).strip()
    return clean_manga_display_title(row.get('parsed_title') or row.get('title')) or row.get('title') or 'Untitled Manga'

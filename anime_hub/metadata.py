from __future__ import annotations

import email.utils
import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

ENDPOINT = "https://graphql.anilist.co"
QUERY = """query ($search: String,$adult:Boolean) { Page(page:1, perPage:8) { media(search:$search, type:ANIME,isAdult:$adult) {
 id startDate { year month day } relations { edges { relationType node { id type format isAdult title { english romaji } } } } title { romaji english native } description(asHtml:false) season seasonYear genres tags { id name rank isMediaSpoiler isAdult } format status episodes isAdult popularity trending averageScore
 nextAiringEpisode { airingAt episode }
 coverImage { extraLarge large } bannerImage synonyms
 } } }"""


@dataclass(slots=True)
class LookupReport:
    search_title: str
    request_attempted: bool = False
    http_status: int | None = None
    api_error: str = ""
    candidates: list[dict] = field(default_factory=list)
    selected: dict | None = None
    confidence: float = 0.0
    failure_reason: str = ""
    retry_count: int = 0
    rate_limited: bool = False
    search_variants: list[str] = field(default_factory=list)
    confidence_level: str = 'Unmatched'
    decisions: list[dict] = field(default_factory=list)
    failure_kind: str = ''
    next_retry: float = 0
    requests: int = 0
    cache_hits: int = 0

    def diagnostic_lines(self) -> list[str]:
        candidate_titles = []
        for item in self.candidates:
            titles = item.get("title") or {}
            candidate_titles.append(f"{item.get('id')}: {titles.get('english') or titles.get('romaji') or 'Untitled'}")
        return [
            f"Search title: {self.search_title}",
            f"Search variants attempted: {' | '.join(self.search_variants) if self.search_variants else self.search_title}",
            f"Request attempted: {'Yes' if self.request_attempted else 'No'}",
            f"HTTP status: {self.http_status if self.http_status is not None else 'N/A'}",
            f"API error/response: {self.api_error or 'OK'}",
            f"Candidate count: {len(self.candidates)}",
            f"Candidate titles: {' | '.join(candidate_titles) if candidate_titles else 'None'}",
            f"Selected AniList ID: {self.selected.get('id') if self.selected else 'None'}",
            f"Confidence: {self.confidence_level} (ranking score, not a probability)",
            f"Rate limited: {'Yes' if self.rate_limited else 'No'}",
            f"Retry count: {self.retry_count}",
            f"Failure reason: {self.failure_reason or 'None'}",
        ]


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


STOP_WORDS = {"a","an","and","at","for","from","in","is","it","me","my","no","of","on","or","the","to","with"}
GENERIC_FALLBACK_WORDS = {
    "battle", "boss", "complete", "fight", "hero", "last", "love", "movie",
    "new", "season", "story", "the", "war", "world",
}


def _words(value: str) -> set[str]:
    normalized = value.replace("’", "'").casefold()
    return {word for word in re.findall(r"[a-z0-9]+", normalized) if len(word) > 1 and word not in STOP_WORDS}


def _safe_fallback(original: str, variant: str) -> bool:
    """Reject generic or lossy fragments while retaining distinctive short titles."""
    original_words = _words(original)
    variant_words = _words(variant)
    if not variant_words or not (variant_words & original_words):
        return False
    if variant_words <= GENERIC_FALLBACK_WORDS:
        return False
    if len(variant_words) == 1:
        word = next(iter(variant_words))
        return len(word) >= 5 and word not in GENERIC_FALLBACK_WORDS
    return True


def search_variants(title: str, alternate_titles: tuple[str, ...] = ()) -> list[str]:
    """Build conservative broadening queries, ordered from precise to broad."""
    variants = []
    def add(value: str, *, shortened: bool = False):
        value = re.sub(r"\s+", " ", value.replace("’", "'")).strip(" ._-–—:()[]")
        if shortened and not _safe_fallback(title, value):
            return
        if len(value) >= 2 and value.casefold() not in {item.casefold() for item in variants}:
            variants.append(value)
    add(title)
    for alternate in alternate_titles:
        add(alternate)
    descriptor_free = re.sub(r"(?:\s*[-–—:]?\s*)\b(?:complete(?:\s+(?:series|collection|edition))?|batch)\b\s*$",
                             "", title, flags=re.I)
    add(descriptor_free)
    contractions = {r"\bDont\b":"Don't",r"\bCant\b":"Can't",r"\bWont\b":"Won't",
                    r"\bIm\b":"I'm",r"\bIll\b":"I'll",r"\bIsnt\b":"Isn't"}
    restored = descriptor_free
    for pattern, replacement in contractions.items():
        restored = re.sub(pattern, replacement, restored, flags=re.I)
    add(restored)
    segments = [part.strip() for part in re.split(r"\s+[-–—:]\s+", restored) if part.strip()]
    for segment in segments:
        add(segment, shortened=True)
    words = restored.split()
    if len(words) >= 3:
        add(" ".join(words[-2:]), shortened=True)
    if len(words) >= 4:
        add(" ".join(words[-3:]), shortened=True)
    meaningful = [word for word in words if word.casefold().strip("!?.,'") not in STOP_WORDS]
    if meaningful:
        add(meaningful[-1].strip("!?.,'"), shortened=True)
    return variants[:6]


def _candidate_season(candidate: dict) -> int:
    titles=candidate.get('title') or {};values=[*titles.values(),*(candidate.get('synonyms') or [])]
    for value in values:
        match=re.search(r'\bseason\s*(\d+)|\b(\d+)(?:st|nd|rd|th)\s+season\b',str(value),re.I)
        if match:return int(match.group(1) or match.group(2))
    for value in values:
        if re.search(r'\b(?:part|cour)\s*\d+',str(value),re.I):continue
        match=re.search(r'\s([2-9])\s*$',str(value))
        if match:return int(match.group(1))
    return 1


def _old_score(search: str, candidate: dict, detected_season: int | None = None,
           detected_year: int | None = None, local_episode_count: int | None = None,
           alternate_searches: tuple[str, ...] = ()) -> float:
    titles = candidate.get("title") or {}
    values = [titles.get("english"), titles.get("romaji"), titles.get("native"), *(candidate.get("synonyms") or [])]
    base = 0.0
    local_forms = (search, *alternate_searches)
    best_coverage = 0.0
    best_shared_count = 0
    for local in local_forms:
        local_normal = _normal(local)
        local_words = _words(local)
        for value in values:
            if not value:
                continue
            normalized = _normal(value)
            ratio = 1.0 if normalized == local_normal else SequenceMatcher(None, local_normal, normalized).ratio()
            candidate_words = _words(value)
            shared_count = len(local_words & candidate_words)
            coverage = shared_count / len(local_words) if local_words else 0.0
            best_coverage = max(best_coverage, coverage)
            best_shared_count = max(best_shared_count, shared_count)
            # Expanded official titles can differ greatly while containing the
            # complete distinctive local title (e.g. "All Works Maid").
            if len(local_words) >= 2 and coverage >= 0.8:
                ratio = max(ratio, 0.86 + min(0.08, (coverage - 0.8) * 0.4))
            base = max(base, ratio)
    # Generated fallback queries discover candidates but are not title evidence.
    # Weak overlap with the original/trusted title cannot auto-match.
    anchor_words = max((len(_words(local)) for local in local_forms), default=0)
    automatic_cap = None
    if best_shared_count == 0:
        automatic_cap = 0.78
    elif anchor_words >= 3 and best_shared_count == 1 and best_coverage < 0.5:
        automatic_cap = 0.79
    score = base
    if detected_season:
        candidate_season = _candidate_season(candidate)
        if candidate_season == detected_season:
            score += 0.20 if detected_season > 1 else 0.08
        elif detected_season > 1:
            score -= 0.25
        else:
            score -= 0.12
    if detected_year and candidate.get("seasonYear"):
        difference = abs(int(candidate["seasonYear"]) - detected_year)
        score += 0.10 if difference == 0 else (-0.08 if difference > 1 else -0.02)
    if local_episode_count and candidate.get("episodes"):
        candidate_episodes = int(candidate["episodes"])
        if candidate_episodes == local_episode_count:
            score += 0.08
        elif local_episode_count > candidate_episodes:
            score -= 0.08
    if automatic_cap is not None:
        score = min(score, automatic_cap)
    return max(0.0, min(1.0, score))


MATCH_GENERIC={'ova','ovas','oad','special','specials','movie','movies','season','series','part','cour','sp'}

def evaluate_candidate(search,candidate,season=None,year=None,count=None,alternates=(),format_hint=None,part=None):
    reasons=[];values=list((candidate.get('title') or {}).values())+list(candidate.get('synonyms') or [])
    anchors=[_words(v)-MATCH_GENERIC for v in (search,*alternates)]
    anchors=[v for v in anchors if v]
    if not anchors:return {'id':candidate.get('id'),'score':0.0,'eligible':False,'reason':'No franchise title evidence; generic release label only.'}
    if not isinstance(candidate.get('id'),int) or not values or candidate.get('type','ANIME')!='ANIME':reasons.append('Invalid or incompatible media identity.')
    if season and _candidate_season(candidate)!=season:reasons.append('Conflicting season number.')
    candidate_parts={int(m.group(1)) for value in values for m in re.finditer(r'\b(?:part|cour)\s*(\d+)',str(value),re.I)}
    if part and (candidate_parts!={part}):reasons.append('Missing or conflicting part/cour identifier.')
    local_text=' '.join(str(v) for v in (search,*alternates)).casefold()
    for qualifier in ('picture drama','prologue','recap','compilation','digest'):
        if any(qualifier in str(value).casefold() for value in values) and qualifier not in local_text:reasons.append('Unrequested '+qualifier+' release.')
    kind=candidate.get('format')
    allowed={'SERIES':{'TV','TV_SHORT','ONA'},'MOVIE':{'MOVIE'},'OVA':{'OVA','ONA','SPECIAL'},'SPECIAL':{'SPECIAL','OVA','ONA'}}
    if format_hint in allowed and kind and kind not in allowed[format_hint]:reasons.append('Incompatible media format.')
    shared=max((len(anchor & (_words(v)-MATCH_GENERIC)) for anchor in anchors for v in values if v),default=0)
    if not shared:reasons.append('Franchise title conflicts with the local release.')
    if reasons:return {'id':candidate.get('id'),'score':0.0,'eligible':False,'reason':' '.join(reasons)}
    score=_old_score(search,candidate,season,year,count,alternates)
    # Distinctive short franchise names need complete token evidence, not fuzzy fragments.
    single=next((next(iter(a)) for a in anchors if len(a)==1),None)
    if single and len(single)>=7 and single not in GENERIC_FALLBACK_WORDS and any(re.match(r'^'+re.escape(single)+r'\b',str(v),re.I) for v in values if v):score=max(score,.94)
    return {'id':candidate.get('id'),'score':score,'eligible':True,'reason':'Title evidence and release constraints agree.'}


def _score(search,candidate,detected_season=None,detected_year=None,local_episode_count=None,alternate_searches=()):
    return evaluate_candidate(search,candidate,detected_season,detected_year,local_episode_count,alternate_searches)['score']


class AniListClient:
    """Matching policy over the shared transport; no independent request budget."""
    def __init__(self,min_interval=2.2,max_retries=5,status_callback=None,should_cancel=None,
                 time_func=time.monotonic,sleep_func=time.sleep,*,scheduler=None,scope='normal',origin='matching',priority=10,wait=True,force=False):
        self.scheduler=scheduler;self.scope=scope;self.origin=origin;self.priority=priority;self.wait=wait;self.force=force
        self._cancel_supplied=should_cancel is not None;self.max_retries=max_retries;self.status_callback=status_callback or (lambda _:None);self.should_cancel=should_cancel or (lambda:False)
        self._lock=threading.Lock()

    def lookup(self,title,detected_season=None,detected_year=None,alternate_titles=(),local_episode_count=None,detected_format=None,detected_part=None):
        from .anilist_transport import get_scheduler,Deferred
        from .anilist_transport import _context
        cancel_callback=self.should_cancel if self._cancel_supplied else _context.get().get('cancel',self.should_cancel)
        report=LookupReport(search_title=title);candidate_map={}
        from .parser import is_structural_folder
        if not title or title=='Unknown Anime' or is_structural_folder(title):
            report.failure_kind='no_match';report.failure_reason='A structural folder label is not a searchable release identity; supply its franchise title in Review.';return report
        with self._lock:
            for variant in search_variants(title,alternate_titles):
                if cancel_callback():report.failure_kind='cancelled';report.failure_reason='Metadata matching cancelled';return report
                report.search_variants.append(variant)
                body=getattr(self,'query_cache',{}).get(variant)
                if body is None:
                    try:
                        response=(self.scheduler or get_scheduler()).request(QUERY,{'search':variant,'adult':self.scope=='restricted'},scope=self.scope,origin=self.origin,priority=self.priority,force=self.force,wait=self.wait,max_retries=self.max_retries,cancel=cancel_callback,status=self.status_callback)
                        body=response.payload;report.http_status=response.status;report.requests+=response.requests;report.cache_hits+=int(response.cached);report.request_attempted|=response.requests>0;report.retry_count+=response.retries;report.rate_limited|=response.rate_limited
                    except Deferred as exc:
                        report.failure_kind=exc.kind;report.next_retry=exc.retry_at;report.http_status=exc.status;report.requests+=exc.attempts;report.request_attempted|=exc.attempts>0;report.retry_count+=exc.retries
                        report.rate_limited=exc.kind=='rate_limited'
                        report.api_error='' if exc.kind in {'waiting','cancelled'} else exc.kind
                        report.failure_reason=('Pending / Rate Limited — metadata will resume without rescanning local files' if report.rate_limited else 'Metadata '+exc.kind.replace('_',' '))
                        return report
                else:report.http_status=200;report.cache_hits+=1
                try:
                    candidates=body['data']['Page']['media']
                    if not isinstance(candidates,list):raise ValueError()
                except (KeyError,TypeError,ValueError):
                    report.failure_kind='invalid_response';report.next_retry=(self.scheduler or get_scheduler()).clock()+300;report.api_error='Invalid AniList response';report.failure_reason='Invalid response; matching can retry later';return report
                for item in candidates:
                    if isinstance(item,dict) and type(item.get('id')) is int and item['id']>0 and isinstance(item.get('title'),dict):candidate_map[item['id']]=item
                if candidates and not candidate_map:
                    report.failure_kind='invalid_response';report.next_retry=(self.scheduler or get_scheduler()).clock()+300;report.api_error='Invalid candidate identities';report.failure_reason='Invalid metadata response; retry is deferred';return report
                report.candidates=list(candidate_map.values())
                if report.candidates:
                    evaluations=[evaluate_candidate(title,item,detected_season,detected_year,local_episode_count,alternate_titles,detected_format,detected_part) for item in report.candidates]
                    report.decisions=evaluations
                    ranked=sorted(zip(evaluations,report.candidates),key=lambda pair:pair[0]['score'],reverse=True)
                    best_score,best=ranked[0];report.confidence=best_score['score']
                    runner=ranked[1][0]['score'] if len(ranked)>1 else 0
                    if best_score['eligible'] and report.confidence>=.86 and report.confidence-runner>=.05:
                        report.selected=best;report.confidence_level='High Confidence';report.failure_reason='';break
                    report.confidence_level='Needs Review'
        if not report.candidates:
            report.failure_kind='no_match';report.failure_reason='AniList returned no candidates after fallback searches'
        elif not report.selected:
            report.failure_kind='ambiguous';report.failure_reason='Candidate evidence is weak, contradictory or too close; available for manual match'
        return report


_DEFAULT_CLIENT = AniListClient()


def lookup_anilist(title: str, detected_season: int | None = None,
                   detected_year: int | None = None, client: AniListClient | None = None,
                   alternate_titles: tuple[str, ...] = (), local_episode_count: int | None = None, detected_format=None, detected_part=None) -> LookupReport:
    return (client or _DEFAULT_CLIENT).lookup(title, detected_season, detected_year,
                                              alternate_titles, local_episode_count, detected_format, detected_part)


def search_anilist(title: str):
    report = lookup_anilist(title)
    if report.http_status != 200 or report.api_error:
        raise RuntimeError(report.failure_reason + (f": {report.api_error[:300]}" if report.api_error else ""))
    return report.candidates


def cache_artwork(metadata: dict, cache_dir: Path) -> dict:
    import io,uuid
    from PIL import Image
    metadata=dict(metadata);cache_dir.mkdir(parents=True,exist_ok=True)
    for field,remote in (("cover_path",(metadata.get('coverImage') or {}).get('extraLarge') or (metadata.get('coverImage') or {}).get('large')),("banner_path",metadata.get('bannerImage'))):
        if metadata.get(field) and Path(metadata[field]).is_file():
            try:
                with Image.open(metadata[field]) as image:image.verify()
                continue
            except (OSError,ValueError):
                if not re.match(r'^\d+_(?:cover|banner)_path\.',Path(metadata[field]).name):raise ValueError('Custom artwork cannot be read; choose a valid local image.')
                metadata.pop(field,None)
        if not remote:continue
        from urllib.parse import urlsplit
        url=urlsplit(remote)
        if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('Invalid artwork address')
        suffix=Path(url.path).suffix or '.jpg';destination=cache_dir/f"{metadata['id']}_{field}{suffix}"
        valid=False
        if destination.is_file():
            try:
                with Image.open(destination) as image:image.verify()
                valid=True
            except (OSError,ValueError):pass
        if not valid:
            request=urllib.request.Request(remote,headers={'User-Agent':'AniVault'})
            with urllib.request.urlopen(request,timeout=20) as response:data=response.read(32*1024*1024+1)
            if len(data)>32*1024*1024:raise ValueError('Artwork exceeds size limit')
            with Image.open(io.BytesIO(data)) as image:image.verify()
            temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.part')
            try:temporary.write_bytes(data);temporary.replace(destination)
            finally:
                if temporary.exists():temporary.unlink()
        metadata[field]=str(destination)
    return metadata


def fetch_anilist_id(identifier,*,scope='normal',scheduler=None,wait=False,origin='metadata-id',force=False):
    from .anilist_transport import get_scheduler
    query="query($id:Int,$adult:Boolean){Media(id:$id,type:ANIME,isAdult:$adult){id type title{romaji english native} synonyms description(asHtml:false) format status episodes isAdult season seasonYear genres coverImage{extraLarge large} bannerImage relations{edges{relationType node{id type isAdult title{romaji english} format}}}}}"
    response=(scheduler or get_scheduler()).request(query,{'id':int(identifier),'adult':scope=='restricted'},scope=scope,origin=origin,wait=wait,priority=20,force=force)
    item=(response.payload.get('data') or {}).get('Media')
    if not isinstance(item,dict) or item.get('id')!=identifier or item.get('isAdult') is not (scope=='restricted') or not isinstance(item.get('title'),dict) or not any(item['title'].values()):
        from .anilist_transport import Deferred
        raise Deferred('invalid_response',time.time()+300)
    return item

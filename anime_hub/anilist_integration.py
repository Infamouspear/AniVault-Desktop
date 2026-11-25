from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

from .metadata import ENDPOINT

USER_AGENT = "AniVault/0.6 (Windows local library client)"
SEASON_PAGE_SIZE = 20


class AniListHTTPError(RuntimeError):
    def __init__(self,status_code,details,retry_after=None):
        self.status_code=int(status_code); self.retry_after=retry_after
        suffix=f" Retry-After: {retry_after}s." if retry_after is not None else ""
        super().__init__(f"AniList returned HTTP {self.status_code}: {details}{suffix}")


def current_anime_season(now: datetime | None = None) -> tuple[str, int]:
    now = now or datetime.now()
    month = now.month
    season = "WINTER" if month <= 3 else "SPRING" if month <= 6 else "SUMMER" if month <= 9 else "FALL"
    return season, now.year


def season_label(season: str, year: int) -> str:
    return f"{season.title()} {year}"


def next_anime_season(season: str, year: int) -> tuple[str, int]:
    order=("WINTER","SPRING","SUMMER","FALL"); index=order.index(season)
    return (order[(index+1)%4],year+1 if season=="FALL" else year)


def graphql(query: str, variables: dict | None = None, token: str = "", timeout: int = 20,
            include_http_status: bool = False):
    from .anilist_transport import get_scheduler,Deferred
    try:response=get_scheduler().request(query,variables,token=token,origin=None,wait=True,max_retries=0,timeout=timeout)
    except Deferred as exc:
        if exc.status:
            import time
            raise AniListHTTPError(exc.status,exc.kind,max(1,int(exc.retry_at-time.time()+.99)) if exc.retry_at else None) from exc
        raise RuntimeError('AniList '+exc.kind.replace('_',' ')) from exc
    data=response.payload.get('data') or {}
    return (data,response.status) if include_http_status else data


def validate_token(token: str) -> dict:
    data = graphql("query { Viewer { id name avatar { medium } } }", token=token)
    viewer = data.get("Viewer")
    if not viewer:
        raise RuntimeError("AniList did not return an account for this token.")
    return viewer


def fetch_user_list(token: str, user_id: int) -> list[dict]:
    query = """query ($userId:Int) {
      MediaListCollection(userId:$userId, type:ANIME) { lists { entries {
        status progress updatedAt media { id episodes status season seasonYear }
      } } }
    }"""
    data = graphql(query, {"userId": int(user_id)}, token=token)
    lists = ((data.get("MediaListCollection") or {}).get("lists") or [])
    return [entry for group in lists for entry in (group.get("entries") or [])]


def update_progress(token: str, media_id: int, progress: int, completed: bool = False) -> dict:
    query = """mutation ($mediaId:Int,$progress:Int,$status:MediaListStatus) {
      SaveMediaListEntry(mediaId:$mediaId, progress:$progress, status:$status) {
        id status progress updatedAt
      }
    }"""
    variables = {"mediaId": int(media_id), "progress": max(0, int(progress)),
                 "status": "COMPLETED" if completed else "CURRENT"}
    return graphql(query, variables, token=token).get("SaveMediaListEntry") or {}


def fetch_anime_relations(media_ids) -> list[dict]:
    """One-hop relation suggestions only; never recursively crawl the graph."""
    ids=[]
    for value in media_ids:
        value=int(value)
        if value not in ids: ids.append(value)
    results={}
    allowed={"PREQUEL","SEQUEL","SIDE_STORY","PARENT","SPIN_OFF","ALTERNATIVE","OTHER"}
    # One aliased GraphQL request prevents a franchise with many children from
    # becoming a burst of identical HTTP requests (and avoids needless 429s).
    from .anilist_transport import get_scheduler,_context
    scheduler=get_scheduler();context=_context.get();scope=context.get('scope','normal')
    cached={}
    if not context.get('force'):
        cached={identifier:value for identifier in ids[:20] if (value:=scheduler.semantic('relations',identifier,scope)) is not None}
    selected=[identifier for identifier in ids[:20] if identifier not in cached]
    fields="relations { edges { relationType node { id type isAdult format episodes title { romaji english native } coverImage { extraLarge large } } } }"
    query="query { %s }" % " ".join(f"m{index}: Media(id:{source_id},type:ANIME) {{ {fields} }}" for index,source_id in enumerate(selected))
    payload=graphql(query,{"id":selected[0]}) if selected else {}
    # Compatibility with the prior single-media response also keeps test and
    # alternate GraphQL adapters usable while production uses aliased fields.
    if "Media" in payload and selected: payload={"m0":payload["Media"]}
    if any(f'm{index}' not in payload or payload[f'm{index}'] is None for index in range(len(selected))):
        raise RuntimeError('AniList returned incomplete relationship data; cached groups were retained.')
    for index,source_id in enumerate(selected):
        media=payload.get(f"m{index}") or {}
        scheduler.semantic('relations',source_id,scope,value=media,ttl=7*86400)
    for source_id in ids[:20]:
        media=cached.get(source_id) if source_id in cached else payload.get(f'm{selected.index(source_id)}') or {}
        for edge in ((media.get("relations") or {}).get("edges") or []):
            node=edge.get("node") or {}; relation=edge.get("relationType")
            if node.get("type")!="ANIME" or relation not in allowed or not node.get("id"): continue
            item=dict(node); item["relationType"]=relation; item["sourceAniListId"]=source_id; results[(source_id,int(node["id"]))]=item
    return list(results.values())


def fetch_discover_catalog(season: str | None = None, year: int | None = None) -> dict:
    """Stable page-one sources for Discover; remote titles are never persisted locally."""
    current_season,current_year=current_anime_season(); season=season or current_season; year=int(year or current_year)
    next_season,next_year=next_anime_season(season,year)
    return {
        "Trending": fetch_season_page(None,None,1,None,"TRENDING_DESC")["items"],
        "Popular": fetch_season_page(None,None,1,None,"POPULARITY_DESC")["items"],
        "Upcoming": fetch_season_page(next_season,next_year,1,"NOT_YET_RELEASED","POPULARITY_DESC")["items"],
        "Top Rated": fetch_season_page(None,None,1,None,"SCORE_DESC")["items"],
    }


def fetch_discover_filters(adult_only: bool = False) -> dict:
    data=graphql("query { GenreCollection MediaTagCollection { id name category isAdult } }")
    genres=data.get("GenreCollection") or []; tags=data.get("MediaTagCollection") or []
    if not adult_only:
        genres=[genre for genre in genres if genre.casefold()!="hentai"]
        tags=[tag for tag in tags if tag.get("isAdult") is not True and (tag.get("name") or "").casefold()!="hentai"]
    return {"genres":genres,"tags":tags}


def fetch_discover_page(page: int = 1, search: str = "", genres=None, tags=None,
                        year_from: int | None = None, year_to: int | None = None,
                        season: str | None = None, formats=None, status: str | None = None,
                        sort: str = "POPULARITY_DESC", is_adult: bool | None = None,
                        media_type: str = "ANIME", country: str | None = None,
                        source: str | None = None) -> dict:
    """Composable AniList browse/search query used by every Discover full page."""
    declarations=["$page:Int","$sort:[MediaSort]","$mediaType:MediaType"]; arguments=["type:$mediaType","sort:$sort"]
    sort_values=list(sort) if isinstance(sort,(list,tuple)) else [sort]
    variables={"page":max(1,int(page)),"sort":sort_values,"mediaType":"MANGA" if media_type=="MANGA" else "ANIME"}
    def add(name,type_name,value,argument=None):
        if value in (None,"",[]):return
        declarations.append(f"${name}:{type_name}"); arguments.append(f"{argument or name}:${name}"); variables[name]=value
    add("search","String",search.strip()); add("genres","[String]",list(genres or []),"genre_in")
    add("tags","[String]",list(tags or []),"tag_in"); add("season","MediaSeason",season)
    add("formats","[MediaFormat]",list(formats or []),"format_in"); add("status","MediaStatus",status)
    add("country","CountryCode",country,"countryOfOrigin");add("source","MediaSource",source)
    if is_adult is not None:add("adult","Boolean",bool(is_adult),"isAdult")
    if year_from: add("startAfter","FuzzyDateInt",int(year_from)*10000+101,"startDate_greater")
    if year_to: add("startBefore","FuzzyDateInt",int(year_to)*10000+1231,"startDate_lesser")
    query="""query (%s) { Page(page:$page,perPage:20) { pageInfo { currentPage hasNextPage lastPage total perPage }
      media(%s) { id title { romaji english native } description(asHtml:false) season seasonYear
      startDate { year month day } genres tags { id name rank isMediaSpoiler isAdult }
      type format status source countryOfOrigin episodes chapters volumes isAdult popularity favourites trending averageScore bannerImage coverImage { extraLarge large }
      nextAiringEpisode { airingAt episode } } } }""" % (",".join(declarations),", ".join(arguments))
    data,http_status=graphql(query,variables,include_http_status=True); container=data.get("Page") or {}
    items=container.get("media") or []
    return {"items":items,"pageInfo":container.get("pageInfo") or {},"httpStatus":http_status,
            "query":{"page":variables["page"],"search":search.strip(),"genres":list(genres or []),"tags":list(tags or []),
                     "yearFrom":year_from,"yearTo":year_to,"season":season,"formats":list(formats or []),
                     "status":status,"sort":sort_values,"isAdult":is_adult,"mediaType":variables["mediaType"],
                     "country":country,"source":source},"rawCount":len(items)}


def fetch_season_page(season: str | None, year: int | None, page: int = 1, status: str | None = None,
                      sort: str = "POPULARITY_DESC") -> dict:
    declarations=["$page:Int","$sort:[MediaSort]"]; arguments=["type:ANIME","sort:$sort"]
    variables={"page":max(1,int(page)),"sort":[sort]}
    if season is not None:
        declarations.append("$season:MediaSeason"); arguments.append("season:$season"); variables["season"]=season
    if year is not None:
        declarations.append("$year:Int"); arguments.append("seasonYear:$year"); variables["year"]=int(year)
    if status is not None:
        declarations.append("$status:MediaStatus"); arguments.append("status:$status"); variables["status"]=status
    query = """query (%s) {
      Page(page:$page, perPage:20) {
        pageInfo { currentPage hasNextPage lastPage total perPage }
        media(%s) {
          id title { romaji english native } description(asHtml:false) season seasonYear startDate { year month day }
          genres tags { id name rank isMediaSpoiler isAdult } format status episodes isAdult popularity trending averageScore
          bannerImage coverImage { extraLarge large }
          nextAiringEpisode { airingAt episode }
        }
      }
    }""" % (",".join(declarations),", ".join(arguments))
    data,http_status=graphql(query,variables,include_http_status=True)
    container=data.get("Page") or {}
    items=container.get("media") or []; page_info=container.get("pageInfo") or {}
    return {"items":items,"pageInfo":page_info,"httpStatus":http_status,
            "query":{"page":max(1,int(page)),"perPage":SEASON_PAGE_SIZE,"season":season,"seasonYear":int(year) if year is not None else None,
                     "status":status,"formatFilters":[],"sort":sort},"rawCount":len(items)}


def fetch_season(season: str, year: int, status: str | None, sort: str = "POPULARITY_DESC") -> list[dict]:
    page, results = 1, []
    while True:
        result=fetch_season_page(season,year,page,status,sort)
        results.extend(result["items"])
        if not result["pageInfo"].get("hasNextPage"):
            return results
        page += 1


def fetch_current_season(season: str | None = None, year: int | None = None) -> list[dict]:
    current_season,current_year=current_anime_season()
    return fetch_season(season or current_season,int(year or current_year),"RELEASING")


def fetch_airing_catalog(season: str | None = None, year: int | None = None) -> dict:
    current_season,current_year=current_anime_season(); season=season or current_season; year=int(year or current_year)
    next_season,next_year=next_anime_season(season,year)
    # Every discovery section keeps the exact page-one response for the query that its
    # View All page will continue.  Previously the landing page was built from an all-page
    # RELEASING catalog while Trending/Popular continued with status=None, page=2.
    # That mixed two different result sets and made AniList legitimately report no page 2.
    current=fetch_season_page(season,year,1,"RELEASING","POPULARITY_DESC")
    trending=fetch_season_page(season,year,1,None,"TRENDING_DESC")
    popular=fetch_season_page(season,year,1,None,"POPULARITY_DESC")
    currently=fetch_season_page(None,None,1,"RELEASING","POPULARITY_DESC")
    upcoming=fetch_season_page(next_season,next_year,1,"NOT_YET_RELEASED","POPULARITY_DESC")
    pages={"Trending Now":trending,"Popular This Season":popular,
           "Currently Airing":currently,"Upcoming Next Season":upcoming}
    return {"current":current["items"],"trending":trending["items"],"popular":popular["items"],
            "currently":currently["items"],"upcoming":upcoming["items"],"section_pages":pages,
            "upcoming_season":next_season,"upcoming_year":next_year}

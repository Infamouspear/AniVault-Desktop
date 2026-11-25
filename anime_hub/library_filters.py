"""Library categories describe metadata/watch state, not scanner folder labels."""
def matches_category(row, item, category, status=None):
    value=(category or '').casefold()
    if value in {'','all categories'}:return True
    kind=item.get('format');watched=row['watched_count'] or 0;episodes=row['episode_count'] or 0
    if value=='watching':return status=='Watching' or (not status and 0<watched<episodes)
    if value=='unwatched':return not watched
    if value=='airing':return item.get('status')=='RELEASING'
    if value=='finished':return item.get('status')=='FINISHED'
    if value=='movies':return kind=='MOVIE' or (not kind and row['category'].casefold()=='movies')
    if value=='specials':return kind in {'OVA','SPECIAL'}
    if value=='tv anime':return kind in {'TV','TV_SHORT'}
    if value=='web anime':return kind=='ONA'
    if value=='other':return kind not in {'TV','TV_SHORT','ONA','MOVIE','OVA','SPECIAL'}
    return row['category'].casefold()==value

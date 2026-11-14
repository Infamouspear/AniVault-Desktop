"""Public-client PIN authorization. No client secret or developer token."""
import json
from pathlib import Path
from urllib.parse import urlencode

CONFIG = Path(__file__).resolve().parent.parent / 'assets' / 'release-public.json'

def public_client_id():
    try: value=str(json.loads(CONFIG.read_text()).get('anilist_client_id',''))
    except (OSError,ValueError): return ''
    return value if value.isdecimal() and int(value)>0 else ''

def authorization_url(client_id=None):
    client_id = client_id or public_client_id()
    if not client_id or not str(client_id).isdecimal():
        raise ValueError('AniList linking is not configured in this release candidate. Your local library remains usable. The publisher must supply the public application ID before distributing V1.0.')
    return 'https://anilist.co/api/v2/oauth/authorize?' + urlencode({'client_id':client_id,'response_type':'token'})

"""Explicit application-only allowlist. Never copy a worktree or AppData wholesale."""
from pathlib import Path
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ('anivault.ico','anivault_icon.png','caught_up_vee.png','empty_vee.png',
          'no_results_vee.png','restricted_banner.png','restricted_vee.png','splash.png','vee.png','release-public.json')
ICONS = ('house','tv','book-open','circle-play','plus','heart','compass','calendar',
         'bookmark','layers','tags','download','settings','lock','refresh-cw','chevron-left','chevron-right','search','chevron-down','chart-column')

def stage(destination, client_id=None, *, offline_candidate=False):
    destination = Path(destination).resolve()
    if destination.exists(): raise ValueError('Use an empty staging destination.')
    if destination == ROOT or destination in ROOT.parents: raise ValueError('Unsafe staging destination.')
    config=json.loads((ROOT/'assets/release-public.json').read_text())
    if set(config) != {'anilist_client_id'}:raise ValueError('Public release config must contain no secrets or extra fields.')
    if client_id is not None:config['anilist_client_id']=str(client_id)
    value=str(config['anilist_client_id'])
    if not (value.isdecimal() and int(value)>0) and not (offline_candidate and value==''):
        raise ValueError('Publisher must configure a public AniList client ID; no secrets or tokens are permitted.')
    files = [ROOT/'main.py'] + sorted((ROOT/'anime_hub').glob('*.py'))
    files += [ROOT/'assets'/name for name in ASSETS]
    files += [ROOT/'assets/icons'/(name+'.svg') for name in ICONS]
    files += [ROOT/'assets/icons/LICENSE']
    destination.mkdir(parents=True)
    manifest=[]
    for source in files:
        if source.is_symlink() or not source.is_file(): raise ValueError('Missing or unsafe release input: '+str(source))
        target=destination/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        if source.name=='release-public.json':target.write_text(json.dumps(config)+'\n')
        else:shutil.copyfile(source,target)
        manifest.append({'path':source.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    (destination/'release-manifest.json').write_text(json.dumps(manifest,indent=2))
    print('ReleaseStage files='+str(len(files))+' personal_state_included=false')
    return manifest

if __name__ == '__main__':
    args=sys.argv[2:]
    offline=args==['--offline-candidate']
    stage(sys.argv[1],args[0] if args and not offline else None,offline_candidate=offline)

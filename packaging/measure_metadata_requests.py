import sys,json,io,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
import argparse
parser=argparse.ArgumentParser(description='Compare metadata request counts against an extracted 1.9.0 source release using mocked HTTP.')
parser.add_argument('mode',choices=['before','after']);parser.add_argument('--baseline-source',type=Path);parser.add_argument('--workdir',type=Path,required=True)
args=parser.parse_args();mode=args.mode
if mode=='before' and (args.baseline_source is None or not (args.baseline_source/'anime_hub/scanner.py').is_file()):parser.error('--baseline-source must contain the extracted 1.9.0 application source')
sys.path.insert(0,str(args.baseline_source.resolve()) if mode=='before' else str(ROOT))
from anime_hub.database import Database
from anime_hub import scanner,metadata
folder=args.workdir.resolve()/mode;folder.mkdir(parents=True,exist_ok=True);root=folder/'Anime'
if root.exists():raise RuntimeError('Fresh benchmark directory required')
for title,season in [('Arifureta',1),('Arifureta',2),('Arifureta',3),('Cyberpunk Edgerunners',1),('Cyberpunk Edgerunners',2),('Uncatalogued Alpha',1),('Uncatalogued Beta',1)]:
 path=root/(title+f' S{season:02}');path.mkdir(parents=True);(path/f'S{season:02}E01.mkv').touch()
ova=root/'My Hero Academia OVAs';ova.mkdir()
for name in ['All Might Rising','Training of the Dead','Make It Do or Die Part 1','Make It Do or Die Part 2']:(ova/('[Anime Time] My Hero Academia OVA - '+name+'.mkv')).touch()
pack=root/'Example Saga Complete Series + OVAs, Specials'
for number in range(1,4):
 path=pack/'Season 1';path.mkdir(parents=True,exist_ok=True);(path/f'Example Saga - {number:02}.mkv').touch()
for name in ('New Adventure','Side Story'):(pack/f'Example Saga OVA - {name}.mkv').touch()
def item(i,title,format='TV'):return {'id':i,'title':{'english':title},'isAdult':False,'type':'ANIME','format':format,'coverImage':{}}
ari=[item(100668,'Arifureta: From Commonplace to World\'s Strongest'),item(112323,'Arifureta: From Commonplace to World\'s Strongest Season 2'),item(154473,'Arifureta: From Commonplace to World\'s Strongest Season 3')]
cyber=[item(120377,'Cyberpunk: Edgerunners','ONA'),item(195539,'Cyberpunk: Edgerunners 2','ONA')]
calls=[]
class Response(io.BytesIO):
 status=200;headers={}
def network(request,**kwargs):
 variables=json.loads(request.data)['variables'];q=variables.get('search','');calls.append(q)
 data=ari if 'arifureta' in q.lower() else cyber if 'cyberpunk' in q.lower() else []
 return Response(json.dumps({'data':{'Page':{'media':data}}}).encode())
if mode=='after':
 from anime_hub.anilist_transport import Scheduler,configure
 from anime_hub import metadata_jobs
 transport=Scheduler(folder/'transport',min_interval=0,default_limit=10000);configure(folder,transport)
else:
 original_client=metadata.AniListClient
 scanner.AniListClient=lambda **kw:original_client(min_interval=0,**kw)
db=Database(folder/'vault.db');counts=[];elapsed=[]
with patch('urllib.request.urlopen',side_effect=network),patch('anime_hub.scanner.cache_artwork',side_effect=lambda item,path:item):
 for cycle in range(3):
  if cycle==2:
   db.connection.close();db=Database(folder/'vault.db')
   if mode=='after':transport=Scheduler(folder/'transport',min_interval=0,default_limit=10000);configure(folder,transport)
  start=len(calls);timer=time.monotonic()
  if mode=='before':scanner.scan(root,db)
  else:
   scanner.scan(root,db,match_online=False)
   metadata_jobs.process(db,scheduler=transport,max_jobs=1000)
  counts.append(len(calls)-start);elapsed.append(round(time.monotonic()-timer,3))
result={'mode':mode,'library_roots':9,'video_files':16,'cycles':['initial','unchanged rescan','restart and unchanged rescan'],'api_requests':counts,'total':sum(counts),'seconds':elapsed,'network':'mocked; no live API traffic'}
print(json.dumps(result));(args.workdir.resolve()/(mode+'.json')).write_text(json.dumps(result,indent=2));db.connection.close()

"""One AniList transport budget, coalesced requests and scoped persistent caches.

No token, query text, variables, title or path is written to diagnostics.
"""
import contextlib,contextvars,copy,email.utils,hashlib,json,os,sqlite3,threading,time,urllib.error,urllib.request
from collections import Counter,deque
from dataclasses import dataclass
from pathlib import Path

_context=contextvars.ContextVar('anilist_request_context',default={})

@contextlib.contextmanager
def request_context(**values):
    marker=_context.set({**_context.get(),**values})
    try:yield
    finally:_context.reset(marker)

class Deferred(RuntimeError):
    def __init__(self,kind,retry_at=0,status=None,attempts=0,retries=0):
        super().__init__('AniList '+kind);self.kind=kind;self.retry_at=retry_at;self.status=status;self.attempts=attempts;self.retries=retries

@dataclass
class Response:
    payload:dict
    status:int=200
    headers:dict=None
    requests:int=0
    retries:int=0
    rate_limited:bool=False
    cached:bool=False


def public_payload(value):
    if isinstance(value,list):return [clean for item in value if (clean:=public_payload(item)) is not None]
    if isinstance(value,dict):
        if value.get('isAdult') is True:return None
        result={k:public_payload(v) for k,v in value.items()}
        if ('relationType' in result and result.get('node') is None) or ('mediaId' in result and result.get('media') is None):return None
        return result
    return value


class Scheduler:
    def __init__(self,directory=None,*,clock=time.time,sleep=time.sleep,default_limit=30,min_interval=None):
        self.directory=Path(directory) if directory else None;self.clock=clock;self.sleep=sleep
        self.error_streak=0;self.pause_kind='rate_limited';self.limit=default_limit;self.min_interval=min_interval;self.next_at=0;self.blocked_until=0;self.reset_at=0;self.remaining=None
        self.sent=deque();self.condition=threading.Condition();self.tickets=[];self.sequence=0;self.active=False;self.flights={};self.memory={};self.metrics={'normal':Counter(),'restricted':Counter()};self.events=deque(maxlen=160)
        if self.directory:self.directory.mkdir(parents=True,exist_ok=True)
        saved=self._read('budget','shared',scope='normal',expired=True)
        if saved:
            self.limit=saved.get('limit',default_limit);self.next_at=saved.get('next_at',0);self.blocked_until=saved.get('blocked_until',0);self.sent=deque(saved.get('sent',[]));self.pause_kind=saved.get('pause_kind','rate_limited');self.error_streak=saved.get('error_streak',0)

    def _database(self,scope):
        folder=self.directory/('restricted' if scope=='restricted' else 'normal');folder.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(folder/'requests.sqlite3',timeout=2)
        c.execute('CREATE TABLE IF NOT EXISTS cache(kind TEXT,key TEXT,created REAL,expires REAL,payload TEXT,PRIMARY KEY(kind,key))')
        return c

    def _read(self,kind,key,scope='normal',expired=False):
        with self.condition:
            row=self.memory.get((scope,kind,key))
        if row is None and self.directory:
            c=self._database(scope)
            try:row=c.execute('SELECT created,expires,payload FROM cache WHERE kind=? AND key=?',(kind,key)).fetchone()
            finally:c.close()
            if row:
                try:row=(row[0],row[1],json.loads(row[2]))
                except (ValueError,TypeError):row=None
        if row and (expired or row[1]>self.clock()):return copy.deepcopy(row[2])
        return None

    def _write(self,kind,key,payload,ttl,scope='normal'):
        now=self.clock();value=public_payload(payload) if scope=='normal' and kind!='budget' else payload
        if value is None:return
        with self.condition:self.memory[(scope,kind,key)]=(now,now+ttl,copy.deepcopy(value))
        if self.directory:
            c=self._database(scope)
            try:
                with c:
                    c.execute('INSERT INTO cache VALUES(?,?,?,?,?) ON CONFLICT(kind,key) DO UPDATE SET created=excluded.created,expires=excluded.expires,payload=excluded.payload',(kind,key,now,now+ttl,json.dumps(value)))
                    c.execute('DELETE FROM cache WHERE expires<? AND kind<>?',(now-86400,'budget'))
            finally:c.close()

    def semantic(self,kind,key,scope='normal',value=None,ttl=86400):
        digest=hashlib.sha256(str(key).encode()).hexdigest()
        if value is not None:self._write(kind,digest,value,ttl,scope)
        else:return self._read(kind,digest,scope)

    def _save_budget(self):
        self._write('budget','shared',{'limit':self.limit,'next_at':self.next_at,'blocked_until':self.blocked_until,'sent':list(self.sent),'pause_kind':self.pause_kind,'error_streak':self.error_streak},86400)

    def snapshot(self,scope='normal'):
        with self.condition:return {'counts':dict(self.metrics[scope]),'waiting':sum(t[2]==scope for t in self.tickets),'limit':self.limit,'next_eligible':max(self.next_at,self.blocked_until),'events':[dict(e) for e in self.events if e['scope']==scope][-30:]}

    def _event(self,origin,scope,kind,key='',status=None):
        with self.condition:
            self.metrics[scope][kind]+=1
            self.events.append({'origin':str(origin).split(':',1)[0][:40],'scope':scope,'event':kind,'key':key[:12],'status':status})

    def eligible_at(self):
        with self.condition:
            now=self.clock()
            while self.sent and self.sent[0]<=now-60:self.sent.popleft()
            return max(self.next_at,self.blocked_until,(self.sent[0]+60 if len(self.sent)>=self.limit else 0))

    def _reserve(self,priority,scope,cancel,status,wait):
        with self.condition:
            self.sequence+=1;ticket=(priority,self.sequence,scope);self.tickets.append(ticket)
        try:
            notified=False
            while True:
                if cancel():raise Deferred('cancelled')
                with self.condition:
                    eligible=self.eligible_at();now=self.clock()
                    if not self.active and ticket==min(self.tickets) and now>=eligible:
                        self.tickets.remove(ticket);self.active=True;self.sent.append(now)
                        interval=self.min_interval if self.min_interval is not None else max(.5,60/max(1,self.limit)+.05)
                        self.next_at=now+interval;return
                if not wait:raise Deferred(self.pause_kind if self.blocked_until>now else 'waiting',eligible,status=429 if self.blocked_until>now and self.pause_kind=='rate_limited' else None)
                if not notified:
                    status('AniList metadata waiting for the shared request budget; local files remain available.');notified=True
                if self.sleep is time.sleep:
                    with self.condition:self.condition.wait(min(.25,max(.01,eligible-now)))
                else:self.sleep(min(.25,max(.01,eligible-now)))
        finally:
            with self.condition:
                if ticket in self.tickets:self.tickets.remove(ticket)

    def _observe(self,headers,status,retry=0):
        headers={k.casefold():v for k,v in dict(headers or {}).items()};now=self.clock()
        with self.condition:
            try:self.limit=max(1,min(10000,int(headers.get('x-ratelimit-limit',self.limit))))
            except (TypeError,ValueError):pass
            try:self.remaining=int(headers['x-ratelimit-remaining'])
            except (KeyError,ValueError,TypeError):self.remaining=None
            try:self.reset_at=float(headers['x-ratelimit-reset'])
            except (KeyError,ValueError,TypeError):self.reset_at=0
            if status==429:
                self.pause_kind='rate_limited'
                raw=headers.get('retry-after');delay=None
                if raw is not None:
                    try:delay=max(0,float(raw))
                    except ValueError:
                        try:delay=max(0,email.utils.parsedate_to_datetime(raw).timestamp()-now)
                        except (ValueError,TypeError,OverflowError):pass
                delay=max(0,self.reset_at-now,delay if delay is not None else min(300,5*2**retry))
                self.blocked_until=max(self.blocked_until,now+delay)
            elif self.remaining==0:self.pause_kind='rate_limited';self.blocked_until=max(self.blocked_until,self.reset_at if self.reset_at>now else now+60)
            interval=self.min_interval if self.min_interval is not None else max(.5,60/self.limit+.05)
            if self.remaining and self.reset_at>now:interval=max(interval,(self.reset_at-now)/(self.remaining+1))
            self.next_at=now+interval
        self._save_budget()

    def request(self,query,variables=None,*,token='',origin=None,scope=None,priority=None,ttl=None,force=False,cancel=None,status=None,wait=True,max_retries=0,timeout=20):
        context=_context.get();origin=origin or context.get('origin','metadata');scope=scope or context.get('scope','normal')
        if scope not in ('normal','restricted'):raise ValueError('Invalid metadata scope')
        priority=priority if priority is not None else context.get('priority',20);cancel=cancel or context.get('cancel',lambda:False);status=status or (lambda _:None)
        force=force or context.get('force',False)
        variables=variables or {};private=variables.get('adult') is True or variables.get('isAdult') is True
        if private:scope='restricted'
        mutation=query.lstrip().startswith('mutation');persistent=not token and not mutation
        if ttl is None:ttl=86400 if ('relations' in query or 'search' in variables or 'Media(id:' in query) else 300
        if not persistent:ttl=0
        key=hashlib.sha256(json.dumps([query,variables,hashlib.sha256(token.encode()).hexdigest() if token else '',scope],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if ttl and not force:
            cached=self._read('response',key,scope)
            if cached is not None:self._event(origin,scope,'cache_hit',key);return Response(cached,cached=True)
        self._event(origin,scope,'cache_miss',key)
        owner=True;flight=None
        if not mutation:
            with self.condition:
                flight=self.flights.get((scope,key))
                if flight:owner=False
                else:flight={'event':threading.Event()};self.flights[(scope,key)]=flight
        if not owner:
            self._event(origin,scope,'coalesced',key)
            while not flight['event'].wait(.1):
                if cancel():raise Deferred('cancelled')
            if 'error' in flight:raise flight['error']
            result=copy.deepcopy(flight['result']);result.requests=0;result.retries=0;return result
        requests=retries=0;rate_limited=False
        try:
            negative=self._read('failure',key,scope) if not force else None
            if negative:raise Deferred(negative['kind'],negative['retry_at'],negative.get('status'))
            while True:
                self._reserve(priority,scope,cancel,status,wait)
                try:
                    if cancel():raise Deferred('cancelled')
                    requests+=1;self._event(origin,scope,'request',key)
                    headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'AniVault-Desktop'}
                    if token:headers['Authorization']='Bearer '+token.strip()
                    req=urllib.request.Request('https://graphql.anilist.co',data=json.dumps({'query':query,'variables':variables}).encode(),headers=headers)
                    with urllib.request.urlopen(req,timeout=timeout) as response:
                        code=int(getattr(response,'status',200));response_headers=dict(getattr(response,'headers',{}) or {});payload=json.load(response)
                    if not isinstance(payload,dict) or ('data' not in payload and 'errors' not in payload):raise Deferred('invalid_response',self.clock()+300,status=code,attempts=requests)
                    errors=payload.get('errors') or []
                    if errors:
                        if any(isinstance(e,dict) and e.get('status')==429 for e in errors):code=429
                        else:raise Deferred('invalid_response',self.clock()+300,status=code,attempts=requests)
                    if code==429:raise urllib.error.HTTPError('https://graphql.anilist.co',429,'Rate limited',response_headers,None)
                    if not isinstance(payload.get('data'),dict) or not payload['data']:raise Deferred('invalid_response',self.clock()+300,status=code,attempts=requests)
                    if any(value is None for value in payload['data'].values()):ttl=min(ttl,300)
                    self.error_streak=0
                    self._observe(response_headers,code)
                    clean=public_payload(payload) if scope=='normal' and not token else payload
                    if clean is None:clean={'data':{}}
                    if ttl:self._write('response',key,clean,ttl,scope)
                    result=Response(clean,code,response_headers,requests,retries,rate_limited)
                    if flight is not None:flight['result']=result
                    return result
                except urllib.error.HTTPError as exc:
                    code=exc.code;self._observe(exc.headers,code,retries)
                    if code==429:
                        rate_limited=True;self._event(origin,scope,'http_429',key,429)
                        if wait and retries<max_retries:
                            retries+=1;status('AniList rate limit reached — metadata paused; local library scanning is independent.');continue
                        raise Deferred('rate_limited',self.blocked_until,429,requests,retries+1)
                    raise Deferred('api_unavailable' if code>=500 else 'http_error',self.clock()+(60 if code>=500 else 900),code,requests,retries)
                except (TimeoutError,__import__('socket').timeout):raise Deferred('timeout',self.clock()+60,attempts=requests)
                except urllib.error.URLError as exc:raise Deferred('timeout' if isinstance(exc.reason,TimeoutError) else 'network',self.clock()+60,attempts=requests)
                except (ValueError,TypeError,KeyError):raise Deferred('invalid_response',self.clock()+300,attempts=requests)
                finally:
                    with self.condition:self.active=False;self.condition.notify_all()
        except Deferred as exc:
            if exc.kind in {'network','timeout','api_unavailable'}:
                if exc.attempts:
                    delay=min(3600,60*2**min(6,self.error_streak));self.error_streak+=1;exc.retry_at=max(exc.retry_at,self.clock()+delay)
                self.blocked_until=max(self.blocked_until,exc.retry_at);self.pause_kind=exc.kind;self._save_budget()
            self._event(origin,scope,exc.kind,key,exc.status)
            if persistent and exc.kind not in ('waiting','rate_limited','cancelled'):
                self._write('failure',key,{'kind':exc.kind,'retry_at':exc.retry_at,'status':exc.status},max(1,exc.retry_at-self.clock()),scope)
            if flight is not None:flight['error']=exc
            raise
        finally:
            if flight is not None:
                with self.condition:self.flights.pop((scope,key),None);flight['event'].set();self.condition.notify_all()


_registry={};_registry_lock=threading.Lock();_default_directory=None

def configure(directory,scheduler=None):
    global _default_directory
    key=str(Path(directory).resolve())
    with _registry_lock:
        _default_directory=key
        if scheduler is not None:_registry[key]=scheduler
        if key not in _registry:_registry[key]=Scheduler(Path(key)/'cache'/'anilist_requests')
        return _registry[key]

def get_scheduler():
    if _default_directory is None:return configure(Path(os.getenv('LOCALAPPDATA',Path.home()))/'AnimeHub')
    return _registry[_default_directory]

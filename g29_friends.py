"""Opt-in fixed-room WebSocket transport. No game data is stored remotely."""
import json
import math
import threading
import time
from urllib.parse import urlsplit
import websocket

def endpoint(value):
    p=urlsplit(value.strip())
    if p.scheme not in ('https','wss') or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('Enter the HTTPS address of your Cloudflare server.')
    return 'wss://'+p.netloc+'/room'

class FriendsLink:
    def __init__(self,url,code,name):
        self.url=endpoint(url)
        if not 12<=len(code)<=128: raise ValueError('The fixed room code must contain 12 to 128 characters.')
        self.code,self.name=code,name.strip()[:20] or 'Driver'
        self.id='';self.pos=None;self.updated=0;self.players=[];self.last_reply=0
        self.error='Connecting';self.lock=threading.Lock();self.stop=threading.Event();self.sock=None
        self.smoothed={};self.last_frame=time.monotonic()
        threading.Thread(target=self.run,daemon=True).start()

    def run(self):
        seq=0
        while not self.stop.is_set():
            try:
                self.sock=websocket.create_connection(self.url,header={'Authorization':'Bearer '+self.code},timeout=3,redirect_limit=0)
                while not self.stop.is_set():
                    started=time.monotonic()
                    with self.lock: pos=self.pos if started-self.updated<1.2 else None
                    seq+=1
                    self.sock.send(json.dumps(dict(seq=seq,name=self.name,pos=pos),allow_nan=False))
                    raw=self.sock.recv()
                    if not isinstance(raw,str) or len(raw)>4096: raise ValueError('Invalid server reply')
                    msg=json.loads(raw);players=msg['players']
                    if not isinstance(players,list) or len(players)>4: raise ValueError('Invalid players')
                    for p in players:
                        if not isinstance(p.get('id'),str) or not isinstance(p.get('name'),str): raise ValueError('Invalid player')
                        v=p.get('pos')
                        if v is not None and (not isinstance(v,list) or len(v)!=2 or not all(isinstance(x,(int,float)) and math.isfinite(x) and abs(x)<1e7 for x in v)): raise ValueError('Invalid position')
                    with self.lock:
                        self.id=msg['id'];self.players=players;self.last_reply=time.monotonic();self.error='Connected'
                    self.stop.wait(max(0,.2-(time.monotonic()-started)))
            except Exception as exc:
                status=getattr(exc,'status_code',None)
                self.error={401:'Invalid room code',409:'Room full (4 players)',503:'Server not configured'}.get(status,'Disconnected - reconnecting')
                if status in (401,409,503): self.stop.set()
            finally:
                if self.sock:self.sock.close()
                self.sock=None
            self.stop.wait(3)

    def snapshot(self,pos):
        with self.lock:
            self.pos=pos;self.updated=time.monotonic()
            fresh=time.monotonic()-self.last_reply<3
            now=time.monotonic();alpha=1-math.exp(-(now-self.last_frame)/.08);self.last_frame=now
            result=[]
            for p in self.players if fresh else []:
                p=dict(p);target=p['pos'];old=self.smoothed.get(p['id'])
                if target is not None:
                    if old is not None and math.dist(old,target)<250:
                        target=[a+(b-a)*alpha for a,b in zip(old,target)]
                    self.smoothed[p['id']]=target;p['pos']=target
                else:self.smoothed.pop(p['id'],None)
                result.append(p)
            self.smoothed={p['id']:self.smoothed[p['id']] for p in result if p['id'] in self.smoothed}
            return result,fresh

    def close(self):
        self.stop.set()
        sock=self.sock
        if sock:
            try:sock.close()
            except OSError:pass

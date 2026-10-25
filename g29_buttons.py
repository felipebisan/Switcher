"""Identify actual HID button bits; never learn axes, hats or status fields."""
def button_layout(descriptor):
    state={'page':0,'size':0,'count':0,'id':0}
    stack=[];offsets={};buttons={};i=0
    while i<len(descriptor):
        prefix=descriptor[i];i+=1
        if prefix==254:
            if i+2>len(descriptor):raise ValueError('Truncated descriptor')
            length=descriptor[i];i+=2+length;continue
        length=(0,1,2,4)[prefix&3]
        if i+length>len(descriptor):raise ValueError('Truncated descriptor')
        value=int.from_bytes(bytes(descriptor[i:i+length]),'little');i+=length
        kind=(prefix>>2)&3;tag=prefix>>4
        if kind==1:
            key={0:'page',7:'size',8:'id',9:'count'}.get(tag)
            if key:state[key]=value
            elif tag==10:stack.append(state.copy())
            elif tag==11:
                if not stack:raise ValueError('Invalid HID stack')
                state=stack.pop()
        elif kind==0 and tag==8:
            rid=state['id'];offset=offsets.get(rid,0)
            if state['page']==9 and state['size']==1 and value&3==2:
                for bit in range(offset,offset+state['count']):
                    byte=bit//8+(1 if rid else 0)
                    if byte<64:buttons.setdefault(rid,set()).add((byte,1<<(bit%8)))
            offsets[rid]=offset+state['size']*state['count']
    return {rid:(pairs,(offsets[rid]+7)//8+(1 if rid else 0)) for rid,pairs in buttons.items()}

def pressed(data,layout):
    rid=data[0] if data and 0 not in layout else 0
    pairs,size=layout.get(rid,(set(),0))
    if not size or len(data)<size:return None
    return {pair for pair in pairs if data[pair[0]]&pair[1]}

def is_pressed(data,layout,byte,mask):
    keys=pressed(data,layout)
    return keys is not None and (byte,mask) in keys

class ButtonCapture:
    def __init__(self):
        self.baseline=None
        self.candidate=None
        self.since=None
        self.blocked=False

    def feed(self,data,layout,now):
        keys=pressed(data,layout)
        if keys is None:return None
        if self.baseline is None:
            self.baseline=set(keys)
            return None
        # A gear or another control already held at entry is not a new press.
        self.baseline.intersection_update(keys)
        new=keys-self.baseline
        if self.blocked:
            if not new:self.blocked=False
            return None
        if self.candidate is None:
            if len(new)==1:
                self.candidate=next(iter(new));self.since=now
            elif len(new)>1:self.blocked=True
            return None
        if new-{self.candidate}:
            self.candidate=None;self.blocked=True
            return None
        if self.candidate not in keys:
            # Use elapsed time at release; no repeated held reports required.
            result=self.candidate if now-self.since>=.02 else None
            self.candidate=None;self.since=None
            return result
        return None

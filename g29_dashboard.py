"""Instrument-cluster presentation of existing local telemetry and road map."""
import math
import os
import struct
import time
from g29_shiftprofile import shift_state
from PIL import Image, ImageDraw, ImageFont

SIZE=(860,300)


def panel_size(percent, screen_width, screen_height, show_map=True):
    base=SIZE
    scale=min(percent/100,max(1,screen_width-40)/base[0],max(1,screen_height-40)/base[1])
    return tuple(max(1,round(v*scale)) for v in base)


def read_instruments(data):
    if len(data)!=324 or struct.unpack_from('<i',data)[0]!=1:return None
    maximum=struct.unpack_from('<f',data,8)[0]
    rpm=struct.unpack_from('<f',data,16)[0]
    speed=struct.unpack_from('<f',data,256)[0]*3.6
    if not all(math.isfinite(v) for v in (maximum,rpm,speed)):return None
    gear=data[319]
    return {'rpm':max(0,rpm),'maximum':max(1000,maximum),'speed':max(0,speed),
            'gear':'R' if gear==0 else 'N' if gear==11 else str(gear) if 1<=gear<=10 else '—'}


class DashboardRenderer:
    def __init__(self):
        self.fonts={}
        self.background=None
        self.key=None
        self.composite=None
        self.map_reference=None
        self.needle_values=None
        self.needle_time=None

    def font(self,size):
        if size not in self.fonts:
            try:self.fonts[size]=ImageFont.truetype(os.path.join(os.environ.get('WINDIR','C:/Windows'),'Fonts','segoeuib.ttf'),int(size*2))
            except OSError:self.fonts[size]=ImageFont.load_default()
        return self.fonts[size]

    def render(self,map_image,instruments,transparent=True,dark_dials=False,now=None,show_map=True,shift_light=False,hardware_warning=None):
        values=instruments or {'rpm':0,'maximum':8000,'speed':0,'gear':'—'}
        rpm_limit=max(4000,math.ceil(values['maximum']/1000)*1000)
        speed_limit=max(320,math.ceil(values['speed']/40)*40)
        key=(rpm_limit,speed_limit,transparent,dark_dials)
        def xy(cx,cy,r,angle):
            a=math.radians(angle);return ((cx+r*math.cos(a))*2,(cy+r*math.sin(a))*2)
        if key!=self.key:
            base=Image.new('RGBA',(1720,600))
            d=ImageDraw.Draw(base)
            if not transparent:
                d.rounded_rectangle((2,2,1718,598),radius=48,fill=(8,11,16,237),outline=(57,67,80,210),width=2)
            for cx,limit,step in ((150,rpm_limit,1000),(710,speed_limit,40)):
                d.ellipse(((cx-128)*2,22*2,(cx+128)*2,278*2),fill=((12,22,35,145) if transparent else (12,22,35,255)) if dark_dials or not transparent else None,outline='#526071',width=2)
                d.arc(((cx-118)*2,32*2,(cx+118)*2,268*2),135,405,fill='#C6D1DF',width=3)
                d.arc(((cx-118)*2,32*2,(cx+118)*2,268*2),351,405,fill='#F34C56',width=6)
                count=round(limit/step)*4
                for i in range(count+1):
                    a=135+270*i/count;major=i%4==0
                    d.line([xy(cx,150,110 if major else 115,a),xy(cx,150,120,a)],fill='#EFF4FA',width=3 if major else 1)
                    if major:
                        label=str(round(limit*i/count/(1000 if cx==150 else 1)))
                        d.text(xy(cx,150,96,a),label,font=self.font(12),anchor='mm',fill='#D5DFEC',stroke_width=2,stroke_fill='#10151C')
                d.arc(((cx-72)*2,78*2,(cx+72)*2,222*2),200,340,fill='#546175',width=2)
            d.text((860,30),'SWITCHER  /  DRIVE',font=self.font(11),anchor='mm',fill='#9DAABD')
            d.line((580,564,1140,564),fill='#E83D49',width=4)
            self.background,self.key=base.resize(SIZE,Image.Resampling.LANCZOS),key
            self.composite=None
        if self.composite is None or self.map_reference is not map_image or getattr(self,'map_visible',None)!=show_map:
            self.composite=self.background.copy()
            if show_map:self.composite.alpha_composite(map_image.resize((270,240),Image.Resampling.LANCZOS),(295,30))
            self.map_reference=map_image
            self.map_visible=show_map
        im=self.composite.copy()
        d=ImageDraw.Draw(im)
        now=time.monotonic() if now is None else now
        target=[values['rpm'],values['speed']]
        if self.needle_time is None or now-self.needle_time>.25 or instruments is None:
            self.needle_values=target
        else:
            blend=1-math.exp(-max(0,now-self.needle_time)/.045)
            self.needle_values=[a+(b-a)*blend for a,b in zip(self.needle_values,target)]
        self.needle_time=now
        for cx,value,limit in ((150,self.needle_values[0],rpm_limit),(710,self.needle_values[1],speed_limit)):
            a=135+270*min(1,max(0,value/limit))
            # Needles occupy the outer dial, leaving digital readouts unobscured.
            points=[tuple(v/2 for v in xy(cx,150,r,a)) for r in (78,114)]
            x0=math.floor(min(p[0] for p in points))-4;y0=math.floor(min(p[1] for p in points))-4
            w=math.ceil(max(p[0] for p in points))-x0+5;h=math.ceil(max(p[1] for p in points))-y0+5
            needle=Image.new('RGBA',(w*2,h*2))
            ImageDraw.Draw(needle).line([((x-x0)*2,(y-y0)*2) for x,y in points],fill='#FF414F',width=7)
            im.alpha_composite(needle.resize((w,h),Image.Resampling.LANCZOS),(x0,y0))
        def label(x,y,text,size,color='#F4F7FC'):
            d.text((x,y),text,font=self.font(size/2),anchor='mm',fill=color,stroke_width=1,stroke_fill='#10151C')
        label(150,130,values['gear'],48)
        label(150,171,'GEAR',10,'#9CAABE')
        label(150,200,f"{values['rpm']:,.0f} RPM",14)
        label(710,137,str(round(values['speed'])),48)
        label(710,183,'km/h',14,'#9CAABE')
        label(150,253,'RPM × 1000',10,'#9CAABE')
        label(710,253,'SPEED',10,'#9CAABE')
        if shift_light and not show_map:
            lit,color=shift_state(values['rpm'] if instruments else 0,values['maximum'],6,now)
            if color=='#FF4D4D' and hardware_warning is not None:
                lit=6 if hardware_warning else 0
            for i in range(12):
                x=298+i*22
                d.rounded_rectangle((x,125,x+16,149),radius=5,fill=color if min(i,11-i)<lit else (32,46,62,130))
        return im

"""Road-only minimap renderer and click-through Windows per-pixel overlay."""
import ctypes
from ctypes import wintypes as wt
import json
import math
import os
from collections import Counter
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageFilter
from g29_mapmatch import RoadMatcher

SIZE = (320, 300)
ANCHOR = (160, 174)


def smooth_path(path):
    """Remove pixel-scale zigzags without moving road junctions or closing gaps."""
    points = [tuple(path[0])]
    for a, b in zip(path, path[1:]):
        count = max(1, math.ceil(math.dist(a, b)/2))
        points.extend((a[0]+(b[0]-a[0])*i/count,
                       a[1]+(b[1]-a[1])*i/count) for i in range(1, count+1))
    for _ in range(3):
        points = [points[0]] + [
            ((a[0]+2*b[0]+c[0])/4, (a[1]+2*b[1]+c[1])/4)
            for a,b,c in zip(points, points[1:], points[2:])
        ] + [points[-1]]
    return points


def road_mask(paths, width):
    """Union round strokes at 4x resolution: intersections have no alpha seams."""
    mask = Image.new('L', (1280,1200))
    draw = ImageDraw.Draw(mask)
    radius = (width-1)/2
    for path in paths:
        points = [(x*2,y*2) for x,y in path]
        draw.line(points, fill=255, width=width, joint='curve')
        for x,y in (points[0],points[-1]):
            draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
    return mask.resize((640,600), Image.Resampling.LANCZOS)


class MinimapRenderer:
    def __init__(self, roads):
        self.roads = roads
        self.paths = []
        self.atlas_key = None
        self.atlas_masks = None
        self.error = ''
        try:
            data = json.loads((roads.assets/'roads.json').read_text(encoding='utf-8'))
            if data['atlas_size'] != list(roads.image.size):
                raise ValueError('Road geometry does not match the calibrated map.')
            endpoints=Counter(tuple(p) for path in data['paths'] for p in (path[0],path[-1]))
            for path in data['paths']:
                # Discard tiny terminal spurs from screenshot thinning, never junction links.
                if (min(endpoints[tuple(path[0])],endpoints[tuple(path[-1])]) == 1
                        and sum(math.dist(a,b) for a,b in zip(path,path[1:])) < 5):
                    continue
                xs,ys=zip(*path)
                self.paths.append((smooth_path(path),(min(xs),min(ys),max(xs),max(ys))))
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            self.error=str(exc)
        self.matcher=RoadMatcher(self.paths)
        self.assist=True
        self.font=ImageFont.load_default()
        try:
            self.font=ImageFont.truetype(os.path.join(os.environ.get('WINDIR','C:/Windows'),'Fonts','segoeuib.ttf'),22)
        except OSError: pass
        self.feather=Image.new('L',(640,600))
        self.feather.putdata([int(255*min(1,max(0,(1-math.hypot((x-320)/320,(y-300)/296))/.16)))
                             for y in range(600) for x in range(640)])

    def project(self, point, center, radius, angle):
        px,py=self.roads.to_pixel(point); cx,cy=self.roads.to_pixel(center)
        scale=126/(radius*self.roads.pixels_per_meter)
        dx,dy=(px-cx)*scale,(py-cy)*scale
        co,si=math.cos(angle),math.sin(angle)
        return ANCHOR[0]+co*dx+si*dy, ANCHOR[1]-si*dx+co*dy

    def road_layers(self, cx, cy, scale, angle):
        # Rasterize once per zoom. Each frame only transforms two cached masks.
        key = round(scale, 9)
        if key != self.atlas_key:
            size = tuple(v*4 for v in self.roads.image.size)
            masks = []
            for screen_width in (10, 8):
                mask = Image.new('L', size)
                draw = ImageDraw.Draw(mask)
                width = max(1, round(screen_width*4/scale))
                radius = (width-1)/2
                for path, _ in self.paths:
                    points = [(x*4,y*4) for x,y in path]
                    draw.line(points, fill=255, width=width, joint='curve')
                    for x,y in (points[0],points[-1]):
                        draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
                masks.append(mask.resize(tuple(v*2 for v in self.roads.image.size),Image.Resampling.LANCZOS))
            self.atlas_masks, self.atlas_key = masks, key
        co,si = math.cos(angle)/scale,math.sin(angle)/scale
        ax,ay = ANCHOR[0]*2,ANCHOR[1]*2
        matrix = (co,-si,2*cx-co*ax+si*ay,si,co,2*cy-si*ax-co*ay)
        return [mask.transform((640,600),Image.Transform.AFFINE,matrix,
                    resample=Image.Resampling.BICUBIC,fillcolor=0) for mask in self.atlas_masks]

    def render(self, center, radius, players, angle=0, trails=None, names=True):
        im=Image.new('RGBA',(640,600),(0,0,0,0))
        draw=ImageDraw.Draw(im)
        if not self.roads.ready or not self.paths:
            text='Map: calibration required' if not self.roads.ready else 'Map: road data missing'
            draw.text((320,300),text,font=self.font,anchor='mm',fill='white',stroke_width=2,stroke_fill='#16191F')
            return im.resize(SIZE,Image.Resampling.LANCZOS)
        cx,cy=self.roads.to_pixel(center)
        offset=self.matcher.match((cx,cy),self.roads.pixels_per_meter) if self.assist else (0,0)
        if not self.assist:self.matcher.reset()
        cx+=offset[0];cy+=offset[1]
        scale=126/(radius*self.roads.pixels_per_meter)
        co,si=math.cos(angle),math.sin(angle)
        shift=((co*offset[0]+si*offset[1])*scale,(-si*offset[0]+co*offset[1])*scale)
        # Subtle road shadows improve contrast without making a containing panel.
        outline,surface=self.road_layers(cx,cy,scale,angle)
        for mask,color,opacity in ((outline,(8,12,18),150),(surface,(244,247,250),255)):
            if opacity != 255: mask=mask.point(lambda v: round(v*opacity/255))
            layer=Image.new('RGBA',im.size,color+(0,))
            layer.putalpha(mask)
            im=Image.alpha_composite(im,layer)
        draw=ImageDraw.Draw(im)
        if trails:
            for player in players:
                points=trails.get(player['id'],[])
                coords=[tuple(2*v for v in self.project(p,center,radius,angle)) for p in points]
                if len(coords)>1: draw.line(coords,fill=player.get('color','#48BDFF'),width=3)
        im.putalpha(ImageChops.multiply(im.getchannel('A'),self.feather))
        draw=ImageDraw.Draw(im)
        # Players outside the visible area sit at its edge; keep names inside.
        for player in players:
            x,y=self.project(player['pos'],center,radius,angle)
            if player['id']!='self':x-=shift[0];y-=shift[1]
            distance=math.hypot((x-160)/142,(y-150)/126)
            if distance>1:
                x,y=160+(x-160)/distance,150+(y-150)/distance
            x,y=x*2,y*2
            heading=player.get('heading',angle)-angle
            dx,dy=math.sin(heading),-math.cos(heading)
            own=player['id']=='self'
            length,width=(21,13) if own else (16,10)
            # Center the visible arrow around the displayed vehicle coordinate.
            x+=dx*length*.775;y+=dy*length*.775
            poly=[(x,y),
                  (x-dx*length*1.55-dy*width,y-dy*length*1.55+dx*width),
                  (x-dx*length*1.2,y-dy*length*1.2),
                  (x-dx*length*1.55+dy*width,y-dy*length*1.55-dx*width)]
            draw.polygon(poly,fill='white' if own else player.get('color','#48BDFF'),outline='#171B20',width=3)
            if names and not own:
                label=player['name'][:20]
                draw.text((max(92,min(548,x)),min(549,y+29)),label,font=self.font,anchor='mm',
                          fill=player.get('color','#48BDFF'),stroke_width=2,stroke_fill='#11151A')
        nx,ny=320-math.sin(angle)*251,300-math.cos(angle)*251
        draw.text((nx,ny),'N',font=self.font,anchor='mm',fill=(255,255,255,220),stroke_width=2,stroke_fill='#15191F')
        return im.resize(SIZE,Image.Resampling.LANCZOS)


class Point(ctypes.Structure): _fields_=[('x',wt.LONG),('y',wt.LONG)]
class Size(ctypes.Structure): _fields_=[('cx',wt.LONG),('cy',wt.LONG)]
class Blend(ctypes.Structure): _fields_=[('op',wt.BYTE),('flags',wt.BYTE),('alpha',wt.BYTE),('format',wt.BYTE)]
class BitmapHeader(ctypes.Structure):
    _fields_=[('size',wt.DWORD),('width',wt.LONG),('height',wt.LONG),('planes',wt.WORD),
              ('bits',wt.WORD),('compression',wt.DWORD),('imageSize',wt.DWORD),
              ('xppm',wt.LONG),('yppm',wt.LONG),('used',wt.DWORD),('important',wt.DWORD)]
class BitmapInfo(ctypes.Structure): _fields_=[('header',BitmapHeader),('colors',wt.DWORD*3)]


class TransparentWindow:
    """Own API function objects so the existing HUD's ctypes signatures stay intact."""
    def __init__(self, size=SIZE):
        self.size = size
        self.hwnd=self.dc=self.bitmap=self.old=None
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.gdi=ctypes.WinDLL('gdi32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        H=ctypes.c_void_p; I=ctypes.c_int; U=ctypes.c_uint
        signatures=[(self.user,'CreateWindowExW',H,[U,ctypes.c_wchar_p,ctypes.c_wchar_p,U,I,I,I,I,H,H,H,H]),
          (self.kernel,'GetModuleHandleW',H,[ctypes.c_wchar_p]),
          (self.gdi,'CreateCompatibleDC',H,[H]),(self.gdi,'DeleteDC',I,[H]),
          (self.gdi,'CreateDIBSection',H,[H,ctypes.POINTER(BitmapInfo),U,ctypes.POINTER(H),H,U]),
          (self.gdi,'SelectObject',H,[H,H]),(self.gdi,'DeleteObject',I,[H]),
          (self.user,'UpdateLayeredWindow',I,[H,H,ctypes.POINTER(Point),ctypes.POINTER(Size),H,ctypes.POINTER(Point),U,ctypes.POINTER(Blend),U]),
          (self.user,'SetWindowPos',I,[H,H,I,I,I,I,U]),(self.user,'ShowWindow',I,[H,I]),
          (self.user,'DestroyWindow',I,[H])]
        for dll,name,restype,argtypes in signatures:
            function=getattr(dll,name); function.restype=restype; function.argtypes=argtypes
        try:
            self.hwnd=self.user.CreateWindowExW(0x080800A8,'STATIC','G29 transparent minimap',0x80000000,
                0,0,*self.size,None,None,self.kernel.GetModuleHandleW(None),None)
            if not self.hwnd: raise ctypes.WinError(ctypes.get_last_error())
            self.dc=self.gdi.CreateCompatibleDC(None)
            if not self.dc: raise ctypes.WinError(ctypes.get_last_error())
            info=BitmapInfo(); info.header=BitmapHeader(ctypes.sizeof(BitmapHeader),self.size[0],-self.size[1],1,32,0,0,0,0,0,0)
            self.bits=H()
            self.bitmap=self.gdi.CreateDIBSection(self.dc,ctypes.byref(info),0,ctypes.byref(self.bits),None,0)
            if not self.bitmap or not self.bits: raise ctypes.WinError(ctypes.get_last_error())
            self.old=self.gdi.SelectObject(self.dc,self.bitmap)
            if not self.old or self.old == ctypes.c_void_p(-1).value:
                self.old = None
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            self.close(); raise

    def show(self, image, x, y):
        if image.size!=self.size or image.mode!='RGBA': raise ValueError('Unexpected overlay frame size or mode.')
        pixels=image.convert('RGBa').tobytes('raw','BGRa')
        ctypes.memmove(self.bits,pixels,len(pixels))
        if not self.user.UpdateLayeredWindow(self.hwnd,None,ctypes.byref(Point(x,y)),ctypes.byref(Size(*self.size)),
                  self.dc,ctypes.byref(Point(0,0)),0,ctypes.byref(Blend(0,0,255,1)),2):
            raise ctypes.WinError(ctypes.get_last_error())
        self.user.SetWindowPos(self.hwnd,ctypes.c_void_p(-1),0,0,0,0,0x53)

    def hide(self):
        if self.hwnd: self.user.ShowWindow(self.hwnd,0)

    def close(self):
        if self.dc and self.old: self.gdi.SelectObject(self.dc,self.old)
        if self.bitmap: self.gdi.DeleteObject(self.bitmap)
        if self.dc: self.gdi.DeleteDC(self.dc)
        if self.hwnd: self.user.DestroyWindow(self.hwnd)
        self.hwnd=self.dc=self.bitmap=self.old=None

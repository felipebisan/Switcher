"""Composited frosted glass with blurred backdrop and translucent surfaces."""
import os
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE=(880,690)

@lru_cache(maxsize=1)
def backdrop():
    im=Image.new('RGBA',SIZE);d=ImageDraw.Draw(im)
    for y in range(690):
        t=y/689
        d.line((0,y,880,y),fill=tuple(round(a+(b-a)*t) for a,b in zip((40,110,153),(5,13,32)))+(255,))
    light=Image.new('RGBA',SIZE);ld=ImageDraw.Draw(light)
    ld.ellipse((510,-160,990,320),fill=(73,180,255,180))
    ld.ellipse((-180,270,340,780),fill=(25,103,242,155))
    ld.ellipse((580,340,1050,840),fill=(77,60,164,145))
    im=Image.alpha_composite(im,light.filter(ImageFilter.GaussianBlur(55)))
    orb=Image.new('RGBA',SIZE);od=ImageDraw.Draw(orb)
    od.ellipse((605,142,820,357),fill=(55,163,239,190))
    od.ellipse((100,390,345,635),fill=(59,110,226,160))
    return Image.alpha_composite(im,orb.filter(ImageFilter.GaussianBlur(5)))

@lru_cache(maxsize=32)
def panel_layer(box):
    patch=backdrop().filter(ImageFilter.GaussianBlur(22)).crop(box)
    tint=Image.new('RGBA',patch.size);d=ImageDraw.Draw(tint)
    for row in range(patch.height):
        d.line((0,row,patch.width,row),fill=(195,225,255,round(39-23*row/max(1,patch.height-1))))
    patch=Image.alpha_composite(patch,tint)
    patch=Image.alpha_composite(patch,Image.new('RGBA',patch.size,(5,20,43,55)))
    mask=Image.new('L',patch.size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,patch.width-1,patch.height-1),radius=23,fill=255)
    patch.putalpha(mask);d=ImageDraw.Draw(patch)
    d.rounded_rectangle((0,0,patch.width-1,patch.height-1),radius=23,outline=(188,222,255,100),width=1)
    d.line((23,1,patch.width-23,1),fill=(221,243,255,155))
    return patch

class GlassPainter:
    def __init__(self):
        self.image=backdrop().copy();self.draw=ImageDraw.Draw(self.image)

    @staticmethod
    @lru_cache(maxsize=48)
    def font(size,bold=False):
        path=os.path.join(os.environ.get('WINDIR','C:/Windows'),'Fonts','segoeuib.ttf' if bold else 'segoeui.ttf')
        try:return ImageFont.truetype(path,size)
        except OSError:return ImageFont.load_default(size=size)

    def text(self,xy,text,size=13,color='#EAF6FF',bold=False,anchor=None):
        self.draw.text(xy,text,font=self.font(size,bold),fill=color,anchor=anchor)

    def panel(self,box):
        shadow=Image.new('RGBA',SIZE)
        ImageDraw.Draw(shadow).rounded_rectangle((box[0],box[1]+8,box[2],box[3]+8),radius=25,fill=(0,5,20,95))
        self.image=Image.alpha_composite(self.image,shadow.filter(ImageFilter.GaussianBlur(12)))
        self.image.alpha_composite(panel_layer(tuple(box)),(box[0],box[1]));self.draw=ImageDraw.Draw(self.image)

    def control(self,box,selected=False,focus=False,disabled=False):
        layer=Image.new('RGBA',SIZE);d=ImageDraw.Draw(layer)
        fill=(103,194,255,75) if selected else (193,225,255,19)
        if disabled:fill=(12,28,55,24)
        d.rounded_rectangle(box,radius=11,fill=fill,outline=(187,224,255,170 if focus else 70),width=2 if focus else 1)
        self.image=Image.alpha_composite(self.image,layer);self.draw=ImageDraw.Draw(self.image)

    def toggle(self,x,y,on,disabled=False):
        color=(90,192,255,255) if on else (51,80,107,255)
        if disabled:color=(75,105,126,160)
        self.draw.rounded_rectangle((x,y,x+38,y+21),radius=11,fill=color)
        cx=x+27 if on else x+11
        self.draw.ellipse((cx-7,y+4,cx+7,y+18),fill='#F1FAFF' if not disabled else '#9BACBF')

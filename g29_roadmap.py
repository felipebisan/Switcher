"""Screenshot-backed road map, affine calibration and calibration UI.

Source captures stay intact. Rendering and UI masks are applied in memory.
"""
import json
import math
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageTk

MASKS = {
    'Topo.png': [(398, 872, 433, 902)],
    'Topo Direita.png': [(909, 6, 1000, 47), (1452, 30, 1690, 238),
                         (546, 358, 601, 425), (1160, 369, 1248, 452), (1106, 416, 1142, 449)],
    'Meio Direita.png': [(915, 0, 1006, 44), (706, 87, 734, 115)],
    'Meio Esquerda.png': [(895, 501, 984, 587), (1207, 0, 1244, 29)],
    'Baixo Direita.png': [(918, 0, 1003, 44), (1466, 104, 1480, 235),
                          (0, 980, 1480, 1004), (1443, 476, 1480, 568),
                          (842, 88, 882, 123), (1373, 392, 1409, 425)],
    'Baixo Esquerda.png': [(1050, 0, 1349, 169), (0, 918, 1349, 925),
                           (784, 24, 820, 63), (524, 510, 553, 541)],
}


def fit_calibration(points):
    """Fit a 2D affine transform without adding a numerical dependency."""
    if not 3 <= len(points) <= 20:
        raise ValueError('Mark at least 3 separated locations (4 recommended).')
    for p in points:
        if len(p) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p):
            raise ValueError('Invalid calibration point.')
    means = [sum(p[k] for p in points)/len(points) for k in range(4)]
    centered = [[p[k]-means[k] for k in range(4)] for p in points]
    xx = sum(p[0]**2 for p in centered)
    zz = sum(p[1]**2 for p in centered)
    xz = sum(p[0]*p[1] for p in centered)
    det = xx*zz-xz*xz
    if xx+zz < 10000 or det <= .004*(xx+zz)**2:
        raise ValueError('Choose locations farther apart, forming a wide triangle, not a straight line.')
    rows = []
    for axis in (2, 3):
        xu = sum(p[0]*p[axis] for p in centered)
        zu = sum(p[1]*p[axis] for p in centered)
        a, b = (xu*zz-zu*xz)/det, (zu*xx-xu*xz)/det
        rows.append([a, b, means[axis]-a*means[0]-b*means[1]])
    a,b,_ = rows[0]; c,d,_ = rows[1]
    trace = a*a+b*b+c*c+d*d
    disc = math.sqrt(max(0, trace*trace-4*(a*d-b*c)**2))
    low, high = (trace-disc)/2, (trace+disc)/2
    if low <= 0 or math.sqrt(high/low) > 1.2 or not .005 < math.sqrt(high) < 20:
        raise ValueError('The marked locations distort the map. Check the points and try again.')
    residual = math.sqrt(sum((sum(rows[k][i]*p[i] for i in (0,1))+rows[k][2]-p[k+2])**2
                             for p in points for k in (0,1))/len(points))
    if residual > 10:
        raise ValueError(f'Points disagree by {residual:.1f} pixels. Check their locations.')
    return rows, residual


class RoadMap:
    def __init__(self, assets, calibration_path):
        self.assets = Path(assets)
        self.calibration_path = Path(calibration_path)
        self.rows = None
        self.points = []
        self.error = ''
        self.image = self.dark = self.coverage = None
        self.cached_key = self.cached_view = None
        self.draft_points = None
        self.calibration_window = None
        try:
            manifest = json.loads((self.assets/'manifest.json').read_text(encoding='utf-8'))
            tiles = []
            for tile in manifest['tiles']:
                with Image.open(self.assets/tile['file']) as source:
                    im = source.convert('RGB')
                tiles.append((tile, im))
            width = max(t['x']+im.width for t, im in tiles)
            height = max(t['y']+im.height for t, im in tiles)
            self.image = Image.new('RGB', (width, height), '#080A0D')
            self.coverage = Image.new('L', (width, height), 0)
            for tile, im in tiles:
                mask = Image.new('L', im.size, 255)
                draw = ImageDraw.Draw(mask)
                for box in MASKS.get(tile['file'], []): draw.rectangle(box, fill=0)
                # Ignore the bright cyan navigation overlay; use overlapping captures beneath it.
                r,g,b = im.split()
                cyan = ImageChops.multiply(
                    ImageChops.subtract(g,r).point(lambda v: 255 if v > 65 else 0),
                    ImageChops.subtract(b,r).point(lambda v: 255 if v > 65 else 0))
                cyan = cyan.filter(ImageFilter.MaxFilter(5))
                mask = ImageChops.subtract(mask, cyan)
                xy = (tile['x'], tile['y'])
                self.image.paste(im, xy, mask)
                self.coverage.paste(255, (xy[0],xy[1],xy[0]+im.width,xy[1]+im.height), mask)
            # A neutral, subdued map preserves roads and geographic detail from the captures.
            gray = ImageOps.grayscale(self.image).point(lambda v: int(8+147*(v/255)**1.7))
            self.dark = ImageOps.colorize(gray, '#05080C', '#D5DFEB')
            self.automatic_rows = None
            preset = self.assets/'automatic_calibration.json'
            if preset.exists():
                data = json.loads(preset.read_text(encoding='utf-8'))
                if data.get('atlas_size') == list(self.image.size):
                    self.automatic_rows, _ = fit_calibration(data['points'])
                    self.rows = self.automatic_rows
            if self.calibration_path.exists():
                data = json.loads(self.calibration_path.read_text(encoding='utf-8'))
                if data.get('atlas_size') == list(self.image.size):
                    rows, _ = fit_calibration(data['points'])
                    self.points, self.rows = data['points'], rows
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = str(exc)

    @property
    def ready(self):
        return self.rows is not None and self.image is not None

    def to_pixel(self, p):
        offset = getattr(self, 'alignment_offset', (0,0))
        return tuple(row[0]*p[0]+row[1]*p[1]+row[2]+offset[i] for i,row in enumerate(self.rows))

    @property
    def pixels_per_meter(self):
        a,b,_ = self.rows[0]; c,d,_ = self.rows[1]
        return math.sqrt(abs(a*d-b*c))

    def save(self, points):
        rows, error = fit_calibration(points)
        data = {'version': 1, 'atlas_size': list(self.image.size), 'points': points}
        temporary = self.calibration_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
        os.replace(temporary, self.calibration_path)
        self.points, self.rows = list(points), rows
        self.cached_key = None
        return error

    def render(self, center, radius, style='dark'):
        """Render the same calibrated viewport used by the overlay's player markers."""
        source = self.dark if style == 'dark' else self.image
        if source is None: return None
        if self.ready and center is not None:
            cx, cy = self.to_pixel(center)
            scale = 110/(radius*self.pixels_per_meter)
        else:
            cx, cy = source.width/2, source.height/2
            scale = min(320/source.width, 228/source.height)
        key = (round(cx, 1), round(cy, 1), round(scale, 5), style)
        if key != self.cached_key:
            self.cached_view = source.transform((320,228), Image.Transform.AFFINE,
                (1/scale,0,cx-160/scale,0,1/scale,cy-114/scale),
                resample=Image.Resampling.BILINEAR, fillcolor='#080A0D')
            self.cached_key = key
        return self.cached_view

    def project(self, p, center, radius):
        px,py = self.to_pixel(p); cx,cy = self.to_pixel(center)
        scale = 110/(radius*self.pixels_per_meter)
        return 160+(px-cx)*scale, 150+(py-cy)*scale

    def calibrate(self, root, get_position):
        if self.image is None:
            messagebox.showerror('Road map', 'Map images are missing. Keep map_assets next to the application.', parent=root)
            return
        if self.calibration_window and self.calibration_window.window.winfo_exists():
            self.calibration_window.window.lift()
            return
        self.calibration_window = CalibrationWindow(root, self, get_position)


class CalibrationWindow:
    def __init__(self, root, road, get_position):
        self.road, self.get_position = road, get_position
        self.points = [list(p) for p in (road.draft_points if road.draft_points is not None else road.points)]
        self.captured = None
        self.window = tk.Toplevel(root)
        self.window.title('Calibrate road map')
        self.window.attributes('-topmost', True)
        width = min(1000, root.winfo_screenwidth()-80)
        height = min(850, root.winfo_screenheight()-100)
        self.width, self.height = width, max(260, height-155)
        tk.Label(self.window, text='1. Stop at a recognizable intersection in the game.  2. Capture position.  3. Click that location here.\n'
                 'Repeat at 3 or more widely separated places. Scroll to zoom; right-drag to pan. Close this window to continue driving.',
                 justify='left', wraplength=width-20).pack(padx=10,pady=8)
        self.canvas = tk.Canvas(self.window, width=self.width, height=self.height, bg='#080A0D', highlightthickness=0)
        self.canvas.pack()
        self.scale = min(self.width/road.image.width, self.height/road.image.height)
        self.base_scale = self.scale
        self.cx, self.cy = road.image.width/2, road.image.height/2
        self.status = tk.StringVar(value='Capture a position, then click the matching location on the map.')
        tk.Label(self.window, textvariable=self.status, wraplength=width-20).pack(pady=5)
        bar = tk.Frame(self.window); bar.pack(pady=(0,10))
        for label, action in [('Capture position', self.capture), ('Undo point', self.undo),
                              ('Clear points', self.clear), ('Save calibration', self.save)]:
            tk.Button(bar, text=label, command=action).pack(side='left', padx=5)
        self.canvas.bind('<Button-1>', self.click)
        self.canvas.bind('<MouseWheel>', self.zoom)
        self.canvas.bind('<ButtonPress-3>', self.pan_start)
        self.canvas.bind('<B3-Motion>', self.pan)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.redraw()

    def map_at(self, x,y):
        return self.cx+(x-self.width/2)/self.scale, self.cy+(y-self.height/2)/self.scale

    def redraw(self):
        picture = self.road.image.transform((self.width,self.height), Image.Transform.AFFINE,
            (1/self.scale,0,self.cx-self.width/2/self.scale,0,1/self.scale,self.cy-self.height/2/self.scale),
            Image.Resampling.BILINEAR, fillcolor='#080A0D')
        self.photo = ImageTk.PhotoImage(picture, master=self.window)
        self.canvas.delete('all')
        self.canvas.create_image(0,0,image=self.photo,anchor='nw')
        for i,p in enumerate(self.points):
            x,y = (p[2]-self.cx)*self.scale+self.width/2, (p[3]-self.cy)*self.scale+self.height/2
            self.canvas.create_oval(x-6,y-6,x+6,y+6,fill='#4DA3FF',outline='white')
            self.canvas.create_text(x+12,y-12,text=str(i+1),fill='white',font=('Segoe UI',12,'bold'))

    def capture(self):
        position, age = self.get_position()
        if position is None or age > 120:
            self.status.set('No recent position. Drive in the game, stop, then capture again.'); return
        self.captured = list(position)
        self.status.set(f'Position captured ({age:.0f}s ago). Click its exact location on the image.')

    def click(self, event):
        if self.captured is None:
            self.status.set('Click Capture position first.'); return
        if len(self.points) >= 20:
            self.status.set('Maximum 20 points. Undo a point or save calibration.'); return
        u,v = self.map_at(event.x,event.y)
        if not (0<=u<self.road.image.width and 0<=v<self.road.image.height) or self.road.coverage.getpixel((int(u),int(v))) < 128:
            self.status.set('Choose a location covered by the screenshots.'); return
        if any(math.dist(self.captured, p[:2]) < 100 for p in self.points):
            self.status.set('This position is too close to an existing point. Drive farther away.'); return
        self.points.append([*self.captured,u,v]); self.captured = None
        self.road.draft_points = [list(p) for p in self.points]
        self.status.set(f'{len(self.points)} points. Drive to another location, or save with at least 3 points.')
        self.redraw()

    def undo(self):
        if self.points: self.points.pop()
        self.captured = None
        self.road.draft_points = [list(p) for p in self.points]
        self.redraw()

    def clear(self):
        self.points.clear(); self.captured = None
        self.road.draft_points = []
        self.redraw()

    def zoom(self, event):
        old = self.map_at(event.x,event.y)
        self.scale = max(self.base_scale, min(4, self.scale*(1.25 if event.delta>0 else .8)))
        new = self.map_at(event.x,event.y)
        self.cx += old[0]-new[0]; self.cy += old[1]-new[1]
        self.redraw()

    def pan_start(self, event):
        self.drag = (event.x,event.y,self.cx,self.cy)

    def pan(self, event):
        x,y,cx,cy = self.drag
        self.cx, self.cy = cx-(event.x-x)/self.scale, cy-(event.y-y)/self.scale
        self.redraw()

    def save(self):
        try:
            error = self.road.save(self.points)
        except (ValueError,OSError) as exc:
            self.status.set(str(exc)); return
        self.status.set(f'Calibration saved. Fit error: {error:.1f}px. Verify at a fourth location in the game.')

    def close(self):
        self.road.draft_points = [list(p) for p in self.points]
        self.window.destroy()

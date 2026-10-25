"""One-landmark translation correction using the actual vector road layer."""
import math
import tkinter as tk


def corrected_offset(previous, predicted, target, pixels_per_meter):
    delta = [target[i]-predicted[i] for i in (0,1)]
    if not all(math.isfinite(v) for v in delta) or math.hypot(*delta)/pixels_per_meter > 100:
        raise ValueError('Choose a reference within 100 m of the marker. Use full calibration for larger errors.')
    return [previous[i]+delta[i] for i in (0,1)]


class FineAlignment:
    def __init__(self, overlay):
        self.overlay = overlay
        self.position=self.predicted=self.target=None
        self.window = tk.Toplevel(overlay.root)
        self.window.title('Fine-tune road alignment')
        self.window.attributes('-topmost', True)
        self.window.resizable(False, False)
        tk.Label(self.window,text='Stop at the center of a recognizable intersection, then Capture position.\n'
                 'Click that same intersection on the roads below and Apply. North is up.\n'
                 'This adjusts the whole map; it does not force your car onto a road.',justify='left').pack(padx=12,pady=10)
        self.canvas=tk.Canvas(self.window,width=600,height=460,bg='#20252B',highlightthickness=0)
        self.canvas.pack()
        self.status=tk.StringVar(value='Capture your stopped position to begin.')
        tk.Label(self.window,textvariable=self.status,wraplength=580).pack(pady=6)
        self.scale=tk.DoubleVar(value=6)
        tk.Scale(self.window,from_=2,to=16,resolution=1,orient='horizontal',label='Zoom',
                 variable=self.scale,command=lambda value:self.draw()).pack(fill='x',padx=12)
        bar=tk.Frame(self.window);bar.pack(pady=10)
        for label,command in [('Capture position',self.capture),('Apply',self.apply),('Reset adjustment',self.reset)]:
            tk.Button(bar,text=label,command=command).pack(side='left',padx=5)
        self.canvas.bind('<Button-1>',self.select)
        self.capture()

    def capture(self):
        position,age=self.overlay.calibration_position()
        if position is None or age>120 or not self.overlay.roads.ready:
            self.position=self.predicted=self.target=None
            self.status.set('Map overview. Return to driving to receive telemetry, stop at an intersection, then Capture position.')
            self.draw()
            return
        self.position=list(position)
        self.predicted=self.overlay.roads.to_pixel(position)
        self.target=None
        self.status.set(f'Captured {age:.0f}s ago. Blue cross = reported position. Click your actual intersection.')
        self.draw()

    def draw(self):
        self.canvas.delete('all')
        paths=self.overlay.minimap.paths
        if not paths:
            self.canvas.create_text(300,230,text='Road data is missing. Check map_assets/roads.json.',fill='white')
            return
        if self.predicted is None:
            x0=min(box[0] for _,box in paths);y0=min(box[1] for _,box in paths)
            x1=max(box[2] for _,box in paths);y1=max(box[3] for _,box in paths)
            cx,cy=(x0+x1)/2,(y0+y1)/2
            s=min(560/max(1,x1-x0),420/max(1,y1-y0))
        else:
            cx,cy=self.predicted;s=self.scale.get()
        for path,(x0,y0,x1,y1) in self.overlay.minimap.paths:
            if x1<cx-300/s or x0>cx+300/s or y1<cy-230/s or y0>cy+230/s:continue
            coords=[v for x,y in path for v in ((x-cx)*s+300,(y-cy)*s+230)]
            self.canvas.create_line(*coords,fill='#F4F7FA',width=2)
        if self.predicted is not None:
            self.canvas.create_line(288,230,312,230,fill='#49BFFF',width=2)
            self.canvas.create_line(300,218,300,242,fill='#49BFFF',width=2)
        self.canvas.create_text(20,20,text='N ↑',fill='white')
        if self.target:
            x,y=(self.target[0]-cx)*s+300,(self.target[1]-cy)*s+230
            self.canvas.create_oval(x-5,y-5,x+5,y+5,outline='#FFBD59',width=2)

    def select(self,event):
        if self.predicted is None:
            self.status.set('Capture a recent car position before choosing its matching intersection.');return
        self.target=[self.predicted[0]+(event.x-300)/self.scale.get(),self.predicted[1]+(event.y-230)/self.scale.get()]
        self.status.set('Orange marker = actual location. Apply saves the translation for every zoom level.')
        self.draw()

    def apply(self):
        if self.target is None:return
        try:
            offset=corrected_offset(self.overlay.settings['alignment_offset'],self.predicted,self.target,
                                    self.overlay.roads.pixels_per_meter)
        except ValueError as exc:self.status.set(str(exc));return
        self.overlay.change('alignment_offset',offset)
        self.window.destroy()

    def reset(self):
        self.overlay.change('alignment_offset',[0,0])
        self.capture()

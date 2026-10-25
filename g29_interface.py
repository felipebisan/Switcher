"""Canvas-based glass UI; all settings retain the existing application callbacks."""
import time
import tkinter as tk
from PIL import Image, ImageTk
from g29_map import POSITIONS
from g29_glass_scene import GlassPainter, SIZE

class SettingsInterface:
    def __init__(self,root,overlay,rounded,actions,state):
        self.root,self.overlay,self.rounded,self.actions,self.state=root,overlay,rounded,actions,state
        self.window=None;self.page='Configuration';self.section='Instruments'
        self.controls=[];self.focus=-1;self.signature=None;self.poll_job=None
        self.nav=('Configuration','Telemetry','About')

    def show(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify();self.window.lift();return
        w=self.window=tk.Toplevel(self.root)
        w.title('SWITCHER');w.geometry('880x690');w.minsize(760,600);w.configure(bg='#080F1B')
        self.canvas=tk.Canvas(w,highlightthickness=0,bg='#080F1B',takefocus=True)
        self.canvas.pack(fill='both',expand=True);self.image_item=self.canvas.create_image(0,0,anchor='nw')
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<Button-1>',self.click)
        self.canvas.bind('<Motion>',self.hover)
        self.canvas.bind('<Tab>',lambda e:self.tab(1))
        self.canvas.bind('<Shift-Tab>',lambda e:self.tab(-1))
        self.canvas.bind('<Return>',lambda e:self.activate())
        self.canvas.bind('<space>',lambda e:self.activate())
        w.protocol('WM_DELETE_WINDOW',self.hide);w.bind('<Escape>',lambda e:self.hide())
        self.rounded(w);self.canvas.focus_set();self.poll()

    def hide(self):
        if self.window is not None:self.window.withdraw()

    def select(self,page):
        self.page=page;self.focus=-1;self.signature=None;self.draw()

    def choose_section(self,section):
        self.section=section;self.select('Telemetry')

    def add(self,box,label,action,disabled=False,options=None):
        index=len(self.controls)
        self.controls.append(dict(box=box,label=label,action=action,disabled=disabled,options=options))
        return index==self.focus

    def action(self,p,box,label,fn,selected=False,disabled=False):
        focused=self.add(box,label,fn,disabled)
        p.control(box,selected,focused,disabled)
        p.text(((box[0]+box[2])/2,(box[1]+box[3])/2),label,13,'#91A6BE' if disabled else '#F0F8FF',anchor='mm')

    def toggle(self,p,x,y,w,label,key=None,getter=None,fn=None,disabled=False):
        getter=getter or (lambda:self.overlay.settings[key])
        fn=fn or (lambda:self.overlay.change(key,not getter()))
        box=(x,y,x+w,y+40);focus=self.add(box,label,fn,disabled)
        if focus:p.control(box,focus=True)
        p.text((x+8,y+10),label,14,'#91A6BE' if disabled else '#EFF8FF')
        p.toggle(x+w-48,y+10,bool(getter()),disabled)

    def choice(self,p,x,y,w,label,key,options,getter=None,fn=None,disabled=False):
        getter=getter or (lambda:self.overlay.settings[key])
        fn=fn or (lambda value:self.overlay.change(key,value))
        p.text((x+8,y+6),label,12,'#A8BED4')
        box=(x,y+27,x+w,y+64);focused=self.add(box,label,fn,disabled,options)
        p.control(box,focus=focused,disabled=disabled)
        p.text((x+14,y+45),dict(options).get(getter(),str(getter())),13,'#8CA3BB' if disabled else '#F4FAFF',anchor='lm')
        p.draw.line([(x+w-25,y+42),(x+w-20,y+47),(x+w-15,y+42)],fill='#B7DFFF',width=2)

    def card(self,p,box,title,subtitle):
        p.panel(box);p.text((box[0]+24,box[1]+22),title,21,bold=True)
        p.text((box[0]+24,box[1]+56),subtitle,12,'#BBD4E8')

    def render(self):
        self.controls=[];p=GlassPainter();s=self.overlay.settings;state=self.state()
        p.text((34,25),'SWITCHER',29,bold=True)
        p.text((36,64),'DRIVING CONTROL  /  LIVE TELEMETRY',10,'#B6DBF3')
        with self.overlay.lock:live=self.overlay.latest is not None and time.monotonic()-self.overlay.received<1.2
        p.text((846,34),f"G29  •  {'Connected' if state['connected'] else 'Disconnected'}",12,anchor='ra')
        p.text((846,59),'Telemetry live' if live else 'Waiting for game',11,'#B6DBF3',anchor='ra')
        for i,page in enumerate(self.nav):
            self.action(p,(34+i*274,100,298+i*274,143),page,lambda page=page:self.select(page),self.page==page)
        if self.page=='Configuration':
            self.card(p,(34,168,434,590),'Mode switching','Your wheel, your driving style.')
            self.toggle(p,50,266,368,'Enable mode switching','switcher_enabled')
            self.toggle(p,50,322,368,'Show mode indicator','show_mode_indicator')
            self.toggle(p,50,378,368,'Enable Shift Light','shift_lights')
            p.text((58,476),'When disabled, the wheel keeps',13,'#BBD4E8')
            p.text((58,496),'its last rotation setting.',13,'#BBD4E8')
            self.card(p,(454,168,846,590),'Wheel configuration','Fine-tune your controls.')
            for y,label,key in [(270,f"RACE rotation  •  {state['race']}°",'rotation_race'),(336,f"DRIFT rotation  •  {state['drift']}°",'rotation_drift'),(402,'Activation button','button')]:
                self.action(p,(478,y,822,y+46),label,self.actions[key])
            p.text((478,502),'Your activation button is saved automatically.',12,'#BBD4E8')
        elif self.page=='Telemetry':
            self.action(p,(34,622,230,648),'Friends room…',self.overlay.friends_dialog)
            for i,name in enumerate(('Instruments','Compact','Map')):
                self.action(p,(34+i*274,159,298+i*274,196),name,lambda n=name:self.choose_section(n),self.section==name)
            disabled=s['instruments_enabled']
            sizes=[(v,f'{v}%') for v in (50,75,100)]
            if self.section=='Instruments':
                self.card(p,(34,214,484,615),'Instruments','Live RPM, speed and gear.')
                self.toggle(p,50,288,418,'Enable instruments',getter=lambda:s['instruments_enabled'],fn=lambda:self.overlay.set_instrument_mode('off' if s['instruments_enabled'] else s['instrument_layout']))
                self.choice(p,58,335,402,'Display',None,[('with_map','Panel with map'),('panel','Panel only'),('shift_light','Panel with shift light')],getter=lambda:s['instrument_layout'],fn=self.overlay.set_instrument_layout)
                self.choice(p,58,410,246,'HUD position','instruments_position',POSITIONS)
                self.choice(p,320,410,140,'Size','panel_scale',sizes)
                self.toggle(p,50,500,418,'Dark dial backgrounds','dark_dials')
                if s['instrument_layout']=='with_map':
                    self.card(p,(504,214,846,615),'Integrated map','The road ahead, in your panel.')
                    self.map_options(p,528,302,294)
                else:
                    shift=s['instrument_layout']=='shift_light'
                    self.card(p,(504,214,846,615),'Shift light' if shift else 'Open center','Your instruments stay in place.')
                    for y,text in ((326,'Light green: building RPM' if shift else 'The map is hidden.'),(362,'Orange: from 70% RPM' if shift else 'Dial positions remain unchanged.'),(398,'Flashing red: above 83%' if shift else 'The center stays transparent.')):
                        p.text((528,y),text,12,'#C4DEEF')
                    if shift:p.text((528,466),'Based on the engine RPM limit.',12,'#C4DEEF')
            elif self.section=='Compact':
                self.card(p,(34,214,520,615),'Compact','A minimal readout for your drive.')
                self.toggle(p,50,294,454,'Enable compact HUD',getter=lambda:state['compact'],fn=self.actions['compact'],disabled=disabled)
                self.choice(p,58,351,438,'HUD position',None,POSITIONS,getter=lambda:state['compact_position'],fn=self.actions['compact_position'],disabled=disabled)
                self.choice(p,58,434,438,'Size','compact_scale',sizes,disabled=disabled)
                self.exclusive_note(p,disabled)
            else:
                self.card(p,(34,214,520,615),'Map','A clear view of every turn.')
                self.toggle(p,50,287,454,'Enable map',getter=lambda:s['standalone_map_enabled'],fn=lambda:self.overlay.set_standalone_map(not s['standalone_map_enabled']),disabled=disabled)
                self.choice(p,58,334,270,'HUD position','map_position',POSITIONS,disabled=disabled)
                self.choice(p,344,334,152,'Size','map_scale',sizes,disabled=disabled)
                self.map_options(p,58,412,438,disabled)
                self.exclusive_note(p,disabled)
        else:
            self.card(p,(34,168,846,590),'Made for the drive.','SWITCHER  /  LOGITECH G29')
            p.text((66,320),'Developed by Amzng',25,bold=True)
            p.text((66,374),'Wheel control, live instruments and a clearer road ahead.',16,'#C4DEEF')
        p.text((440,652),'Saved automatically  •  Close to tray  •  Minimize to taskbar',11,'#B2C9E0',anchor='mm')
        return p.image

    def exclusive_note(self,p,disabled):
        self.card(p,(540,214,846,615),'Your layout','Independent when you need it.')
        for y,text in [(325,'Instruments is active.' if disabled else 'Ready to customize.'),(361,'Turn it off to use this HUD.' if disabled else 'Choose a position and size.'),(397,'Your preferences stay saved.')]:
            p.text((562,y),text,12,'#C4DEEF')

    def map_options(self,p,x,y,w,disabled=False):
        self.choice(p,x,y,w,'View radius','zoom',[(v,f'{v} m') for v in (250,500,1000,2000)],disabled=disabled)
        self.toggle(p,x,y+76,w,'Rotate with car','rotate',disabled=disabled)
        self.toggle(p,x,y+115,w,'Road alignment assist',getter=lambda:self.overlay.settings.get('road_assist',True),fn=lambda:self.overlay.change('road_assist',not self.overlay.settings.get('road_assist',True)),disabled=disabled)
        self.action(p,(x,y+158,x+w,y+193),'Map alignment…',self.alignment_options,disabled=disabled)

    def draw(self):
        if self.window is None:return
        image=self.render();self.frame=image
        w,h=max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
        self.photo=ImageTk.PhotoImage(image.resize((w,h),Image.Resampling.LANCZOS),master=self.canvas)
        self.canvas.itemconfigure(self.image_item,image=self.photo)

    def hit(self,event):
        x=event.x*880/max(1,self.canvas.winfo_width());y=event.y*690/max(1,self.canvas.winfo_height())
        return next((i for i,c in enumerate(self.controls) if c['box'][0]<=x<=c['box'][2] and c['box'][1]<=y<=c['box'][3] and not c['disabled']),-1)

    def hover(self,event):self.canvas.configure(cursor='hand2' if self.hit(event)>=0 else '')

    def click(self,event):
        self.canvas.focus_set();self.focus=self.hit(event);self.activate()

    def tab(self,direction):
        enabled=[i for i,c in enumerate(self.controls) if not c['disabled']]
        if enabled:
            index=enabled.index(self.focus) if self.focus in enabled else (-1 if direction>0 else 0)
            self.focus=enabled[(index+direction)%len(enabled)];self.draw()
        return 'break'

    def activate(self):
        if not 0<=self.focus<len(self.controls):return 'break'
        c=self.controls[self.focus]
        if c['disabled']:return 'break'
        if c['options']:
            if getattr(self,'popup',None) is not None:self.popup.destroy()
            menu=tk.Menu(self.window,tearoff=False,bg='#17334C',fg='#ECF6FF',activebackground='#32678C',activeforeground='white')
            for value,label in c['options']:
                menu.add_command(label=label,command=lambda v=value,fn=c['action']:self.commit(fn,v))
            x=self.canvas.winfo_rootx()+int(c['box'][0]*self.canvas.winfo_width()/880)
            y=self.canvas.winfo_rooty()+int(c['box'][3]*self.canvas.winfo_height()/690)
            self.popup=menu
            try:menu.tk_popup(x,y)
            finally:menu.grab_release()
        else:c['action']();self.draw()
        return 'break'

    def commit(self,fn,value):fn(value);self.draw()

    def alignment_options(self):
        window=tk.Toplevel(self.window);window.title('Map alignment');window.configure(bg='#17334C');window.transient(self.window)
        def fine():
            if not self.overlay.settings['auto_alignment']:self.overlay.change('auto_alignment',True)
            self.overlay.fine_align()
        for label,fn in [('Automatic alignment',lambda:self.overlay.change('auto_alignment',True)),('Fine-tune alignment…',fine),('Full manual calibration…',self.overlay.calibrate_manually),('Show / hide trail',lambda:self.overlay.change('show_trails',not self.overlay.settings['show_trails'])),('Save trail…',self.overlay.save_trail),('Clear trail',lambda:self.overlay.trails.clear())]:
            tk.Button(window,text=label,command=fn,bg='#234662',fg='white',relief='flat',padx=24,pady=10).pack(fill='x',padx=12,pady=5)

    def poll(self):
        if self.window is None or not self.window.winfo_exists():return
        state=self.state()
        with self.overlay.lock:live=self.overlay.latest is not None and time.monotonic()-self.overlay.received<1.2
        signature=(repr(self.overlay.settings),repr(state),live,self.page,self.section)
        if signature!=self.signature:
            self.signature=signature;self.draw()
        self.poll_job=self.window.after(250,self.poll)

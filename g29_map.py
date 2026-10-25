"""Route overlay and opt-in authenticated group telemetry (LAN/VPN)."""
import collections
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import math
import os
import queue
import secrets
import socket
import struct
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, filedialog
from PIL import ImageTk, Image
from g29_roadmap import RoadMap
from g29_minimap import MinimapRenderer, TransparentWindow
from g29_alignment import FineAlignment
from g29_friends import FriendsLink
from g29_dashboard import DashboardRenderer, read_instruments, panel_size as dashboard_size

POSITIONS = [('centro_inferior', 'Bottom center'), ('centro', 'Center'),
             ('centro_superior', 'Top center'), ('inferior_esquerda', 'Bottom left'),
             ('inferior_direita', 'Bottom right')]


def read_position(data):
    if len(data) != 324 or struct.unpack_from('<i', data)[0] != 1:
        return None
    x, y, z = struct.unpack_from('<fff', data, 244)
    if not all(math.isfinite(v) and abs(v) < 1e7 for v in (x, y, z)):
        return None
    return [x, z]


def encode(payload, key):
    body = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()
    return hmac.digest(key, body, 'sha256') + body


def decode(data, key):
    if not 32 < len(data) <= 16000:
        raise ValueError('Invalid packet size')
    if not hmac.compare_digest(data[:32], hmac.digest(key, data[32:], 'sha256')):
        raise ValueError('Invalid group code')
    payload = json.loads(data[32:])
    if (not isinstance(payload, dict) or not isinstance(payload.get('time'), (int, float))
            or not math.isfinite(payload['time']) or abs(time.time() - payload['time']) > 60):
        raise ValueError('Expired packet')
    return payload


def valid_player(p):
    return (isinstance(p, dict) and isinstance(p.get('id'), str) and len(p['id']) == 16
            and isinstance(p.get('name'), str) and 1 <= len(p['name']) <= 20
            and isinstance(p.get('seq'), int) and p['seq'] >= 0
            and (p.get('pos') is None or (isinstance(p['pos'], list) and len(p['pos']) == 2
                 and all(isinstance(v, (int, float)) and math.isfinite(v) and abs(v) < 1e7 for v in p['pos']))))


class GroupLink:
    """One private room per host. No sharing until explicitly connected."""
    def __init__(self, host, port, code, name, hosting=False):
        self.key = hashlib.sha256(code.encode()).digest()
        self.id = secrets.token_hex(8)
        self.name = name
        self.lock = threading.Lock()
        self.pos = None
        self.players = []
        self.last_reply = 0
        self.error = ''
        self.stop = threading.Event()
        self.server = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            address = socket.gethostbyname(host)
            self.address = (address, port)
            if hosting:
                self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.server.bind(('0.0.0.0', port))
                self.server.settimeout(.2)
            self.sock.bind(('0.0.0.0', 0))
            self.sock.settimeout(.1)
        except Exception:
            self.close()
            raise
        self.threads = []
        if self.server:
            self.threads.append(threading.Thread(target=self.serve, daemon=True))
        self.threads.append(threading.Thread(target=self.run, daemon=True))
        for thread in self.threads:
            thread.start()

    def serve(self):
        members = {}
        while not self.stop.is_set():
            try:
                raw, address = self.server.recvfrom(16001)
                p = decode(raw, self.key)
                if p.get('kind') != 'player' or not valid_player(p):
                    continue
                now = time.monotonic()
                members = {k: v for k, v in members.items() if now - v[1] < 3}
                old = members.get(p['id'])
                if old and p['seq'] <= old[0]['seq']:
                    continue
                if not old and len(members) >= 16:
                    continue
                members[p['id']] = (p, now)
                response = {'kind': 'group', 'time': time.time(), 'request': p['seq'],
                            'players': [v[0] for v in members.values()]}
                self.server.sendto(encode(response, self.key), address)
            except (ValueError, KeyError, TypeError, UnicodeError, socket.timeout):
                continue
            except OSError:
                break

    def run(self):
        seq = 0
        last_seq = 0
        while not self.stop.is_set():
            started = time.monotonic()
            with self.lock:
                pos = self.pos
            seq += 1
            try:
                self.sock.sendto(encode({'kind': 'player', 'time': time.time(), 'id': self.id,
                    'name': self.name, 'seq': seq, 'pos': pos}, self.key), self.address)
                raw, address = self.sock.recvfrom(16001)
                p = decode(raw, self.key)
                reply_seq = p.get('request', -1)
                if (address != self.address or p.get('kind') != 'group'
                        or not isinstance(reply_seq, int) or not last_seq < reply_seq <= seq):
                    continue
                players = p.get('players')
                if not isinstance(players, list) or len(players) > 16 or not all(valid_player(v) for v in players):
                    continue
                with self.lock:
                    last_seq = reply_seq
                    self.players = players
                    self.last_reply = time.monotonic()
                    self.error = ''
            except (ValueError, KeyError, TypeError, UnicodeError, socket.timeout):
                pass
            except OSError as exc:
                self.error = str(exc)
            self.stop.wait(max(0, .15 - (time.monotonic() - started)))

    def snapshot(self, pos):
        with self.lock:
            self.pos = pos
            fresh = time.monotonic() - self.last_reply < 3
            return list(self.players) if fresh else [], fresh

    def close(self):
        self.stop.set()
        for sock in (self.sock, self.server):
            if sock:
                sock.close()


class MapOverlay:
    def __init__(self, root, directory, rounded, refresh_menu):
        self.root = root
        self.path = os.path.join(directory, 'map_config.json')
        self.settings = {'enabled': True, 'position': 'inferior_esquerda', 'zoom': 1000, 'name': 'Driver',
                         'style': 'transparent', 'show_trails': False, 'rotate': True, 'names': True,
                         'layout_version': 2, 'auto_alignment': True, 'alignment_offset': [0,0],
                         'panel_scale': 100, 'panel_transparent': True, 'dark_dials': False}
        try:
            with open(self.path, encoding='utf-8') as f:
                saved = json.load(f)
            for k, value in saved.items():
                if k == 'panel_scale' and value in (50,75,100): self.settings[k]=value
                if k == 'panel_transparent' and isinstance(value,bool): self.settings[k]=value
                if k == 'dark_dials' and isinstance(value,bool): self.settings[k]=value
                if k == 'alignment_offset' and isinstance(value,list) and len(value)==2 and all(isinstance(v,(int,float)) and math.isfinite(v) and abs(v)<1000 for v in value): self.settings[k]=value
                if k == 'enabled' and isinstance(value, bool): self.settings[k] = value
                if k == 'position' and value in dict(POSITIONS): self.settings[k] = value
                if k == 'zoom' and value in (250, 500, 1000, 2000): self.settings[k] = value
                if k == 'name' and isinstance(value, str) and 0 < len(value) <= 20: self.settings[k] = value
                if k == 'style' and value in ('dashboard', 'transparent', 'dark', 'original'): self.settings[k] = value
                if k == 'show_trails' and isinstance(value, bool): self.settings[k] = value
                if k in ('rotate', 'names', 'auto_alignment') and isinstance(value, bool): self.settings[k] = value
            if saved.get('layout_version') != 2:
                self.settings['style'] = 'transparent'
                self.settings['zoom'] = max(1000, self.settings['zoom'])
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        # Migrate the old combined style to independently switchable components.
        prior=saved if 'saved' in locals() and isinstance(saved,dict) else {}
        self.settings['road_assist']=prior.get('road_assist',True) is True
        self.settings['map_enabled']=prior.get('map_enabled',self.settings['enabled']) is True
        self.settings['instruments_enabled']=prior.get('instruments_enabled',self.settings['enabled'] and self.settings['style']=='dashboard') is True
        self.settings['enabled']=self.settings['map_enabled'] or self.settings['instruments_enabled']
        self.settings['style']='dashboard' if self.settings['instruments_enabled'] else 'transparent'
        self.settings['panel_transparent']=True
        self.settings['names']=False
        self.settings['shift_lights']=prior.get('shift_lights',True) is True
        for key in ('map_scale','compact_scale'):
            value=prior.get(key,100)
            self.settings[key]=value if value in (50,75,100) else 100
        self.settings['hud_defaults_version']=prior.get('hud_defaults_version',0)
        for key in ('map_position','instruments_position'):
            value=prior.get(key,self.settings['position'])
            self.settings[key]=value if value in dict(POSITIONS) else self.settings['position']
        for key in ('switcher_enabled','show_mode_indicator'):
            self.settings[key]=prior.get(key,True) is True
        self.settings['standalone_map_enabled']=prior.get('standalone_map_enabled',self.settings['map_enabled']) is True
        layout=prior.get('instrument_layout','with_map' if self.settings['map_enabled'] else 'panel')
        self.settings['instrument_layout']=layout if layout in ('with_map','panel','shift_light') else 'with_map'
        # Apply the requested preset once; later user changes remain saved.
        self.preset_applied=self.settings['hud_defaults_version']<2
        if self.preset_applied:
            self.settings.update(enabled=True, instruments_enabled=True, map_enabled=True,
                                 standalone_map_enabled=True, style='dashboard', instrument_layout='with_map',
                                 instruments_position='centro_inferior', panel_scale=75, dark_dials=False,
                                 map_position='inferior_esquerda', map_scale=75, compact_scale=100,
                                 zoom=500, rotate=True, hud_defaults_version=2)
        self.refresh_menu = refresh_menu
        self.lock = threading.Lock()
        self.latest = None
        self.received = 0
        self.latest_yaw = None
        self.instruments = None
        self.last_position = None
        self.last_position_time = 0
        assets = os.path.join(directory, 'map_assets')
        if not os.path.isdir(assets):
            assets = os.path.join(getattr(sys, '_MEIPASS', directory), 'map_assets')
        self.roads = RoadMap(assets, os.path.join(directory, 'map_calibration.json'))
        self.manual_rows = self.roads.rows
        self.fine_dialog = None
        self.roads.alignment_offset = self.settings['alignment_offset'] if self.settings['auto_alignment'] else [0,0]
        if self.settings['auto_alignment'] and getattr(self.roads, 'automatic_rows', None):
            self.roads.rows = self.roads.automatic_rows
        self.minimap = MinimapRenderer(self.roads)
        self.transparent_window = None
        self.native_size = None
        self.dashboard = DashboardRenderer()
        self.map_executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix='g29-map')
        self.map_future = None
        self.map_frame = Image.new('RGBA',(320,300))
        self.heading = None
        self.map_photo = None
        self.map_image = None
        self.link = None
        self.group_info = None
        self.pending = queue.Queue()
        self.connecting = False
        self.closed = False
        self.dialog = None
        self.trails = {}
        self.center = None
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.configure(bg='#080A0D')
        self.window.attributes('-topmost', True)
        self.window.attributes('-toolwindow', True)
        self.window.attributes('-alpha', .94)
        rounded(self.window)
        self.canvas = tk.Canvas(self.window, width=320, height=300, bg='#080A0D', highlightthickness=0)
        self.canvas.pack()
        self.tick()

    def feed(self, data):
        try:
            pos = read_position(data)
        except (ValueError, struct.error):
            pos = None
        with self.lock:
            self.latest, self.received = pos, time.monotonic()
            self.instruments = read_instruments(data)
            yaw = struct.unpack_from('<f', data, 56)[0] if pos is not None else None
            self.latest_yaw = yaw if yaw is not None and math.isfinite(yaw) and abs(yaw) <= 4*math.pi else None
            if pos is not None:
                self.last_position, self.last_position_time = list(pos), self.received

    def calibration_position(self):
        with self.lock:
            return self.last_position, time.monotonic()-self.last_position_time

    def save(self):
        try:
            temporary = self.path + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
            os.replace(temporary, self.path)
        except OSError as exc:
            messagebox.showerror('Map settings', f'Unable to save settings: {exc}', parent=self.root)
        self.refresh_menu()

    def change(self, key, value):
        self.settings[key] = value
        if key == 'enabled':
            if not value:self.settings['map_enabled']=self.settings['instruments_enabled']=False
            elif not (self.settings['map_enabled'] or self.settings['instruments_enabled']):self.settings['map_enabled']=True
        if key in ('map_enabled','instruments_enabled'):
            self.settings['enabled']=self.settings['map_enabled'] or self.settings['instruments_enabled']
            self.settings['style']='dashboard' if self.settings['instruments_enabled'] else 'transparent'
        if key in ('alignment_offset', 'auto_alignment'):
            self.roads.alignment_offset = self.settings['alignment_offset'] if self.settings['auto_alignment'] else [0,0]
            self.roads.cached_key = None
        if key == 'auto_alignment':
            if value:
                self.manual_rows = self.roads.rows
                self.roads.rows = getattr(self.roads, 'automatic_rows', None) or self.roads.rows
            else:
                self.roads.rows = self.manual_rows
            self.roads.cached_key = None
        self.save()

    def instrument_mode(self):
        if not self.settings['instruments_enabled']:return 'off'
        return self.settings.get('instrument_layout','with_map' if self.settings['map_enabled'] else 'panel')

    def set_instrument_mode(self, mode):
        if mode not in ('off','panel','with_map','shift_light'):raise ValueError(mode)
        if mode!='off':self.settings['instrument_layout']=mode
        self.settings['instruments_enabled']=mode!='off'
        self.settings['map_enabled']=mode=='with_map' if mode!='off' else self.settings['standalone_map_enabled']
        self.settings['enabled']=self.settings['instruments_enabled'] or self.settings['map_enabled']
        self.settings['style']='dashboard' if mode!='off' else 'transparent'
        self.save()

    def set_instrument_layout(self, layout):
        if layout not in ('panel','with_map','shift_light'):raise ValueError(layout)
        self.settings['instrument_layout']=layout
        if self.settings['instruments_enabled']:self.set_instrument_mode(layout)
        else:self.save()

    def set_standalone_map(self, enabled):
        if self.settings['instruments_enabled']:return
        self.settings['standalone_map_enabled']=bool(enabled)
        self.change('map_enabled',bool(enabled))

    def calibrate_manually(self):
        if self.settings['auto_alignment']: self.change('auto_alignment', False)
        self.roads.calibrate(self.root, self.calibration_position)

    def fine_align(self):
        if self.fine_dialog and self.fine_dialog.window.winfo_exists():
            self.fine_dialog.window.lift(); return
        self.fine_dialog = FineAlignment(self)

    def menu(self, pystray, compact_menu=None):
        Item, Menu = pystray.MenuItem, pystray.Menu
        def action(fn):
            return lambda icon, item: self.root.after(0, fn)
        def toggle(label,key):
            return Item(label,action(lambda:self.change(key,not self.settings[key])),checked=lambda item:self.settings[key])
        def choice(label,key,value):
            return Item(label,action(lambda:self.change(key,value)),checked=lambda item:self.settings[key]==value,radio=True)
        items=[
            Item('Map',Menu(
                toggle('Show map','map_enabled'),
                Item('View radius',Menu(*(choice(f'{v} m','zoom',v) for v in (250,500,1000,2000)))),
                toggle('Rotate with car','rotate'),
                Item('Alignment',Menu(
                    toggle('Automatic alignment','auto_alignment'),
                    Item('Fine-tune alignment...',action(self.fine_align),enabled=lambda item:self.settings['auto_alignment']),
                    Item('Calibrate road map...',action(self.calibrate_manually)))),
                Item('Trail',Menu(toggle('Show trail','show_trails'),
                    Item('Save trail...',action(self.save_trail)),
                    Item('Clear trail',action(self.trails.clear))))
            )),
            Item('Instruments',Menu(
                toggle('Show instruments','instruments_enabled'),
                toggle('Dark dial backgrounds','dark_dials')
            )),
            Item('Layout',Menu(
                Item('Position',Menu(*(choice(label,'position',key) for key,label in POSITIONS))),
                Item('Instrument size',Menu(*(choice(f'{v}%','panel_scale',v) for v in (50,75,100))),
                     enabled=lambda item:self.settings['instruments_enabled'])
            ))
        ]
        if compact_menu is not None:items.append(Item('Compact HUD',compact_menu))
        return Item('Telemetry',Menu(*items))

    def show_group_details(self):
        if not self.group_info: return
        info = self.group_info
        address = info['host']
        if info['hosting']:
            address = 'Use this computer\'s LAN / VPN IPv4 address'
        messagebox.showinfo('Group details',
            f"Host: {address}\nPort: {info['port']} (UDP)\nCode: {info['code']}\n\n"
            'Friends must use the same game session / world.\nLeave group stops position sharing.', parent=self.root)

    def save_trail(self):
        trail = list(self.trails.get('self', []))
        if not trail:
            messagebox.showinfo('Save trail', 'Drive in the game to record a trail first.', parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='Save trail',
                    defaultextension='.json', initialfile='g29-route.json', filetypes=[('Route JSON', '*.json')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump({'format': 'g29-route-v1', 'coordinates': 'Forza X/Z meters',
                               'points': [list(p[:2]) for p in trail]}, f, indent=2)
            except OSError as exc:
                messagebox.showerror('Save trail', str(exc), parent=self.root)

    def leave(self):
        if self.link:
            self.link.close()
            self.link = None
        self.group_info = None
        self.trails.clear()
        self.refresh_menu()

    def friends_dialog(self):
        path = os.path.join(self.directory, 'friends.json') if hasattr(self, 'directory') else os.path.join(os.path.dirname(self.path), 'friends.json')
        try:
            with open(path, encoding='utf-8') as f: config = json.load(f)
        except (OSError, ValueError): config = {}
        win = tk.Toplevel(self.root)
        win.title('Friends • Fixed room')
        win.configure(bg='#142638'); win.resizable(False,False)
        entries = {}
        for row, (key,label) in enumerate((('url','Server address'),('code','Fixed room code'),('name','Your name'))):
            tk.Label(win,text=label,bg='#142638',fg='white').grid(row=row,column=0,padx=16,pady=10,sticky='w')
            entry=tk.Entry(win,width=42,show='*' if key=='code' else '')
            entry.insert(0,config.get(key,''));entry.grid(row=row,column=1,padx=16,pady=10)
            entries[key]=entry
        status=tk.StringVar(value='Disconnected')
        tk.Label(win,textvariable=status,bg='#142638',fg='white').grid(row=3,columnspan=2,pady=10)
        tk.Label(win,text='Up to 4 friends • Join the same game session.\nPosition sharing starts only after Connect.',bg='#142638',fg='white').grid(row=4,columnspan=2,pady=10)
        def connect():
            values={k:e.get().strip() for k,e in entries.items()}
            try:
                from g29_friends import endpoint
                endpoint(values['url'])
                if not 12<=len(values['code'])<=128:raise ValueError('Use a fixed code with 12 to 128 characters.')
                with open(path+'.tmp','w',encoding='utf-8') as f:json.dump(values,f,indent=2)
                os.replace(path+'.tmp',path)
                self.leave()
                self.link=FriendsLink(values['url'],values['code'],values['name'])
            except (ValueError,OSError) as exc:messagebox.showerror('Friends',str(exc),parent=win)
        tk.Button(win,text='Connect',command=connect).grid(row=5,column=0,pady=16)
        tk.Button(win,text='Disconnect',command=self.leave).grid(row=5,column=1,pady=16)
        def poll():
            if not win.winfo_exists():return
            status.set(self.link.error if self.link else 'Disconnected')
            win.after(500,poll)
        poll()

    def group_dialog(self, hosting):
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        win = self.dialog = tk.Toplevel(self.root)
        win.title('Host group' if hosting else 'Join group')
        win.attributes('-topmost', True)
        win.resizable(False, False)
        fields = {}
        rows = [('name', 'Your name', self.settings['name']),
                ('host', 'Host address (LAN / VPN)', '127.0.0.1' if hosting else ''),
                ('port', 'Group port', '5301'),
                ('code', 'Private group code', secrets.token_hex(8) if hosting else '')]
        for row, (key, label, default) in enumerate(rows):
            tk.Label(win, text=label).grid(row=row, column=0, sticky='w', padx=12, pady=7)
            entry = tk.Entry(win, width=30)
            entry.insert(0, default)
            entry.grid(row=row, column=1, padx=12, pady=7)
            fields[key] = entry
        if hosting: fields['host'].configure(state='disabled')
        text = ('Share your LAN / VPN address, port and code with friends.\nKeep this app open. Allow UDP on the group port through your firewall.'
                if hosting else 'Use the host\'s LAN / VPN address, port and code.\nEveryone must be in the same game session / world.')
        tk.Label(win, text=text, justify='left', wraplength=420).grid(row=4, column=0, columnspan=2, padx=12, pady=10)
        status = tk.StringVar(value='Positions are shared only while connected. Maximum 16 participants.')
        tk.Label(win, textvariable=status, wraplength=420).grid(row=5, column=0, columnspan=2, padx=12, pady=8)
        def connect():
            if self.connecting: return
            values = {k: v.get().strip() for k, v in fields.items()}
            try:
                port = int(values['port'])
                if not 1024 <= port <= 65535 or port == 5300: raise ValueError('Use a port from 1024 to 65535, except 5300.')
                if not 1 <= len(values['name']) <= 20: raise ValueError('Use a name of 1 to 20 characters.')
                if not 8 <= len(values['code']) <= 128: raise ValueError('Use a group code of 8 to 128 characters.')
                if not values['host']: raise ValueError('Enter the host address.')
            except ValueError as exc:
                status.set(str(exc)); return
            self.leave()
            self.settings['name'] = values['name']
            self.save()
            self.connecting = True
            self.group_info = {**values, 'hosting': hosting}
            status.set('Connecting...')
            def work():
                try:
                    link = GroupLink(values['host'], port, values['code'], values['name'], hosting)
                    if self.closed: link.close(); return
                    self.pending.put((link, None, win, status))
                except (OSError, ValueError) as exc:
                    self.pending.put((None, str(exc), win, status))
            threading.Thread(target=work, daemon=True).start()
        tk.Button(win, text='Start hosting' if hosting else 'Join', command=connect).grid(row=6, column=0, columnspan=2, pady=12)

    def tick(self):
        if self.closed: return
        frame_started = time.monotonic()
        while not self.pending.empty():
            link, error, win, status = self.pending.get_nowait()
            self.connecting = False
            if win.winfo_exists():
                if error: status.set(error)
                else:
                    win.destroy()
                    if self.group_info and self.group_info['hosting']:
                        self.root.after(0, self.show_group_details)
            if link: self.link = link
            self.refresh_menu()
        now = time.monotonic()
        with self.lock:
            pos = self.latest if now - self.received < 1.2 else None
            yaw = self.latest_yaw
            instruments = self.instruments if pos is not None else None
        players, connected = self.link.snapshot(pos) if self.link else ([], False)
        active = [p for p in players if p['pos'] is not None and p['id'] != self.link.id]
        if pos:
            active.insert(0, {'id': 'self', 'name': 'You', 'pos': pos, 'yaw': yaw})
            self.center = pos
        elif active:
            self.center = active[0]['pos']
        keep = {p['id'] for p in active} | {'self'}
        self.trails = {k: v for k, v in self.trails.items() if k in keep}
        for p in active:
            trail = self.trails.setdefault(p['id'], collections.deque(maxlen=800))
            if trail and (now - trail[-1][2] > 2 or math.dist(trail[-1][:2], p['pos']) > 250):
                trail.clear()
            if not trail or math.dist(trail[-1][:2], p['pos']) >= 2:
                trail.append((*p['pos'], now))
            elif trail:
                trail[-1] = (*trail[-1][:2], now)
        if self.settings['enabled']:
            width, height = self.window.winfo_screenwidth(), self.window.winfo_screenheight()
            positions = {'centro_inferior': ((width-320)//2, height-395), 'centro': ((width-320)//2, (height-300)//2),
                         'centro_superior': ((width-320)//2, 60), 'inferior_esquerda': (25, height-325),
                         'inferior_direita': (width-345, height-325)}
            position=self.settings.get('instruments_position' if self.settings['instruments_enabled'] else 'map_position',self.settings['position'])
            x, y = positions[position]
            panel_size = dashboard_size(self.settings['panel_scale'],width,height,self.settings['map_enabled']) if self.settings['style']=='dashboard' else (round(320*self.settings.get('map_scale',100)/100),round(300*self.settings.get('map_scale',100)/100))
            if self.settings['style'] in ('dashboard','transparent'):
                if position=='inferior_esquerda':x=25
                elif position=='inferior_direita':x=width-panel_size[0]-25
                else:x=(width-panel_size[0])//2
                if position=='centro':y=(height-panel_size[1])//2
                elif position=='centro_superior':y=60
                else:y=height-panel_size[1]-(12 if position=='centro_inferior' else 25)
                x=min(x,max(0,width-panel_size[0]))
                y=min(y,max(0,height-panel_size[1]))
            x, y = max(0,x), max(0,y)
            if self.settings['style'] in ('transparent','dashboard'):
                self.window.withdraw()
                if active and self.center is not None:
                    try:
                        if self.transparent_window is not None and self.native_size != panel_size:
                            self.transparent_window.close()
                            self.transparent_window = None
                        if self.transparent_window is None:
                            self.transparent_window = TransparentWindow(panel_size)
                            self.native_size = panel_size
                        frame = self.draw_minimap(active,background=self.settings['style']=='dashboard') if self.settings['map_enabled'] else self.map_frame
                        if self.settings['style']=='dashboard':
                            led_phase=self.shift_warning() if hasattr(self,'shift_warning') else None
                            frame=self.dashboard.render(frame,instruments,True,self.settings['dark_dials'],show_map=self.settings['map_enabled'],shift_light=self.settings.get('instrument_layout')=='shift_light',hardware_warning=led_phase)
                        if frame.size!=panel_size:frame=frame.resize(panel_size,Image.Resampling.LANCZOS)
                        self.transparent_window.show(frame, x, y)
                    except (OSError, AttributeError) as exc:
                        if self.transparent_window: self.transparent_window.hide()
                        self.settings['enabled'] = False
                        self.refresh_menu()
                        messagebox.showerror('Minimap', f'Unable to show the transparent minimap: {exc}', parent=self.root)
                elif self.transparent_window:
                    self.transparent_window.hide()
            else:
                if self.transparent_window: self.transparent_window.hide()
                self.draw(active, connected, pos)
                self.window.geometry(f'320x300+{x}+{y}')
                if not self.window.winfo_viewable(): self.window.deiconify()
        else:
            self.window.withdraw()
            if self.transparent_window: self.transparent_window.hide()
        period = (1/60 if self.settings['style']=='dashboard' else 1/30) if self.settings['enabled'] and active else .1
        self.root.after(max(1, int(1000*(period-(time.monotonic()-frame_started)))), self.tick)

    def draw_minimap(self, players, background=False):
        self.minimap.assist=self.settings.get('road_assist',True)
        rendered = []
        for p in players:
            copy = dict(p)
            trail = self.trails.get(p['id'], [])
            direction = self.heading or 0
            if self.roads.ready and p.get('yaw') is not None:
                # Yaw is body orientation, independent of drifting or reverse travel.
                dx,dz = math.sin(p['yaw']), math.cos(p['yaw'])
                a,b,_ = self.roads.rows[0]; c,d,_ = self.roads.rows[1]
                direction = math.atan2(a*dx+b*dz, -(c*dx+d*dz))
                if p['id'] == 'self': self.heading = direction
            elif self.roads.ready and len(trail) > 1:
                a,b = self.roads.to_pixel(trail[-2]),self.roads.to_pixel(trail[-1])
                direction = math.atan2(b[0]-a[0], -(b[1]-a[1]))
                if p['id'] == 'self':
                    self.heading = direction
            copy['heading'] = direction
            copy['color'] = ['#48BDFF','#FFBD59','#BA8CFF','#73E5AD'][int(hashlib.sha256(p['id'].encode()).hexdigest()[:4],16)%4]
            rendered.append(copy)
        angle = (self.heading or 0) if self.settings['rotate'] else 0
        if background or getattr(self,'map_future',None) is not None:
            if self.map_future is not None and self.map_future.done():
                self.map_frame=self.map_future.result()
                self.map_future=None
            if self.map_future is None:
                trails={key:list(value) for key,value in self.trails.items()} if self.settings['show_trails'] else None
                self.map_future=self.map_executor.submit(self.minimap.render,list(self.center),self.settings['zoom'],rendered,angle,trails,self.settings['names'])
            return self.map_frame
        return self.minimap.render(self.center, self.settings['zoom'], rendered, angle,
                    self.trails if self.settings['show_trails'] else None, self.settings['names'])

    def draw(self, players, connected, own):
        c = self.canvas
        c.delete('all')
        c.create_text(14, 17, text='GROUP MAP' if self.link else 'ROAD MAP', fill='#E6EDF3', anchor='w', font=('Segoe UI', 10, 'bold'))
        c.create_text(306, 17, text=f"{self.settings['zoom']} m" if self.roads.ready and self.center is not None else 'Overview', fill='#8E99A4', anchor='e')
        background = self.roads.render(self.center, self.settings['zoom'], self.settings['style'])
        if background is not None:
            if background is not self.map_image:
                self.map_photo = ImageTk.PhotoImage(background, master=self.root)
                self.map_image = background
            c.create_image(0,36,image=self.map_photo,anchor='nw')
        else:
            for x in range(20, 321, 40): c.create_line(x, 35, x, 263, fill='#17202A')
            for y in range(43, 264, 40): c.create_line(0, y, 320, y, fill='#17202A')
        radius = self.settings['zoom']
        def project(p):
            if self.roads.ready:
                return self.roads.project(p, self.center, radius)
            return (160 + (p[0]-self.center[0])*110/radius, 150 - (p[1]-self.center[1])*110/radius)
        def inside(p): return 8 <= p[0] <= 312 and 40 <= p[1] <= 258
        if self.center and (self.roads.ready or self.roads.image is None):
            for p in players:
                color = '#4DA3FF' if p['id'] == 'self' else ['#FF8C42', '#44D17A', '#D38DFF', '#FFD54A'][int(hashlib.sha256(p['id'].encode()).hexdigest()[:4],16)%4]
                trail = list(self.trails.get(p['id'], []))
                previous = None
                step = max(1, len(trail)//120)
                for point in (trail[::step] if self.settings['show_trails'] else []):
                    xy = project(point)
                    if previous and inside(previous) and inside(xy): c.create_line(*previous, *xy, fill=color, width=2)
                    previous = xy
                x, y = project(p['pos'])
                offscreen = not inside((x,y))
                x, y = max(12,min(308,x)), max(46,min(250,y))
                dx, dy = (0, -1)
                if len(trail) > 1:
                    current, previous = project(trail[-1]), project(trail[-2])
                    dx, dy = current[0]-previous[0], current[1]-previous[1]
                    length = math.hypot(dx,dy) or 1
                    dx, dy = dx/length, dy/length
                c.create_polygon(x+dx*9,y+dy*9,x-dx*5-dy*5,y-dy*5+dx*5,x-dx*5+dy*5,y-dy*5-dx*5,fill=color)
                distance = f" {math.dist(own,p['pos']):.0f}m" if own and p['id'] != 'self' else ''
                label = p['name'] + distance + (' >' if offscreen else '')
                c.create_text(max(65,min(255,x)), min(252,y+16), text=label, fill=color, font=('Segoe UI',8))
        if not players and self.roads.ready:
            c.create_text(160,150,text='Waiting for game telemetry...',fill='#8E99A4')
        c.create_rectangle(0,265,320,300,fill='#080A0D',outline='')
        status = ('Connected · '+str(len(players))+' driving') if connected else ('Waiting for host · check address / code' if self.link else 'Solo · Group sharing off')
        if self.roads.image is None:
            status = 'Road images missing · check map_assets'
        elif not self.roads.ready:
            status = 'Map → Calibrate road map... (3+ locations)'
        elif self.center:
            u,v = self.roads.to_pixel(self.center)
            if not (0<=u<self.roads.image.width and 0<=v<self.roads.image.height):
                status = 'Outside the captured map'
            elif self.roads.coverage.getpixel((int(u),int(v))) < 128:
                status = 'This area is missing from the screenshots'
        c.create_text(12,280,text=status,anchor='w',fill='#44D17A' if connected else '#8E99A4',font=('Segoe UI',8))

    def close(self):
        self.closed = True
        self.map_executor.shutdown(wait=False,cancel_futures=True)
        if self.transparent_window: self.transparent_window.close()
        if self.link: self.link.close()
        while not self.pending.empty():
            link, *_ = self.pending.get_nowait()
            if link: link.close()

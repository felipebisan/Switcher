"""Scale the existing compact canvas without restarting its update loop."""
import tkinter.font as tkfont


class CompactLayout:
    def __init__(self, namespace, overlay):
        self.namespace = namespace
        self.overlay = overlay
        self.scale = None
        self.canvas = namespace['telemetria_canvas']
        self.items = []
        for item in self.canvas.find_all():
            font = None
            if self.canvas.type(item) == 'text':
                font = tkfont.Font(root=self.canvas, font=self.canvas.itemcget(item, 'font')).actual()
            self.items.append((item, self.canvas.coords(item), font))

    def apply(self):
        value = self.overlay.settings.get('compact_scale', 100)
        if value == self.scale:
            return
        ratio = value / 100
        for item, coordinates, font in self.items:
            self.canvas.coords(item, *[coordinate * ratio for coordinate in coordinates])
            if font:
                self.canvas.itemconfigure(item, font=(font['family'], max(5, round(font['size'] * ratio)), font['weight']))
        self.namespace['TELEMETRIA_LARGURA'] = round(210 * ratio)
        self.namespace['TELEMETRIA_ALTURA'] = round(92 * ratio)
        self.namespace['reposicionar_hud_telemetria']()
        self.scale = value

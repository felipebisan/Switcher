"""G29 LED output, current-phase scheduling and local timing diagnostics."""
import math
import threading
import time
from g29_shiftprofile import shift_state
from g29_shiftlog import ShiftLog


def led_mask(rpm, maximum, now=None):
    count,_ = shift_state(rpm, maximum, 5, now)
    return (1 << count) - 1


class ShiftLights:
    def __init__(self, namespace, settings, clock=time.monotonic, diagnostics_path=None):
        self.ns, self.settings, self.clock = namespace, settings, clock
        self.stop = threading.Event()
        self.last_device = None
        self.last_mask = None
        self.last_sent = 0
        self.error = None
        self._display = None
        self.log = ShiftLog(diagnostics_path)
        self.log.record(event='start',version='scheduled-v1',blink_hz=2,poll_ms=10)
        self.thread = threading.Thread(target=self.run, daemon=True, name='G29 shift lights')

    def update(self, now=None, force_off=False):
        # The caller's timestamp may predate contention on the HID device.
        waiting = self.clock()
        record = None
        with self.ns['device_lock']:
            device = self.ns['device']
            if device is None:
                self.last_device = None
                self._display = None
                return
            with self.ns['telemetria_lock']:
                rpm, maximum = self.ns['telemetria_rpm'], self.ns['telemetria_rpm_max']
                packet_time = self.ns['telemetria_ultimo_pacote']
                telemetry_active = self.ns['telemetria_ativa']
            started = self.clock()
            active = telemetry_active and 0 <= started-packet_time < 1
            enabled = active and self.settings.get('shift_lights', True) and not force_off
            mask = led_mask(rpm, maximum, started) if enabled else 0
            warning = bool(enabled and math.isfinite(rpm) and math.isfinite(maximum)
                           and maximum > 0 and rpm / maximum > .83)
            if not warning:self._display = None
            if (device is self.last_device and mask == self.last_mask
                    and started-self.last_sent < 1 and not force_off):
                return
            try:
                written = device.write([0, 0xF8, 0x12, mask, 0, 0, 0, 0])
                if written != 8:
                    raise OSError(f'Incomplete LED report: {written}/8 bytes')
                finished = self.clock()
                self.last_device, self.last_mask, self.last_sent = device, mask, finished
                self._display = (mask == 31, finished) if warning else None
                self.error = None
                ok = True
            except (OSError, ValueError) as exc:
                finished = self.clock()
                self.error = str(exc)
                ok = False
            record = dict(event='write',ok=ok,started=started,finished=finished,
                          lock_wait_ms=(started-waiting)*1000,write_ms=(finished-started)*1000,
                          mask=mask,warning=warning,error=self.error)
        self.log.record(**record)

    def warning_state(self, now=None):
        """Last sent warning phase; None means use the standalone HUD clock."""
        now = self.clock() if now is None else now
        state = self._display
        with self.ns['telemetria_lock']:
            fresh = (self.ns['telemetria_ativa']
                     and 0 <= now-self.ns['telemetria_ultimo_pacote'] < 1)
        if (state is None or self.stop.is_set()
                or not fresh
                or not self.settings.get('shift_lights', True)
                or self.ns.get('device') is not self.last_device
                or not 0 <= now-state[1] < .75):
            return None
        return state[0]

    def next_delay(self):
        # Absolute deadlines discard missed ticks; never queue obsolete blink states.
        now = self.clock()
        period = .1 if self.error else .01
        return max(.001,(math.floor(now/period)+1)*period-now)

    def run(self):
        try:
            while not self.stop.is_set():
                self.update()
                self.stop.wait(self.next_delay())
        finally:
            self.update(force_off=True)
            self.log.close()

    def close(self):
        self.stop.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=1)
        else:
            self.update(force_off=True)
            self.log.close()

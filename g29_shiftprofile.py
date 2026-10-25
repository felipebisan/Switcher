"""Shared visual and physical shift-light timing and RPM progression."""
import math
import time

def shift_state(rpm, maximum, segments, now=None):
    if not all(math.isfinite(v) for v in (rpm,maximum)) or maximum<=0 or rpm<0:
        return 0,'#9BE564'
    ratio=min(1,rpm/maximum)
    warning=ratio>.83
    color='#FF4D4D' if warning else '#FF8C42' if ratio>=.70 else '#9BE564'
    count=round(segments*max(0,min(1,(ratio-.45)/.5)))
    if warning:
        now=time.monotonic() if now is None else now
        count=segments if int(now*4)%2==0 else 0
    return count,color

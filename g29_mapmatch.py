"""Conservative display-only matching against the local road geometry."""
import math
import numpy as np

class RoadMatcher:
    def __init__(self, paths):
        segments=[(a,b) for path,_ in paths for a,b in zip(path,path[1:]) if math.dist(a,b)>1e-6]
        self.a=np.array([s[0] for s in segments],dtype=float).reshape(-1,2)
        self.v=np.array([s[1] for s in segments],dtype=float).reshape(-1,2)-self.a
        self.l2=(self.v*self.v).sum(axis=1)
        self.reset()

    def reset(self):
        self.previous=None;self.direction=None;self.count=0;self.offset=np.zeros(2)

    def match(self, point, ppm):
        point=np.asarray(point,dtype=float)
        if not len(self.a) or ppm<=0:return (0.,0.)
        if self.previous is not None:
            delta=point-self.previous;distance=float(np.linalg.norm(delta))/ppm
            if distance>80:self.reset()
            elif distance>=1:
                self.direction=delta/np.linalg.norm(delta);self.previous=point.copy()
        if self.previous is None:self.previous=point.copy()
        if self.direction is None:return (0.,0.)
        t=np.clip(((point-self.a)*self.v).sum(axis=1)/self.l2,0,1)
        projected=self.a+t[:,None]*self.v
        distances=np.linalg.norm(projected-point,axis=1)/ppm
        alignment=np.abs(self.v@self.direction)/np.sqrt(self.l2)
        candidates=np.flatnonzero((distances<=12)&(alignment>=.94))
        target=np.zeros(2)
        if len(candidates):
            scores=distances[candidates]+(1-alignment[candidates])*30
            best=candidates[np.argmin(scores)]
            # Reject competing nearby roads instead of jumping between them.
            rivals=candidates[(np.linalg.norm(projected[candidates]-projected[best],axis=1)/ppm>3)&(scores<scores.min()+4)]
            # Junctions with a differently oriented road also remain unmatched.
            junction=np.any((distances<8)&(alignment<.8))
            if not len(rivals) and not junction:
                self.count+=1
                if self.count>=3:target=projected[best]-point
            else:self.count=0
        else:self.count=0
        # Small display correction; never modify telemetry or saved calibration.
        self.offset+=(target-self.offset)*.3
        return tuple(self.offset)

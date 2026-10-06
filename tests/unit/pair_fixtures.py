"""Small analytic detection cases, independent of the support solver."""
import numpy as np
from pair_fixture_adapter import Side


def rectangle(key, bounds=(-1,1,-1,1), height=0., n=2, direction=(0,0,1), **kwargs):
    lo,hi,bottom,top=bounds; xx,yy=np.meshgrid(np.linspace(lo,hi,n),np.linspace(bottom,top,n))
    v=np.column_stack([xx.ravel(),yy.ravel(),np.full(n*n,height)])
    cells=np.array([(j*n+i,j*n+i+1,(j+1)*n+i+1,(j+1)*n+i) for j in range(n-1) for i in range(n-1)])
    f=np.concatenate([cells[:,[0,1,2]],cells[:,[0,2,3]]])
    return Side(key,key,v,v.copy(),np.tile(direction,(len(v),1)),f,**kwargs)


def triangle(key, vertices, **kwargs):
    v=np.array(vertices,dtype=float)
    return Side(key,key,v,v.copy(),np.tile([0.,0.,1.],(len(v),1)),np.array([[0,1,2]]),**kwargs)


def collect(sides, search=.5, exhaustive=False):
    from pair_fixture_adapter import PairDetector
    with PairDetector(search) as detector:
        for side in sides: detector.add(side)
        return detector.detect(exhaustive)


def directed(result, receiver, provider):
    return [f for f in result['fragments'] if f['receiver_id']==receiver and f['provider_id']==provider]


def area(result, receiver, provider):
    return sum(f['area'] for f in directed(result,receiver,provider))

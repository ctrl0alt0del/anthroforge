"""Frozen analytic fixtures, independent of real muscle oracle labels."""
from dataclasses import replace
import numpy as np

from pair_fixture_adapter import Side, domain


def sheet(name, height, depth, n=5, shift=(0,0,0), size=(1,1), direction=(0,0,1)):
    u,v = np.meshgrid(np.linspace(-.5,.5,n), np.linspace(-.5,.5,n)); x,y = u.ravel(),v.ravel()
    base = np.column_stack((x*size[0],y*size[1],height(x,y))) + shift
    directions = np.tile(direction,(len(x),1)); own = base + directions*depth(x,y)[:,None]
    faces = [(a,a+1,a+n+1) for a in range(n*n-n) if (a+1)%n] + [(a,a+n+1,a+n) for a in range(n*n-n) if (a+1)%n]
    return domain(Side(name,name,base,own,directions,np.array(faces),displacement=.5))


def constant(value):
    return lambda x,y: np.full_like(x,value)


def make(name, height_a=.1, height_b=0., depth_a=.1, depth_b=.1, expected='supported', **kwargs):
    functions = [v if callable(v) else constant(v) for v in (height_a,height_b,depth_a,depth_b)]
    a=sheet('a',functions[0],functions[2],**kwargs); b=sheet('b',functions[1],functions[3])
    return dict(name=name,domains=[a,b],expected=expected,sign=1 if expected=='supported' else 0)


def cases():
    curved = lambda x,y: .04*(1-4*x*x)*(1-4*y*y)
    result = [make('separated'),make('similar_curved',lambda x,y:curved(x,y)+.1,curved),
        make('coincident_bases',0,0,.2,.1,'ambiguous'),make('identical',0,0,.1,.1,'ambiguous'),
        make('near_coincident',1e-7,0,.1,.1,'ambiguous'),make('crossing',lambda x,y:.2*x,0,.1,.1,'conflicting'),
        make('outer_crossing',.02,0,lambda x,y:.08+.12*x,.1,'conflicting'),
        make('nested_depth',.02,0,.03,.2,'conflicting'),make('partial',shift=(.7,0,0)),
        make('narrow_interior',size=(.003,.1),shift=(.071,.061,0),n=2),
        make('adjacent',shift=(1,0,0),expected='no_overlap'),make('separated_xy',shift=(3,0,0),expected='no_overlap')]
    result += [make('resolution_'+str(n),n=n) for n in (2,3,9,19)]
    return result + [make('opposed_directions',direction=(0,0,-1),expected='ambiguous'),make('tangent_directions',direction=(1,0,0),expected='ambiguous'),islands(1),islands(.005)]


def joined(a,b):
    return replace(a,base=np.concatenate((a.base,b.base)),own=np.concatenate((a.own,b.own)),direction=np.concatenate((a.direction,b.direction)),
                   faces=np.concatenate((a.faces,b.faces+len(a.base))),parts=np.zeros(len(a.faces)+len(b.faces),dtype=np.int64),sources=np.arange(len(a.faces)+len(b.faces)))


def islands(size):
    a=sheet('a',constant(.1),constant(.1)); b=sheet('b',constant(0),constant(.1))
    extra_a=sheet('a',constant(-.1),constant(.1),n=2,size=(size,size),shift=(2,0,0))
    extra_b=sheet('b',constant(0),constant(.1),n=2,size=(size,size),shift=(2,0,0))
    return dict(name='changing_order_islands_'+str(size),domains=[joined(a,extra_a),joined(b,extra_b)],expected='conflicting',sign=0)


def transformed(case, matrix, scale=1):
    values = []
    for d in case['domains']:
        values.append(replace(d,base=np.ascontiguousarray(d.base@matrix.T*scale),own=np.ascontiguousarray(d.own@matrix.T*scale),
                              direction=np.ascontiguousarray(d.direction@matrix.T),displacement=d.displacement*scale))
    return dict(case,domains=values)

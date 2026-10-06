from dataclasses import replace
import numpy as np
from stack_multi_fixtures import chain,settings
from test_muscle_stacking import inflated
from test_muscle_stacking_material import box


def translated(domains,dx,prefix=''):
    return [replace(d,key=replace(d.key,muscle=prefix+d.key.muscle),group=prefix+d.group,
        base=d.base+[dx,0,0],own=d.own+[dx,0,0],material=replace(d.material,vertices=d.material.vertices+[dx,0,0])) for d in domains]


def fixture():
    return chain(n=9)+translated([inflated('other_lower',0,.3,n=5),inflated('other_cover',.1,.2,n=5)],7)


def modify(domains,**fields):
    return [replace(domains[0],**fields),*domains[1:]]


def cases():
    v=fixture();a=v[0];new=inflated('new_neighbor',-.1,.1,(-.5,.5,-.4,.4),n=5)
    return [('unchanged',v,settings()),('outer_edit',modify(v,own=a.base+(a.own-a.base)*1.1),settings()),
        ('base_edit',modify(v,base=a.base-[0,0,.01]),settings()),('direction_edit',modify(v,direction=-a.direction),settings()),
        ('topology_edit',modify(v,faces=a.faces[:,::-1]),settings()),('provenance_edit',modify(v,sources=a.sources+20),settings()),
        ('group_edit',modify(v,group=v[1].group),settings()),('addition',v+[new],settings()),('deletion',v[1:],settings()),
        ('neighbor_move',v[:3]+translated(v[3:],-6.5),settings()),('reordered',list(reversed(v)),settings()),
        ('search_edit',v,replace(settings(),search_distance=.09)),('smoothing_edit',v,settings(radius=.3)),
        ('eviction',v,replace(settings(),cache_bytes=0)),('invalid_input',modify(v,valid=False),settings()),
        ('obstacle_edit',[replace(d,obstacles=(box((-2,-2,-1),(2,2,-.5)),)) for d in v],settings())]

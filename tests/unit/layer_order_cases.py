"""Truth is fixed from construction, never inferred from the resolver answer."""
from dataclasses import replace
import numpy as np
from layer_order_fixtures import cases as previous,make,sheet,constant,transformed


def varying(n):
    a=sheet('a',lambda x,y:.1+.03*x*x,constant(.1),n=n)
    b=sheet('b',lambda x,y:.03*x*x,constant(.2),n=n)
    values=[]
    for d in (a,b):
        direction=np.column_stack((-.06*d.base[:,0],np.zeros(len(d.base)),np.ones(len(d.base))))
        direction/=np.linalg.norm(direction,axis=1)[:,None];values.append(replace(d,direction=direction))
    return dict(name=f'varying_directions_{n}',domains=values,expected='supported',underlying=1)


def cases():
    mapping={'ambiguous':{'coincident_bases','conflicting_directions_or_local_order','projection_requires_review'},'conflicting':{'intersecting_bases','conflicting_directions_or_local_order'},'no_overlap':{'no_upward_evidence'}}
    result=previous()
    for c in result:
        if c['name'] in ('outer_crossing','nested_depth'):c['expected']='supported'
        c['underlying']=1;c['allowed']=mapping.get(c['expected'],{c['expected']})
    result += [make('shared_boundary',lambda x,y:.1*(x+.5)),make('large_depth',10,0),make('disabled_inflation',.1,0,0,0)]
    result += [varying(n) for n in (3,9,21)]
    result += [dict(transformed(make('mirror'),np.diag([-1,1,1])),name='mirrored_identity')]
    b=transformed(make('side_b'),np.diag([1,1,-1]));b['domains']=[replace(d,key=replace(d.key,side='B')) for d in b['domains']];result.append(b)
    for c in result:c.setdefault('allowed',{c['expected']});c.setdefault('underlying',1)
    return result

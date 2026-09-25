"""Topology preparation for a continuous bone-conforming attachment."""
import numpy as np

def compact(v,f):
    points,index,inverse=np.unique(np.round(v,9),axis=0,return_index=True,return_inverse=True)
    faces=inverse[np.array(f,int)];good=np.array([len(set(t))==3 for t in faces])
    return np.array(v)[index],faces[good]

def clip_polygon(points,values,level):
    result=[]
    for i,a in enumerate(points):
        j=(i+1)%len(points);b=points[j];da=values[i]-level;db=values[j]-level
        if da<=0:result.append(a)
        if (da<0<db) or (db<0<da):result.append(a+(b-a)*da/(da-db))
    return result

def cut(v,f,values,level):
    vertices=[];faces=[]
    for tri in f:
        polygon=clip_polygon(v[tri],values[tri],level);n=len(vertices);vertices.extend(polygon)
        for j in range(1,len(polygon)-1):faces.append([n,n+j,n+j+1])
    return compact(vertices,faces)

def boundaries(f):
    directed=np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]);u,inv,c=np.unique(np.sort(directed,axis=1),axis=0,return_inverse=True,return_counts=True)
    assert c.max() <= 2, 'Nonmanifold edges'
    pairs=directed[c[inv]==1];nxt={int(a):int(b) for a,b in pairs};assert len(nxt)==len(pairs),'Branching boundary'
    loops=[]
    while nxt:
        start=min(nxt);loop=[start];i=nxt.pop(start)
        while i!=start:loop.append(i);i=nxt.pop(i)
        loops.append(np.array(loop))
    return loops

def sample_loop(v,ids,count):
    p=v[ids];p=np.vstack([p,p[0]]);d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))];t=np.arange(count)*d[-1]/count
    return np.column_stack([np.interp(t,d,p[:,i]) for i in range(3)])

def fractions(v,ids):
    p=v[ids];d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(np.vstack([p,p[0]]),axis=0),axis=1))]
    return d[:-1]/d[-1]

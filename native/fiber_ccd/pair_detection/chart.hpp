#pragma once
namespace af_pair {
static bool outside_edges(const Query& q,const Vec* provider) {
    Vec v[3];for(int i=0;i<3;++i)v[i]=ly_project(provider[i],q.frame);
    for(Vec edge:q.edges){double largest=-INFINITY;
        for(Vec p:v)largest=std::max(largest,edge.x*p.x+edge.y*p.y+edge.z);
        if(largest < -1e-11)return true;}return false;
}
static void prepare_edges(Query& q) {
    Vec r[3];for(int i=0;i<3;++i)r[i]=ly_project(q.triangle[i],q.frame);
    double sign=ly_cross(sub(r[1],r[0]),sub(r[2],r[0]))>0?1:-1;
    for(int i=0;i<3;++i){Vec delta=sub(r[(i+1)%3],r[i]);
        q.edges[i]={-sign*delta.y,sign*delta.x,sign*(delta.y*r[i].x-delta.x*r[i].y)};}
}
static bool prepare(Query& q,Result& out) {
    face(q.receiver,q.rf,q.triangle);q.origin=q.triangle[0];Vec direction{0,0,0};
    for(Vec& v:q.triangle)v=sub(v,q.origin);
    for(int i=0;i<3;++i)direction=add(direction,q.receiver.direction[q.receiver.faces[q.rf*3+i]]);
    if(norm(direction)<q.settings.epsilon){++out.stats[4];return false;}
    q.frame=ly_frame(direction);Vec normal=cross(sub(q.triangle[1],q.triangle[0]),sub(q.triangle[2],q.triangle[0]));
    if(norm(normal)<1e-15)return false;
    if(std::abs(dot(normal,q.frame.d))<q.settings.epsilon*norm(normal)){++out.stats[4];return false;}
    if(q.gate)prepare_edges(q);return true;
}
}

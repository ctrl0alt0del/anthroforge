#pragma once
struct LyFrame { Vec u,v,d; };
static double ly_cross(Vec a,Vec b) {return a.x*b.y-a.y*b.x;}
static Vec ly_project(Vec p,const LyFrame& f) {return {dot(p,f.u),dot(p,f.v),dot(p,f.d)};}

static LyFrame ly_frame(Vec direction) {
    Vec d=af_env_unit(direction),axis=std::abs(d.x)<.8?Vec{1,0,0}:Vec{0,1,0};
    Vec u=af_env_unit(cross(d,axis));return {u,cross(d,u),d};
}

#pragma once
#include "af_transfer_constraints_compile.hpp"
namespace af_transfer_constraints {
struct Goals { std::vector<P> p;std::vector<double>w; };
using Projection=void(*)(const Input&,const State&,int,const std::vector<P>&,Goals&);
static void accumulate(Goals&g,int i,P p,double w) {g.p[i]=add(g.p[i],mul(p,w));g.w[i]+=w;}
static void exact_goal(const Input&,const State&,int,const std::vector<P>&,Goals&) {}
static void shape_goal(const Input&a,const State&,int k,const std::vector<P>&shape,Goals&g) {
    for(int i=0;i<a.base->n;++i)accumulate(g,i,shape[i],a.rules[k].weight*a.factors[k*a.base->n+i]);
}
static void guide_goal(const Input&a,const State&,int k,const std::vector<P>&,Goals&g) {
    for(int i=0;i<a.base->n;++i)accumulate(g,i,point(a.rules[k],i),a.rules[k].weight*a.factors[k*a.base->n+i]);
}
static void clearance_goal(const Input&a,const State&s,int k,const std::vector<P>&,Goals&g) {
    auto&r=a.rules[k];for(int w=0;w<a.base->nw;++w)if(r.worlds[w]){auto q=query(a.base->worlds[w],s.x);
        for(int i=0;i<a.base->n;++i)if(!s.fixed[i]&&violation(q,i,r.gap)>0){
            P p{q.near[3*i]+r.gap*q.normals[3*i],q.near[3*i+1]+r.gap*q.normals[3*i+1],q.near[3*i+2]+r.gap*q.normals[3*i+2]};
            accumulate(g,i,p,r.weight*a.factors[k*a.base->n+i]);}}
}
static const Projection projectors[]={exact_goal,shape_goal,guide_goal,clearance_goal,exact_goal};
static std::vector<P> shape_goals(const State&s) {
    std::vector<P>out(s.x.size());std::vector<int>counts(s.x.size());
    for(auto&ids:s.clusters)cluster(s.rest,s.x,ids,out,counts);
    for(int i=0;i<(int)out.size();++i)out[i]=counts[i]?mul(out[i],1./counts[i]):s.x[i];return out;
}
static double step(const Input&a,State&s) {
    int n=a.base->n;Goals g{std::vector<P>(n),std::vector<double>(n)};auto shape=shape_goals(s);
    for(int k=0;k<a.count;++k)if(active(a.rules[k]))projectors[a.rules[k].kind](a,s,k,shape,g);
    double change=0;for(int i=0;i<n;++i){P p=g.w[i]>0?mul(add(s.x[i],mul(g.p[i],1./g.w[i])),.5):s.x[i];
        if(s.fixed[i])p=s.hard[i];if(!std::isfinite(norm2(p)))throw std::runtime_error("nonfinite iterate");change+=norm2(sub(p,s.x[i]));s.x[i]=p;}
    return sqrt(change/n);
}
static void solve(const Input&a,State&s) {
    auto&b=*a.base;for(int it=0;it<b.iterations;++it){b.stats[1]=step(a,s);b.stats[2]=it+1;if(b.stats[1]<b.convergence)break;}store(s.x,b.output);
}
}

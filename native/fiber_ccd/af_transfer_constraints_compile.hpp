#pragma once
#include "af_transfer_constraints_types.hpp"
namespace af_transfer_constraints {
static void factors(const Input&a,const State&s,int k) {
    auto&r=a.rules[k];int n=a.base->n;auto out=a.factors+k*n;
    auto d=geodesic(n,r.selected,s.edges,unpack(n,a.base->source));
    for(int i=0;i<n;++i){double t=r.falloff>0?std::clamp(d[i]/r.falloff,0.,1.):1.;
        out[i]=active(r)&&r.allowed[i]?(r.selected[i]?1.:1-t*t*(3-2*t)):0.;}
}
static void conflict(const Input&a,int k,int vertex,const char*message) {
    a.summary[k*8+4]=vertex+1;
    for(int j=0;j<a.count;++j)if(active(a.rules[j])&&hard(a.rules[j])&&a.rules[j].selected[vertex])a.summary[j*8+4]=vertex+1;
    throw std::domain_error(message);
}
static void lock(const Input&a,State&s,int k) {
    auto&r=a.rules[k];if(!active(r)||!hard(r))return;
    for(int i=0;i<a.base->n;++i)if(r.selected[i]){auto p=point(r,i);
        if(s.fixed[i]&&norm2(sub(s.hard[i],p))>1e-20)conflict(a,k,i,"conflicting exact targets");
        s.fixed[i]=1;s.hard[i]=p;s.x[i]=p;}
}
static void clearance_conflicts(const Input&a,const State&s) {
    for(int k=0;k<a.count;++k){auto&r=a.rules[k];if(!active(r)||r.kind!=Clearance||r.gap<=0)continue;
        for(int w=0;w<a.base->nw;++w)if(r.worlds[w]){auto q=query(a.base->worlds[w],s.hard);
            for(int i=0;i<a.base->n;++i)if(s.fixed[i]&&a.factors[k*a.base->n+i]>0&&violation(q,i,r.gap)>r.tolerance)conflict(a,k,i,"exact target conflicts with positive clearance");}}
}
static std::vector<std::vector<int>> local_clusters(const Input&a,const std::vector<P>&source) {
    std::map<int,std::vector<int>>groups;std::vector<std::vector<int>>out;
    for(int i=0;i<a.base->n;++i)groups[a.owners[i]].push_back(i);
    for(auto&entry:groups){std::vector<P>p;for(int i:entry.second)p.push_back(source[i]);
        if(extent(p)<=1e-12)throw std::invalid_argument("degenerate source object");
        for(auto ids:clusters(p,extent(p)*a.base->cluster_radius)){for(int&i:ids)i=entry.second[i];out.push_back(ids);}}
    return out;
}
static State compile(const Input&a) {
    auto&b=*a.base;auto source=unpack(b.n,b.source),initial=unpack(b.n,b.target);State s;
    s.rest=placement(b,source,initial);s.x=s.rest;s.hard=s.rest;s.fixed.resize(b.n);
    s.edges=edges(tree(source),b.faces,b.nf,0);s.clusters=local_clusters(a,source);
    for(int k=0;k<a.count;++k){factors(a,s,k);lock(a,s,k);}clearance_conflicts(a,s);
    store(s.rest,b.rest);for(int i=0;i<b.n;++i)b.influence[i]=s.fixed[i];return s;
}
}

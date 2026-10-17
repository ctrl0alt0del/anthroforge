#pragma once
#include "af_transfer_constraints_solve.hpp"
namespace af_transfer_constraints {
static double dot(P a,P b) {return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
static double area(P a,P b,P c) {
    P u=sub(b,a),v=sub(c,a);return .5*sqrt(norm2({u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]}));
}
static std::vector<double> vertex_areas(const Input&a,const std::vector<P>&source) {
    std::vector<double>out(a.base->n);for(int f=0;f<a.base->nf;++f){auto t=a.base->faces+3*f;double mass=area(source[t[0]],source[t[1]],source[t[2]])/3;
        for(int j=0;j<3;++j)out[t[j]]+=mass;}return out;
}
static void stations(const Input&a,int k,int axis,const std::vector<P>&source,const std::vector<double>&mass) {
    auto&r=a.rules[k];P direction{r.axes[3*axis],r.axes[3*axis+1],r.axes[3*axis+2]};int bins=axis?r.bins_v:r.bins_u;
    double lo=1e100,hi=-1e100;for(int i=0;i<a.base->n;++i)if(r.intended[i]){double t=dot(source[i],direction);lo=std::min(lo,t);hi=std::max(hi,t);}
    double total[16]={},selected[16]={};for(int i=0;i<a.base->n;++i)if(r.intended[i]){int b=std::clamp(int((dot(source[i],direction)-lo)/std::max(hi-lo,1e-20)*bins),0,bins-1);
        total[b]+=mass[i];selected[b]+=r.selected[i]*mass[i];}
    for(int b=0;b<16;++b)a.coverage[k*32+axis*16+b]=total[b]>0?selected[b]/total[b]:-1;
}
static void coverage(const Input&a,int k,const std::vector<P>&source,const std::vector<double>&mass) {
    auto&r=a.rules[k];double count=0,selected=0,total_area=0,selected_area=0;
    for(int i=0;i<a.base->n;++i)if(r.intended[i]){count++;selected+=r.selected[i];total_area+=mass[i];selected_area+=r.selected[i]*mass[i];}
    a.summary[k*8+2]=count?selected/count:1.;a.summary[k*8+3]=total_area?selected_area/total_area:1.;
    for(int axis=0;axis<2;++axis)stations(a,k,axis,source,mass);
}
static void residuals(const Input&a,const State&s,int k,const std::vector<P>&shape) {
    auto&r=a.rules[k];auto out=a.residuals+k*a.base->n;double scale=std::max(extent(s.rest),1e-12);
    for(int i=0;i<a.base->n;++i){out[i]=0;if(a.factors[k*a.base->n+i]<=0)continue;
        if(r.kind==Shape)out[i]=sqrt(norm2(sub(s.x[i],shape[i])))/scale;
        else if(r.kind!=Clearance)out[i]=sqrt(norm2(sub(s.x[i],point(r,i))));}
    if(r.kind==Clearance)for(int w=0;w<a.base->nw;++w)if(r.worlds[w]){auto q=query(a.base->worlds[w],s.x);
        for(int i=0;i<a.base->n;++i)if(a.factors[k*a.base->n+i]>0)out[i]=std::max(out[i],violation(q,i,r.gap));}
}
static void strain(const Input&a,const State&s,int k) {
    if(a.rules[k].kind!=Shape)return;auto out=a.residuals+k*a.base->n;std::fill(out,out+a.base->n,0.);
    for(auto [i,j]:s.edges){double before=sqrt(norm2(sub(s.rest[i],s.rest[j]))),after=sqrt(norm2(sub(s.x[i],s.x[j])));
        if(before<=1e-15)continue;double error=fabs(log(std::max(after/before,1e-15)));
        for(int v:{i,j})if(a.factors[k*a.base->n+v]>0)out[v]=std::max(out[v],error);}
}
static void summarize(const Input&a,const State&s,int k) {
    int n=a.base->n;auto sum=a.summary+8*k;double weight=0;auto initial=unpack(n,a.base->target);auto&r=a.rules[k];
    for(int i=0;i<n;++i){double f=a.factors[k*n+i],error=a.residuals[k*n+i];a.movement[k*n+i]=sqrt(norm2(sub(s.x[i],initial[i])));
        if(f<=0)continue;sum[0]=std::max(sum[0],error);sum[1]=std::max(sum[1],a.movement[k*n+i]);sum[5]+=f*error*error;weight+=f;sum[7]++;
        if(r.kind==Attachment||r.kind==Guide||r.kind==Protection)sum[6]=std::max(sum[6],sqrt(norm2(sub(initial[i],point(r,i)))));}
    sum[5]/=std::max(weight,1e-30);
}
static void report(const Input&a,const State&s) {
    auto source=unpack(a.base->n,a.base->source),shape=shape_goals(s);auto mass=vertex_areas(a,source);
    for(int k=0;k<a.count;++k){residuals(a,s,k,shape);strain(a,s,k);summarize(a,s,k);coverage(a,k,source,mass);}
}
}
AF_NATIVE_EXPORT int af_transfer_constraints_fit(af_transfer_constraints::Input*a) {
    if(!a)return 1;
    try {af_transfer_constraints::validate(*a);auto s=af_transfer_constraints::compile(*a);af_transfer_constraints::solve(*a,s);af_transfer_constraints::report(*a,s);return 0;}
    catch(const std::domain_error&){return 4;}catch(const std::invalid_argument&){return 1;}catch(const std::bad_alloc&){return 2;}catch(...){return 3;}
}

// ABI 1: all fitting and iterative clearance queries stay inside this library.
#pragma once
#include "af_transfer_math.hpp"
#include "af_transfer_graph.hpp"
namespace af_transfer_shape {
struct Input {
    int abi,n,nf,nw,reflection,iterations;
    const double *source,*target;const int *fixed,*faces;void **worlds;
    double radius,cluster_radius,bridge,shape,collision,clearance,convergence,far_influence;
    double *rest,*influence,*output,*stats;
};
struct Contact { std::vector<P> goals;std::vector<double> weights; };
static void validate(const Input&a) {
    if(a.abi!=1||a.n<4||a.n>100000||a.nf<1||a.nf>200000||a.nw<0||a.nw>32||a.iterations<1||a.iterations>1000)throw std::invalid_argument("budget");
    if(!a.source||!a.target||!a.fixed||!a.faces||!a.rest||!a.influence||!a.output||!a.stats||(a.nw&&!a.worlds))throw std::invalid_argument("pointer");
    for(double x:{a.radius,a.cluster_radius,a.bridge,a.shape,a.collision,a.clearance,a.convergence,a.far_influence})if(!std::isfinite(x)||x<0)throw std::invalid_argument("settings");
    if(a.radius<=0||a.cluster_radius<=0||a.shape<=0||a.convergence<=0||a.far_influence>1||(a.reflection!=1&&a.reflection!=-1))throw std::invalid_argument("settings");
    int pins=0;for(int i=0;i<a.n;++i){if(a.fixed[i]!=0&&a.fixed[i]!=1)throw std::invalid_argument("mask");pins+=a.fixed[i];}
    if(!pins)throw std::invalid_argument("missing attachment band");
    for(int i=0;i<a.n*3;++i)if(!std::isfinite(a.source[i])||!std::isfinite(a.target[i]))throw std::invalid_argument("coordinate");
    for(int i=0;i<a.nf*3;++i)if(a.faces[i]<0||a.faces[i]>=a.n)throw std::invalid_argument("triangle");
    for(int i=0;i<a.nw;++i)if(!a.worlds[i])throw std::invalid_argument("world");
}
static P mean(const std::vector<P>&p) { P c{};for(P x:p)c=add(c,x);return mul(c,1.0/p.size()); }
static std::array<double,4> align(const std::vector<P>&a,const std::vector<P>&b,P ca,P cb) {
    double h[3][3]={};for(size_t i=0;i<a.size();++i){P x=sub(a[i],ca),y=sub(b[i],cb);for(int j=0;j<3;++j)for(int k=0;k<3;++k)h[j][k]+=x[j]*y[k];}return quaternion(h);
}
static std::vector<P> placement(const Input&input,const std::vector<P>&s,const std::vector<P>&target) {
    auto a=s;for(P&p:a)p[0]*=input.reflection;P ca=mean(a),cb=mean(target);auto q=align(a,target,ca,cb);double numerator=0,denominator=0;
    for(size_t i=0;i<a.size();++i){P x=rotate(sub(a[i],ca),q),y=sub(target[i],cb);for(int j=0;j<3;++j)numerator+=x[j]*y[j];denominator+=norm2(x);}
    double scale=numerator/std::max(denominator,1e-30);if(!std::isfinite(scale)||scale<=1e-12)throw std::invalid_argument("similarity");
    input.stats[0]=scale;for(int i=0;i<4;++i)input.stats[3+i]=q[i];for(int i=0;i<3;++i){input.stats[7+i]=ca[i];input.stats[10+i]=cb[i];}
    for(P&p:a)p=add(cb,mul(rotate(sub(p,ca),q),scale));return a;
}
static void store(const std::vector<P>&p,double*out) { for(size_t i=0;i<p.size();++i)for(int j=0;j<3;++j)out[3*i+j]=p[i][j]; }
static std::vector<P> initialize(const Input&a,const std::vector<P>&rest,const std::vector<P>&target,const std::vector<std::pair<int,int>>&edges) {
    auto distance=geodesic(a.n,a.fixed,edges,rest);std::vector<P>x(a.n);double radius=extent(target)*a.radius;
    for(int i=0;i<a.n;++i){double t=std::clamp(distance[i]/radius,0.,1.);double w=a.far_influence+(1-a.far_influence)*(1-t*t*(3-2*t));
        a.influence[i]=w;x[i]=a.fixed[i]?target[i]:add(rest[i],mul(sub(target[i],rest[i]),w));}return x;
}
static Contact contacts(const Input&a,const std::vector<P>&x) {
    Contact out{std::vector<P>(a.n),std::vector<double>(a.n,0)};if(!a.nw||a.collision<=0)return out;
    std::vector<double>flat(a.n*3),near(a.n*3),normals(a.n*3),dist(a.n);std::vector<int>owner(a.n),inside(a.n);store(x,flat.data());
    for(int k=0;k<a.nw;++k){int status=af_world_nearest_points(a.worlds[k],flat.data(),a.n,near.data(),normals.data(),dist.data(),owner.data(),inside.data());
        if(status)throw std::runtime_error("collision query failed");
        for(int i=0;i<a.n;++i)if(inside[i]&&!a.fixed[i]){P p{near[3*i]+a.clearance*normals[3*i],near[3*i+1]+a.clearance*normals[3*i+1],near[3*i+2]+a.clearance*normals[3*i+2]};
            out.goals[i]=add(out.goals[i],mul(p,a.collision));out.weights[i]+=a.collision;}}
    return out;
}
static double step(const Input&a,const std::vector<P>&rest,const std::vector<P>&target,const std::vector<std::vector<int>>&ids,std::vector<P>&x) {
    std::vector<P>goals(a.n);std::vector<int>count(a.n);for(const auto&g:ids)cluster(rest,x,g,goals,count);auto hit=contacts(a,x);double change=0;
    for(int i=0;i<a.n;++i){double w=.02+.6*a.influence[i],s=a.shape*(1.25-a.influence[i]);P shape=count[i]?mul(goals[i],1.0/count[i]):x[i];
        P next=mul(add(add(mul(shape,s),mul(target[i],w)),hit.goals[i]),1/(s+w+hit.weights[i]));next=a.fixed[i]?target[i]:mul(add(x[i],next),.5);
        if(!std::isfinite(norm2(next)))throw std::runtime_error("nonfinite iterate");change+=norm2(sub(next,x[i]));x[i]=next;}return sqrt(change/a.n);
}
static void solve(const Input&a) {
    auto source=unpack(a.n,a.source),target=unpack(a.n,a.target);double size=extent(source);
    if(size<=1e-12||extent(target)<=1e-12)throw std::invalid_argument("degenerate input");auto rest=placement(a,source,target);store(rest,a.rest);
    auto ids=clusters(source,size*a.cluster_radius);auto e=edges(tree(source),a.faces,a.nf,size*a.bridge);auto x=initialize(a,rest,target,e);
    for(int i=0;i<a.iterations;++i){a.stats[1]=step(a,rest,target,ids,x);a.stats[2]=i+1;if(a.stats[1]<a.convergence)break;}
    store(x,a.output);
}
}
AF_NATIVE_EXPORT int af_transfer_shape_fit(af_transfer_shape::Input*a) {
    if(!a)return 1;
    try {af_transfer_shape::validate(*a);af_transfer_shape::solve(*a);return 0;}
    catch(const std::invalid_argument&){return 1;}catch(const std::bad_alloc&){return 2;}catch(...){return 3;}
}

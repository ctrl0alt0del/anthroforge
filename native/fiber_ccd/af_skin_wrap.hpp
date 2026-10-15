#pragma once
namespace af_skin {
struct WrapGrid {
    int nx,ny,nz; double h; Vec origin; float* field;
    const float* coarse; const int* shape; const double* transform;
    std::vector<unsigned char> flags;
    size_t index(int x,int y,int z) const { return (size_t(x)*ny+y)*nz+z; }
    Vec point(int x,int y,int z) const { return add(origin,{x*h,y*h,z*h}); }
};
inline float coarse_value(const WrapGrid& g,Vec p) {
    Vec q=mul(sub(p,load3(g.transform)),1/g.transform[3]); int a[3]; double w[3];
    for(int k=0;k<3;++k) { double v=std::clamp((&q.x)[k],0.,double(g.shape[k]-1));
        a[k]=std::min(g.shape[k]-2,int(v)); w[k]=v-a[k]; }
    double result=0;
    for(int i=0;i<8;++i) { int x=i&1,y=(i>>1)&1,z=(i>>2)&1;
        size_t j=(size_t(a[0]+x)*g.shape[1]+a[1]+y)*g.shape[2]+a[2]+z;
        result+=g.coarse[j]*(x?w[0]:1-w[0])*(y?w[1]:1-w[1])*(z?w[2]:1-w[2]); }
    return float(result);
}
inline double empty_radius(const double* sample,double offset,double h) {
    double d=sample[0],width=sample[1],limit=sample[2],strength=sample[3];
    if(width<=0)return std::max(0.,d-std::max(offset,.8*h));
    double clearance=std::max(.8*h,std::min(offset,std::max(.8*h,(width-3.6*h)*.5)));
    double radius=std::max(0.,std::min(d,width-d)-clearance);
    return width>limit || limit<=0 ? radius : (1-strength)*radius;
}
inline bool clear_gap_pair(const GapScene& scene,Vec p,Vec d,double reach) {
    Hit forward,backward; forward.distance=backward.distance=reach;
    ray_node(*scene.mesh,p,d,0,-1,forward); if(forward.face>=0)return false;
    ray_node(*scene.mesh,p,mul(d,-1),0,-1,backward); return backward.face<0;
}
inline bool open_gap_cone(const GapScene& scene,Vec p,Vec a,Vec b,double angle,double reach) {
    for(int side=-1;side<=1;++side) {
        double t=angle+side*3.141592653589793/6;
        if(!clear_gap_pair(scene,p,add(mul(a,std::cos(t)),mul(b,std::sin(t))),reach))return false;
    }
    return true;
}
inline bool through_gap(const GapScene& scene,Vec p,const double* sample,double reach) {
    if(sample[0]<sample[1]*.4)return false;
    if(!opposing_patches(scene,sample))return false;
    Vec axis=load3(sample+9),reference=std::abs(axis.x)<.8?Vec{1,0,0}:Vec{0,1,0};
    Vec a=unit(cross(axis,reference)),b=unit(cross(axis,a));
    for(int angle=0;angle<8;++angle)
        if(open_gap_cone(scene,p,a,b,angle*3.141592653589793/8,reach))return true;
    return false;
}
inline bool resolve_gap_center(const GapScene& scene,double* sample,double reach) {
    if(sample[1]<=0)return false; Vec center=load3(sample+6); Hit nearby=nearest(scene,center);
    if(nearby.face<0)return false; int owner=scene.owners[nearby.face];
    sample[1]=std::min(sample[1],2*nearby.distance);
    sample[2]=std::min(sample[2],scene.limits[owner]); sample[3]=std::min(sample[3],scene.strengths[owner]);
    if(sample[1]<=sample[2] && sample[3]==1)return false;
    double check[13]; std::copy(sample,sample+13,check); check[0]=check[1]*.5;
    return opposing_patches(scene,check);
}
inline void distance_line(std::vector<float>& f,double h2) {
    int n=int(f.size()),k=0; std::vector<int> v(n); std::vector<double> bounds(n+1); bounds[0]=-INFINITY; bounds[1]=INFINITY;
    for(int q=1;q<n;++q) {
        double s=0;
        do { int p=v[k]; s=((double(f[q])-f[p])/h2+double(q)*q-double(p)*p)/(2*(q-p));
            if(s>bounds[k] || k==0)break; --k; } while(true);
        ++k; v[k]=q; bounds[k]=s; bounds[k+1]=INFINITY;
    }
    std::vector<float> out(n); k=0;
    for(int q=0;q<n;++q) { while(bounds[k+1]<q)++k; double d=q-v[k]; out[q]=float(d*d*h2+f[v[k]]); }
    f.swap(out);
}
}
#include "af_skin_separation.hpp"

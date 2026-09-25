// Sparse, coupled tensor-spline fitting for authoring. No Blender callbacks.
#pragma once
namespace af_base {
static double knot(int i,int n) { return i<4?0.0:(i>=n?1.0:double(i-3)/(n-3)); }
static double greville(int i,int n) { return (knot(i+1,n)+knot(i+2,n)+knot(i+3,n))/3; }
static double basis(int i,int d,double t,int n) {
    if(!d)return t>=knot(i,n)&&t<knot(i+1,n)?1.0:0.0;
    double a=knot(i+d,n)-knot(i,n),b=knot(i+d+1,n)-knot(i+1,n);
    return (a>0?(t-knot(i,n))/a*basis(i,d-1,t,n):0)+(b>0?(knot(i+d+1,n)-t)/b*basis(i+1,d-1,t,n):0);
}
static std::vector<double> row(double u,double v,int nu,int nv,int active=0) {
    std::vector<double> r(nu*nv);u=std::min(u,1.0-1e-13);v=std::min(v,1.0-1e-13);
    for(int i=0;i<nu;++i)for(int j=0;j<nv;++j)r[i*nv+j]=(active?(i<active?std::max(0.0,1-std::abs(u*(active-1)-i)):0):basis(i,3,u,nu))*basis(j,3,v,nv);
    return r;
}
static void term(std::vector<double>& a,std::vector<double>& b,int n,const std::vector<double>& r,const double* p,double w) {
    for(int i=0;i<n;++i)if(r[i]!=0){for(int j=0;j<n;++j)if(r[j]!=0)a[i*n+j]+=w*r[i]*r[j];
        for(int k=0;k<3;++k)b[i*3+k]+=w*r[i]*p[k];}
}
static void data(std::vector<double>& a,std::vector<double>& b,int n,const double* samples,int count,int nu,int nv,int parts,const int64_t* active) {
    for(int q=0;q<count;++q){const double* p=samples+7*q;int offset=int(p[0])*nu*nv;
        auto local=row(p[1],p[2],nu,nv,active?int(active[int(p[0])]):0);std::vector<double> r(n);
        for(int i=0;i<nu*nv;++i)r[offset+i]=local[i];term(a,b,n,r,p+3,p[6]);}
}
static void fair(std::vector<double>& a,std::vector<double>& b,int n,int nu,int nv,int parts,double weight,const int64_t* active) {
    double zero[3]={};
    for(int p=0;p<parts;++p)for(int u=0;u<(active?active[p]:nu);++u)for(int v=0;v<nv;++v)for(int axis=0;axis<2;++axis){
        if(axis?v+2>=nv:u+2>=(active?active[p]:nu))continue;int i=p*nu*nv+u*nv+v,step=axis?1:nv;
        int t=axis?v:u,size=axis?nv:nu;double x=(!axis&&active)?1.0:greville(t+1,size)-greville(t,size),y=(!axis&&active)?1.0:greville(t+2,size)-greville(t+1,size),s=(x+y)/2;
        std::vector<double> r(n);r[i]=s/x;r[i+step]=-s/x-s/y;r[i+2*step]=s/y;term(a,b,n,r,zero,weight);}
}
static void locks(std::vector<double>& c,std::vector<double>& d,int n,const double* pins,int count,int nu,int nv,const int64_t* active) {
    for(int p=0;p<count;++p){const double* pin=pins+6*p;auto r=row(pin[1],pin[2],nu,nv,active?int(active[int(pin[0])]):0);int offset=int(pin[0])*nu*nv;
        c.resize(c.size()+n);int start=int(c.size())-n;for(int i=0;i<nu*nv;++i)c[start+offset+i]=r[i];
        d.insert(d.end(),pin+3,pin+6);}
}
static void seams(std::vector<double>& a,std::vector<double>& b,std::vector<double>& c,std::vector<double>& d,int n,const int64_t* joins,int count,int nu,int nv,double strength,const int64_t* active) {
    const double zero[3]={};
    for(int s=0;s<count;++s){auto j=joins+4*s;int a0=int(j[0])*nu*nv+(j[1]?(active?int(active[j[0]]):nu)-1:0)*nv,a1=a0+(j[1]?-nv:nv);
        int b0=int(j[2])*nu*nv+(j[3]?(active?int(active[j[2]]):nu)-1:0)*nv,b1=b0+(j[3]?-nv:nv);
        for(int v=0;v<nv;++v){int start=int(c.size());c.resize(c.size()+n);c[start+a0+v]=1;c[start+b0+v]=-1;d.insert(d.end(),3,0);
            std::vector<double> r(n);r[a1+v]=1;r[b1+v]=1;r[a0+v]-=1;r[b0+v]-=1;term(a,b,n,r,zero,strength);}}
}
static void augment(std::vector<double>& a,std::vector<double>& b,const std::vector<double>& c,const std::vector<double>& d,int n) {
    int m=int(d.size()/3),size=n+m;std::vector<double> k(size*size),r(size*3);
    for(int i=0;i<n;++i){for(int j=0;j<n;++j)k[i*size+j]=a[i*n+j];for(int j=0;j<3;++j)r[i*3+j]=b[i*3+j];k[i*size+i]+=1e-12;}
    for(int i=0;i<m;++i){for(int j=0;j<n;++j)k[(n+i)*size+j]=k[j*size+n+i]=c[i*n+j];for(int j=0;j<3;++j)r[(n+i)*3+j]=d[i*3+j];}
    a.swap(k);b.swap(r);
}
static bool solve(std::vector<double> a,std::vector<double> b,std::vector<double>& x) {
    int n=int(b.size()/3),rank=0;std::vector<int> pivots;
    for(int col=0;col<n;++col){int p=rank;for(int i=rank;i<n;++i)if(std::abs(a[i*n+col])>std::abs(a[p*n+col]))p=i;
        if(std::abs(a[p*n+col])<1e-11)continue;
        for(int j=col;j<n;++j)std::swap(a[p*n+j],a[rank*n+j]);for(int j=0;j<3;++j)std::swap(b[p*3+j],b[rank*3+j]);
        double v=a[rank*n+col];for(int j=col;j<n;++j)a[rank*n+j]/=v;for(int j=0;j<3;++j)b[rank*3+j]/=v;
        for(int i=rank+1;i<n;++i){double w=a[i*n+col];for(int j=col;j<n;++j)a[i*n+j]-=w*a[rank*n+j];for(int j=0;j<3;++j)b[i*3+j]-=w*b[rank*3+j];}
        pivots.push_back(col);if(++rank==n)break;}
    for(int i=rank;i<n;++i)for(int j=0;j<3;++j)if(std::abs(b[i*3+j])>1e-7)return false;
    x.assign(n*3,0);for(int i=rank-1;i>=0;--i)for(int k=0;k<3;++k){double v=b[i*3+k];for(int j=pivots[i]+1;j<n;++j)v-=a[i*n+j]*x[j*3+k];x[pivots[i]*3+k]=v;}
    return true;
}
static bool finite(const double* p,int n) { if(!p)return n==0;for(int i=0;i<n;++i)if(!std::isfinite(p[i]))return false;return true; }
static bool samples_valid(const double* p,int count,int stride,int parts) {
    if(!finite(p,count*stride))return false;
    for(int i=0;i<count;++i){const double* q=p+i*stride;if(q[0]!=int(q[0])||q[0]<0||q[0]>=parts||q[1]<0||q[1]>1||q[2]<0||q[2]>1)return false;
        if(stride==7&&q[6]<=0)return false;}
    return true;
}
}
#include "af_base_order.hpp"
AF_EXPORT int af_base_spline_fit(const double* samples,int count,const double* pins,int pin_count,const int64_t* joins,int join_count,int parts,int nu,int nv,const int64_t* active,double fairness,double tangent,double* output) {
    using namespace af_base; if(parts<1||parts>8||nu<(active?2:4)||nu>8||nv<4||nv>8||count<4||count>40000||pin_count<0||pin_count>128||join_count<0||join_count>8||!output)return 1;
    if(!samples_valid(samples,count,7,parts)||!samples_valid(pins,pin_count,6,parts)||!std::isfinite(fairness)||fairness<=0||!std::isfinite(tangent)||tangent<0)return 1;
    if(join_count&&!joins)return 1;
    for(int i=0;i<join_count;++i){auto j=joins+4*i;if(j[0]<0||j[0]>=parts||j[2]<0||j[2]>=parts||j[0]==j[2]||j[1]<0||j[1]>1||j[3]<0||j[3]>1)return 1;}
    if(active)for(int p=0;p<parts;++p)if(active[p]<2||active[p]>nu)return 1;
    try{int n=parts*nu*nv;std::vector<double>a(n*n),b(n*3),c,d,x;data(a,b,n,samples,count,nu,nv,parts,active);fair(a,b,n,nu,nv,parts,fairness,active);
        locks(c,d,n,pins,pin_count,nu,nv,active);seams(a,b,c,d,n,joins,join_count,nu,nv,tangent,active);auto matrix=a,values=b;augment(matrix,values,c,d,n);
        if(!solve(matrix,values,x)||!finite(x.data(),n*3))return 2;
        if(active){auto limits=strip_order(samples,count,parts,nu,nv,active);seam_order(limits,samples,count,parts,nu,nv,active,joins,join_count);
            if(!ordered_solve(a,b,c,d,n,limits,x)||!finite(x.data(),n*3))return 4;}
        for(int i=0;i<int(d.size()/3);++i)for(int k=0;k<3;++k){double residual=-d[i*3+k];for(int j=0;j<n;++j)residual+=c[i*n+j]*x[j*3+k];if(std::abs(residual)>1e-6)return 2;}
        std::copy(x.begin(),x.begin()+n*3,output);return 0;
    }catch(...){return 3;}
}
AF_EXPORT int af_base_spline_eval(const double* controls,int nu,int nv,const double* uv,int count,int linear,double* output) {
    if(nu<(linear?2:4)||nu>8||nv<4||nv>8||count<1||count>40000||!output||!af_base::finite(controls,nu*nv*3)||!af_base::finite(uv,2*count))return 1;
    try{for(int p=0;p<count;++p){if(uv[2*p]<0||uv[2*p]>1||uv[2*p+1]<0||uv[2*p+1]>1)return 1;auto r=af_base::row(uv[2*p],uv[2*p+1],nu,nv,linear?nu:0);
        for(int k=0;k<3;++k){double v=0;for(int i=0;i<nu*nv;++i)v+=r[i]*controls[i*3+k];output[p*3+k]=v;}}
    return 0;}catch(...){return 3;}
}
AF_EXPORT int af_base_harmonic(const int64_t* edges,const double* weights,int edge_count,const int64_t* fixed,int count,double* uv) {
    if(count<4||count>8192||edge_count<1||edge_count>120000||!edges||!fixed||!af_base::finite(weights,edge_count)||!af_base::finite(uv,count*2))return 1;
    try{std::vector<std::vector<std::pair<int,double>>> rows(count);std::vector<double> degree(count);
    for(int e=0;e<edge_count;++e){int64_t a=edges[2*e],b=edges[2*e+1];if(a<0||a>=count||b<0||b>=count||weights[e]<=0)return 1;rows[a].push_back({int(b),weights[e]});degree[a]+=weights[e];}
    for(int i=0;i<count;++i)if(degree[i]<=0)return 1;
    for(int step=0;step<20000;++step){double error=0;
        for(int i=0;i<count;++i)if(!fixed[i])for(int axis=0;axis<2;++axis){double value=0;for(auto e:rows[i])value+=e.second*uv[2*e.first+axis]/degree[i];
            error=std::max(error,std::abs(value-uv[2*i+axis]));uv[2*i+axis]=value;}
        if(error<1e-11)return 0;}
    return 2;}catch(...){return 3;}
}

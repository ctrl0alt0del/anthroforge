// Local rigid shape matching with a symmetric Horn eigensolve.
#pragma once
#include <vector>
#include <cmath>
#include <algorithm>
#include <array>
#include <numeric>
namespace af_transfer_shape {
using P=std::array<double,3>;
static P add(P a,P b) { for(int i=0;i<3;++i)a[i]+=b[i];return a; }
static P sub(P a,P b) { for(int i=0;i<3;++i)a[i]-=b[i];return a; }
static P mul(P a,double b) { for(double&v:a)v*=b;return a; }
static double norm2(P a) { return a[0]*a[0]+a[1]*a[1]+a[2]*a[2]; }
struct Kd { int id,left=-1,right=-1,axis; };
struct Tree { std::vector<P> p;std::vector<int> order;std::vector<Kd> nodes; };
static int build(Tree&t,int lo,int hi,int depth) {
    if(lo>=hi)return -1;int axis=depth%3,mid=(lo+hi)/2;
    std::nth_element(t.order.begin()+lo,t.order.begin()+mid,t.order.begin()+hi,[&](int a,int b){return t.p[a][axis]<t.p[b][axis];});
    int n=(int)t.nodes.size();t.nodes.push_back({t.order[mid],-1,-1,axis});
    int l=build(t,lo,mid,depth+1),r=build(t,mid+1,hi,depth+1);t.nodes[n].left=l;t.nodes[n].right=r;return n;
}
static std::vector<P> unpack(int n,const double*x) {
    std::vector<P> p(n);for(int i=0;i<n;++i)for(int a=0;a<3;++a)p[i][a]=x[3*i+a];return p;
}
static void jacobi(double a[4][4],double v[4][4],int p,int q) {
    if(fabs(a[p][q])<1e-16)return;double angle=.5*atan2(2*a[p][q],a[q][q]-a[p][p]),c=cos(angle),s=sin(angle);
    double pp=a[p][p],qq=a[q][q],pq=a[p][q];a[p][p]=c*c*pp-2*c*s*pq+s*s*qq;a[q][q]=s*s*pp+2*c*s*pq+c*c*qq;a[p][q]=a[q][p]=0;
    for(int k=0;k<4;++k){if(k!=p&&k!=q){double ap=a[k][p],aq=a[k][q];a[k][p]=a[p][k]=c*ap-s*aq;a[k][q]=a[q][k]=s*ap+c*aq;}
        double vp=v[k][p],vq=v[k][q];v[k][p]=c*vp-s*vq;v[k][q]=s*vp+c*vq;}
}
static std::array<double,4> quaternion(double h[3][3]) {
    double a=h[0][0],b=h[0][1],c=h[0][2],d=h[1][0],e=h[1][1],f=h[1][2],g=h[2][0],j=h[2][1],k=h[2][2];
    double q[4][4]={{a+e+k,f-j,g-c,b-d},{f-j,a-e-k,b+d,c+g},{g-c,b+d,-a+e-k,f+j},{b-d,c+g,f+j,-a-e+k}},v[4][4]={};
    for(int i=0;i<4;++i)v[i][i]=1;
    for(int it=0;it<16;++it)for(int p=0;p<4;++p)for(int r=p+1;r<4;++r)jacobi(q,v,p,r);
    int id=0;for(int i=1;i<4;++i)if(q[i][i]>q[id][id])id=i;return {v[0][id],v[1][id],v[2][id],v[3][id]};
}
static P rotate(P v,std::array<double,4>q) {
    P u{q[1],q[2],q[3]};P cross{u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]};
    double dot=u[0]*v[0]+u[1]*v[1]+u[2]*v[2];return add(add(mul(u,2*dot),mul(v,q[0]*q[0]-norm2(u))),mul(cross,2*q[0]));
}
static void cluster(const std::vector<P>&rest,const std::vector<P>&x,const std::vector<int>&ids,std::vector<P>&goals,std::vector<int>&counts) {
    P c0{},c1{};for(int j:ids){c0=add(c0,rest[j]);c1=add(c1,x[j]);}c0=mul(c0,1.0/ids.size());c1=mul(c1,1.0/ids.size());
    double h[3][3]={};for(int j:ids){P a=sub(rest[j],c0),b=sub(x[j],c1);for(int m=0;m<3;++m)for(int n=0;n<3;++n)h[m][n]+=a[m]*b[n];}
    auto q=quaternion(h);for(int j:ids){goals[j]=add(goals[j],add(c1,rotate(sub(rest[j],c0),q)));counts[j]++;}
}

}

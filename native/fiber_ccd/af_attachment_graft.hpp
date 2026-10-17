// Ordered anatomical attachment envelope construction.
#pragma once
namespace af_graft {
using namespace af_transfer_shape;
static double dot(P a,P b){return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
static std::vector<P> chart(const std::vector<P>&v,P u,P w) {
    std::vector<P>r(v.size());P c=mean(v);double uv=0,uu=0,su=0,sv=0;
    for(size_t i=0;i<v.size();++i){P p=sub(v[i],c);r[i]={dot(p,u),dot(p,w),0};uv+=r[i][0]*r[i][1];uu+=r[i][0]*r[i][0];}
    for(P&p:r){p[1]-=p[0]*uv/std::max(uu,1e-20);su=std::max(su,std::abs(p[0]));sv=std::max(sv,std::abs(p[1]));}
    for(P&p:r){p[0]/=std::max(su,1e-20);p[1]/=std::max(sv,1e-20);}return r;
}
static double alignment(const std::vector<P>&a,const std::vector<P>&b,int shift,int sign) {
    P ca=mean(a),cb=mean(b);double cost=0;int n=(int)a.size();
    for(int i=0;i<n;++i){int j=(shift+sign*i+n*2)%n;cost+=norm2(sub(sub(a[i],ca),sub(b[j],cb)));}return cost;
}
static std::pair<int,int> correspondence(const std::vector<P>&a,const std::vector<P>&b) {
    double best=1e100;std::pair<int,int> result{0,1};int n=(int)a.size();
    for(int sign:{-1,1})for(int k=0;k<n;++k){double e=alignment(a,b,k,sign);if(e<best){best=e;result={k,sign};}}return result;
}
static P evaluate(P a,P b,P normal,double t,double escape) {
    P p1=add(a,mul(normal,escape)),p2=add(b,mul(sub(a,b),.22));double u=1-t;
    return add(add(mul(a,u*u*u),mul(p1,3*u*u*t)),add(mul(p2,3*u*t*t),mul(b,t*t*t)));
}
static void build(int count,int rings,const double*first,const double*second,const double*normals,const double*axes,double escape,double*out,int*order) {
    auto a=unpack(count,first),b=unpack(count,second),norm=unpack(count,normals),frame=unpack(4,axes);auto ca=chart(a,frame[0],frame[1]),cb=chart(b,frame[2],frame[3]);
    auto match=correspondence(ca,cb);order[0]=match.first;order[1]=match.second;
    for(int k=0;k<rings;++k){double t=double(k+1)/(rings+1);for(int i=0;i<count;++i){int j=(match.first+match.second*i+2*count)%count;
        double depth=escape*(.15+.85*std::clamp((ca[i][1]+1)*.5,0.,1.));P p=evaluate(a[i],b[j],norm[i],t,depth);for(int c=0;c<3;++c)out[(k*count+i)*3+c]=p[c];}}
}
}
AF_NATIVE_EXPORT int af_attachment_graft(int count,int rings,const double*a,const double*b,const double*normals,const double*axes,double escape,double*out,int*order) {
    try{if(count<3||count>1024||rings<1||rings>128||!a||!b||!normals||!axes||!out||!order||escape<0||!std::isfinite(escape))return 1;
        af_graft::build(count,rings,a,b,normals,axes,escape,out,order);return 0;}catch(...){return 2;}
}

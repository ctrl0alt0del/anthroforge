#pragma once
#include <igl/point_simplex_squared_distance.h>
#include <unsupported/Eigen/Polynomials>
namespace af_ad {
using P3=Eigen::Vector3d;
struct ContactRow { int ids[4]; double w[4]; P3 normal; int face=-1; };
struct ContactBox { P3 lo,hi; int face; };
inline P3 position(const M& a,const M& b,int i,double t) {return (a.row(i)+t*(b.row(i)-a.row(i))).transpose();}
inline P3 face_normal(const M& v,const I& f,int i) {
    P3 a=v.row(f(i,1))-v.row(f(i,0)),b=v.row(f(i,2))-v.row(f(i,0));P3 n=a.cross(b);
    return n.norm()>1e-15?P3(n.normalized()):P3::Zero();
}
inline double determinant(const M& a,const M& b,const int* ids,double t) {
    P3 p=position(a,b,ids[0],t),q=position(a,b,ids[1],t),r=position(a,b,ids[2],t),s=position(a,b,ids[3],t);
    return (q-p).cross(r-p).dot(s-p);
}
inline std::vector<double> contact_times(const M& a,const M& b,const int* ids) {
    double f0=determinant(a,b,ids,0),f1=determinant(a,b,ids,1),fm=determinant(a,b,ids,-1),f2=determinant(a,b,ids,2);
    double c2=(f1+fm)*.5-f0,d=(f1-fm)*.5,c3=(f2-f0-4*c2-2*d)/6,c1=d-c3;
    Eigen::VectorXd c(4);c<<f0,c1,c2,c3;int degree=3;double scale=c.cwiseAbs().maxCoeff();
    while(degree>0 && std::abs(c[degree])<=1e-13*std::max(scale,1e-30))--degree;
    std::vector<double> result{0.,1.};if(!degree)return result;
    Eigen::PolynomialSolver<double,Eigen::Dynamic> solver;solver.compute(c.head(degree+1));
    for(const auto& root:solver.roots())if(std::abs(root.imag())<1e-8 && root.real()>=0 && root.real()<=1)result.push_back(root.real());
    std::sort(result.begin(),result.end());return result;
}
inline bool shared(const I& f,int a,int b) {
    for(int i=0;i<3;++i)for(int j=0;j<3;++j)if(f(a,i)==f(b,j))return true;return false;
}
inline bool overlap(const ContactBox& a,const ContactBox& b) {
    return (a.lo.array()<=b.hi.array()).all() && (b.lo.array()<=a.hi.array()).all();
}
inline std::vector<ContactBox> swept_boxes(const M& a,const M& b,const I& f,double reach) {
    std::vector<ContactBox> boxes(f.rows());
    for(int i=0;i<f.rows();++i){auto& box=boxes[i];box.face=i;box.lo=P3::Constant(INFINITY);box.hi=-box.lo;
        for(int j=0;j<3;++j){P3 x=a.row(f(i,j)),y=b.row(f(i,j));box.lo=box.lo.cwiseMin(x).cwiseMin(y);box.hi=box.hi.cwiseMax(x).cwiseMax(y);}
        box.lo.array()-=reach;box.hi.array()+=reach;}
    std::sort(boxes.begin(),boxes.end(),[](const auto& x,const auto& y){return x.lo.x()<y.lo.x();});return boxes;
}
inline double separation(const ContactRow& row,const M& x) {
    P3 d=P3::Zero();for(int k=0;k<4;++k)d+=row.w[k]*x.row(row.ids[k]).transpose();return d.dot(row.normal);
}
inline ContactRow vertex_face(const M& a,const M& b,const I& f,int vertex,int face,double time) {
    M triangle(3,3);for(int k=0;k<3;++k)triangle.row(k)=position(a,b,f(face,k),time);
    Eigen::Matrix<int,1,3> face_ids;face_ids<<0,1,2;Eigen::RowVector3d closest,weights,p=position(a,b,vertex,time);
    double distance;igl::point_simplex_squared_distance<3>(p,triangle,face_ids,0,distance,closest,weights);
    ContactRow row{};row.ids[0]=vertex;row.w[0]=1;row.face=face;
    for(int k=0;k<3;++k){row.ids[k+1]=f(face,k);row.w[k+1]=-weights[k];}
    P3 u=triangle.row(1)-triangle.row(0),v=triangle.row(2)-triangle.row(0);row.normal=u.cross(v).normalized();return row;
}
inline double row_distance(const ContactRow& row,const M& a,const M& b,double t) {
    P3 delta=P3::Zero();for(int k=0;k<4;++k)delta+=row.w[k]*position(a,b,row.ids[k],t);return delta.norm();
}
inline bool orient_row(ContactRow& row,const M& start,const M& reference,P3 normal,double tolerance) {
    if(!row.normal.allFinite())return false;
    double gap=separation(row,start);if(std::abs(gap)<=tolerance){P3 delta=P3::Zero();
        for(int k=0;k<4;++k)delta+=row.w[k]*reference.row(row.ids[k]).transpose();gap=delta.dot(normal);}
    if(gap<0)row.normal=-row.normal;return true;
}
inline void vertex_events(const M& a,const M& b,const M& reference,const I& f,int vertex,int face,double tolerance,std::vector<ContactRow>& out) {
    int ids[4]={vertex,f(face,0),f(face,1),f(face,2)};
    for(double t:contact_times(a,b,ids)) {
        ContactRow row=vertex_face(a,b,f,vertex,face,t);
        if(row_distance(row,a,b,t)>tolerance || !orient_row(row,a,reference,face_normal(reference,f,face),tolerance))continue;
        if(separation(row,b)<-tolerance){out.push_back(row);return;}
    }
}
inline Eigen::Vector2d edge_parameters(P3 p,P3 q,P3 r,P3 s) {
    P3 u=q-p,v=s-r,w=p-r;double aa=u.dot(u),bb=u.dot(v),cc=v.dot(v),dd=u.dot(w),ee=v.dot(w),den=aa*cc-bb*bb;
    double x=den>1e-25?std::clamp((bb*ee-cc*dd)/den,0.,1.):0.;
    double y=cc>1e-25?std::clamp((bb*x+ee)/cc,0.,1.):0.;
    if(aa>1e-25)x=std::clamp((bb*y-dd)/aa,0.,1.);return {x,y};
}
inline ContactRow edge_row(const M& a,const M& b,const int* ids,double time,P3 fallback) {
    P3 p=position(a,b,ids[0],time),q=position(a,b,ids[1],time),r=position(a,b,ids[2],time),s=position(a,b,ids[3],time);
    auto uv=edge_parameters(p,q,r,s);ContactRow row{};std::copy(ids,ids+4,row.ids);
    row.w[0]=1-uv[0];row.w[1]=uv[0];row.w[2]=uv[1]-1;row.w[3]=-uv[1];
    P3 n=(q-p).cross(s-r);row.normal=n.norm()>1e-14?P3(n.normalized()):fallback;return row;
}
inline void edge_events(const M& a,const M& b,const M& reference,const I& f,int fa,int fb,double tolerance,std::vector<ContactRow>& out) {
    for(int i=0;i<3;++i)for(int j=0;j<3;++j){int ids[4]={f(fa,i),f(fa,(i+1)%3),f(fb,j),f(fb,(j+1)%3)};
        for(double t:contact_times(a,b,ids)){auto row=edge_row(a,b,ids,t,face_normal(a,f,fb));
            auto prior=edge_row(reference,reference,ids,0,face_normal(reference,f,fb));
            if(row_distance(row,a,b,t)>tolerance || !orient_row(row,a,reference,prior.normal,tolerance))continue;
            if(separation(row,b)<-tolerance){out.push_back(row);break;}}}
}
}

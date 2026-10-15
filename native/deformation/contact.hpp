#pragma once
#include "contact_geometry.hpp"
namespace af_ad {
struct ContactTask {
    M reference,start,x; I faces; Eigen::VectorXi symmetry;P3 origin,normal;std::vector<ContactRow> rows;
    std::string cancel;uint64_t budget;double tolerance,reach;int tested=0,passes=0,limited=0;
    std::chrono::steady_clock::time_point started=std::chrono::steady_clock::now();
};
inline void contact_check(ContactTask& s) {
    if(!s.cancel.empty() && std::filesystem::exists(s.cancel))throw std::runtime_error("CANCELLED");
    if(std::chrono::duration<double>(std::chrono::steady_clock::now()-s.started).count()>60)s.limited=1;
    if(s.rows.size()*sizeof(ContactRow)>s.budget/4)s.limited=1;
}
inline void contact_pair(ContactTask& s,int a,int b) {
    if(shared(s.faces,a,b))return; ++s.tested;
    for(int k=0;k<3;++k){vertex_events(s.start,s.x,s.reference,s.faces,s.faces(a,k),b,s.tolerance,s.rows);
        vertex_events(s.start,s.x,s.reference,s.faces,s.faces(b,k),a,s.tolerance,s.rows);}
    edge_events(s.start,s.x,s.reference,s.faces,a,b,s.tolerance,s.rows);
}
inline void refresh_contacts(ContactTask& s) {
    if(s.limited)return;
    auto boxes=swept_boxes(s.start,s.x,s.faces,s.reach);s.rows.clear();
    for(size_t a=0;a<boxes.size() && !s.limited;++a){contact_check(s);
        for(size_t b=a+1;b<boxes.size() && boxes[b].lo.x()<=boxes[a].hi.x();++b){
            if(overlap(boxes[a],boxes[b]))contact_pair(s,boxes[a].face,boxes[b].face);
            if((b%256)==0){contact_check(s);if(s.limited)break;}}}
}
inline double symmetry_project(ContactTask& s) {
    double change=0; if(s.normal.norm()<.5)return 0;R3 reflect=R3::Identity()-2*s.normal*s.normal.transpose();
    for(int i=0;i<s.x.rows();++i){int j=s.symmetry[i];if(j<0||j<i)continue;
        P3 a=s.x.row(i),b=s.x.row(j),next=(a+s.origin+reflect*(b-s.origin))*.5;
        change=std::max(change,(next-a).norm());s.x.row(i)=next;s.x.row(j)=s.origin+reflect*(next-s.origin);}
    return change;
}
inline double project_contact(ContactTask& s,const ContactRow& row) {
    double gap=separation(row,s.x);if(gap>=-s.tolerance)return 0;double denom=0;
    for(double w:row.w)denom+=w*w;if(denom<=1e-15)return 0;
    for(int k=0;k<4;++k)s.x.row(row.ids[k])+=(-gap/denom*row.w[k]*row.normal).transpose();return -gap;
}
inline void contact_solve(ContactTask& s,double* stats) {
    double maximum=0;for(int pass=0;pass<4;++pass){contact_check(s);if(s.limited)break;
        symmetry_project(s);refresh_contacts(s);maximum=0;
        for(int sweep=0;sweep<32;++sweep){contact_check(s);if(s.limited)break;double delta=symmetry_project(s);
            for(const auto& row:s.rows)delta=std::max(delta,project_contact(s,row));maximum=std::max(maximum,delta);
            if(delta<=s.tolerance)break;}
        s.passes=pass+1;if(s.rows.empty()||maximum<=s.tolerance)break;}
    refresh_contacts(s);stats[0]=0;for(const auto& r:s.rows)stats[0]+=separation(r,s.x)<-s.tolerance;
    stats[1]=s.tested;stats[2]=s.passes;stats[3]=s.limited;
    stats[4]=0;for(const auto& row:s.rows)stats[4]=std::max(stats[4],-separation(row,s.x));
    stats[5]=(s.x-s.start).rowwise().norm().maxCoeff();stats[6]=1; // Edge-edge/coplanar CCD coverage reported separately.
    stats[7]=0;for(int i=0;i<s.x.rows();++i)if(s.symmetry[i]>=0){P3 p=s.x.row(i),q=s.x.row(s.symmetry[i]);
        stats[7]=std::max(stats[7],(p-2*s.normal*s.normal.dot(p-s.origin)-q).norm());}
}
inline void validate_published_motion(ContactTask& s,const M& published,double* stats) {
    if((published-s.reference).cwiseAbs().maxCoeff()<=s.tolerance){stats[5]=stats[0];return;}
    if(s.limited){stats[5]=-1;return;}s.start=published;refresh_contacts(s);
    stats[5]=s.limited?-1:0;
    if(!s.limited)for(const auto& row:s.rows)stats[5]+=separation(row,s.x)<-s.tolerance;
    stats[3]=s.limited;
}
API int af_ad_contact(const double* reference,const double* current,const double* proposed,int count,const int* faces,int nf,
    const int* symmetry,const double* plane,uint64_t budget,const char* cancel,double* output,double* stats) {
    try{ContactTask s;s.reference=Eigen::Map<const RM>(reference,count,3);s.start=s.reference;M published=Eigen::Map<const RM>(current,count,3);
        s.x=Eigen::Map<const RM>(proposed,count,3);s.faces=Eigen::Map<const RI>(faces,nf,3);s.symmetry=Eigen::Map<const Eigen::VectorXi>(symmetry,count);
        s.origin=Eigen::Map<const P3>(plane);s.normal=Eigen::Map<const P3>(plane+3);s.budget=budget;s.cancel=cancel?cancel:"";
        double scale=(s.reference.colwise().maxCoeff()-s.reference.colwise().minCoeff()).norm();s.tolerance=std::max(scale*1e-9,1e-12);s.reach=10*s.tolerance;
        if(uint64_t(count)*128+uint64_t(nf)*128>budget)throw std::runtime_error("CONTACT_MEMORY_LIMIT");
        contact_solve(s,stats);validate_published_motion(s,published,stats);Eigen::Map<RM>(output,count,3)=s.x;return 1;
    }catch(const std::exception& e){error=e.what();return 0;}
}
API int af_ad_symmetry(const double* vertices,int count,const double* plane,int* partners,double* maximum) {
    try{M v=Eigen::Map<const RM>(vertices,count,3);P3 o=Eigen::Map<const P3>(plane),n=Eigen::Map<const P3>(plane+3);*maximum=0;
        for(int i=0;i<count;++i){P3 p=v.row(i);p-=2*n*n.dot(p-o);double best=INFINITY;int found=-1;
            for(int j=0;j<count;++j){double d=(v.row(j).transpose()-p).squaredNorm();if(d<best){best=d;found=j;}}
            partners[i]=found;*maximum=std::max(*maximum,std::sqrt(best));}
        for(int i=0;i<count;++i)if(partners[partners[i]]!=i)partners[i]=-1;return 1;
    }catch(const std::exception& e){error=e.what();return 0;}
}
}

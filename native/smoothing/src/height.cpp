#include "af_smoothing/model.hpp"
#include "af_smoothing/height.h"
#include <Eigen/Geometry>
#include <map>
#include <array>
#include <cstdio>
#include <algorithm>

namespace afh {
using namespace afs;
using Matrix = Eigen::Matrix<double,Eigen::Dynamic,3,Eigen::RowMajor>;
struct Domain {
    Mesh mesh;
    std::vector<int> ids;
    std::vector<std::array<int,3>> triangles;
    std::vector<bool> fixed;
    int skipped=0;
};
static void append(Domain& d,const Matrix& b,int a,int c,int e,double threshold) {
    Eigen::Vector3d u=b.row(c)-b.row(a),v=b.row(e)-b.row(a);
    if (u.cross(v).norm()<=threshold) { ++d.skipped; return; }
    d.triangles.push_back({a,c,e});
}
static Domain triangles(const Matrix& b,const int64_t* f,int n,int cols,const int64_t* parts,int part) {
    Domain d;
    double extent=(b.colwise().maxCoeff()-b.colwise().minCoeff()).norm();
    require(std::isfinite(extent) && extent>0,"Invalid material extent");
    for (int i=0;i<n;++i) {
        for (int k=0;k<cols;++k) require(f[i*cols+k]>=0 && f[i*cols+k]<b.rows(),"Face index out of range");
        if (parts && parts[i]!=part) continue;
        append(d,b,int(f[i*cols]),int(f[i*cols+1]),int(f[i*cols+2]),extent*extent*1e-12);
        if(cols==4) append(d,b,int(f[i*cols]),int(f[i*cols+2]),int(f[i*cols+3]),extent*extent*1e-12);
    }
    return d;
}
static void compact(Domain& d,const Matrix& b) {
    std::map<int,int> ids;
    for (auto t:d.triangles) for (int i:t) ids.emplace(i,0);
    for (auto& item:ids) { item.second=int(d.ids.size()); d.ids.push_back(item.first); }
    d.mesh.vertices.resize(ids.size(),3); d.mesh.faces.resize(d.triangles.size(),3);
    for (auto item:ids) d.mesh.vertices.row(item.second)=b.row(item.first);
    for (int i=0;i<int(d.triangles.size());++i)
        for (int k=0;k<3;++k) d.mesh.faces(i,k)=ids.at(d.triangles[i][k]);
    d.fixed.assign(ids.size(),false);
}
static void boundaries(Domain& d) {
    std::map<std::pair<int,int>,int> edges;
    for (int i=0;i<d.mesh.faces.rows();++i) for (int k=0;k<3;++k)
        ++edges[std::minmax(d.mesh.faces(i,k),d.mesh.faces(i,(k+1)%3))];
    for(auto item:edges) if(item.second==1) d.fixed[item.first.first]=d.fixed[item.first.second]=true;
}
static Field field(Domain& d,const Matrix& b,const Matrix& x,double radius,double strength,double change) {
    Field f; f.radius=radius; f.strength=strength; f.target.resize(d.ids.size());
    for (int i=0;i<int(d.ids.size());++i) f.target[i]=(x.row(d.ids[i])-b.row(d.ids[i])).norm();
    f.lower=(f.target.array()-change).max(0); f.upper=(f.target.array()+change).min(f.target.maxCoeff());
    for (int i=0;i<f.target.size();++i) {
        d.fixed[i]=d.fixed[i] || f.target[i]==0;
        if(d.fixed[i]) f.lower[i]=f.upper[i]=f.target[i];
    }
    return f;
}
static Eigen::Vector3d normal(const Matrix& x,const std::array<int,3>& t) {
    Eigen::Vector3d a=x.row(t[1])-x.row(t[0]),b=x.row(t[2])-x.row(t[0]);
    return a.cross(b);
}
static void verify(const Domain& d,const Matrix& own,const Matrix& out) {
    for (auto t:d.triangles) {
        auto before=normal(own,t),after=normal(out,t);
        if(before.squaredNorm()>1e-28)
            require(after.norm()>before.norm()*1e-8 && before.dot(after)>0,"Smoothing would collapse or reverse an existing face");
    }
}
static Matrix displace(const Domain& d,const Matrix& base,const Matrix& own,const Field& f,const Vector& h) {
    Matrix out=own;
    for (int i=0;i<int(d.ids.size());++i) if(!d.fixed[i]) {
        int j=d.ids[i];
        out.row(j)=base.row(j)+(own.row(j)-base.row(j))*(h[i]/f.target[i]);
    }
    verify(d,own,out); return out;
}
static void metrics(AF_HeightReport& r,const Result& result) {
    const auto& m=result.metrics;
    r.iterations=m.iterations; r.solve_ms=m.solve_ms; r.violation=m.violation;
    r.stationarity=m.stationarity; r.complementarity=m.complementarity;
    r.complementarity_relative=m.complementarity_relative; r.objective=m.objective;
    r.status=int(result.status); std::snprintf(r.message,sizeof(r.message),"%s",result.message.c_str());
}
static Matrix solve(Domain& d,const Matrix& b,const Matrix& x,Field& f,AF_HeightReport& report) {
    CotangentBiharmonic builder; NoSupport source;
    Session session(d.mesh,builder,make_piqp(),Options{});
    auto r=session.run(f,source); metrics(report,r);
    if(r.status!=Status::success) throw std::runtime_error(r.message);
    report.max_change=max_abs(r.values-f.target);
    return displace(d,b,x,f,r.values);
}
static Matrix evaluate(Domain& d,const Matrix& b,const Matrix& x,double radius,double strength,double change,AF_HeightReport& r) {
    require(!d.triangles.empty(),"No usable material triangles");
    compact(d,b); boundaries(d);
    auto f=field(d,b,x,radius,strength,change);
    validate_field(f,int(d.ids.size()));
    r.samples=int(d.ids.size()); r.pinned=int(std::count(d.fixed.begin(),d.fixed.end(),true));
    r.skipped_triangles=d.skipped;
    if(r.pinned==r.samples || radius==0 || strength==0 || change==0) return x;
    return solve(d,b,x,f,r);
}
}

int af_height_version() { return 1; }
int af_height_smooth(const double* base,const double* own,int count,const int64_t* faces,int nf,int cols,
    const int64_t* parts,int part,double radius,double strength,double change,double* output,AF_HeightReport* report) {
    if(!report) return 1;
    *report={}; const double start=afs::now_ms();
    try {
        afs::require(base && own && faces && output && count>=3 && nf>0 && (cols==3 || cols==4),"Invalid smoothing buffers");
        afs::require(std::isfinite(change) && change>=0,"Invalid maximum change");
        afh::Matrix b=Eigen::Map<const afh::Matrix>(base,count,3),x=Eigen::Map<const afh::Matrix>(own,count,3);
        afs::require(b.allFinite() && x.allFinite(),"Nonfinite material snapshots");
        auto d=afh::triangles(b,faces,nf,cols,parts,part); auto result=afh::evaluate(d,b,x,radius,strength,change,*report);
        std::copy(result.data(),result.data()+count*3,output);
    } catch(const std::exception& e) { if(!report->status) report->status=1; std::snprintf(report->message,sizeof(report->message),"%s",e.what()); }
    report->total_ms=afs::now_ms()-start; return report->status;
}

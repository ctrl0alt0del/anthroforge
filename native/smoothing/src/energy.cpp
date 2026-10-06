#include "af_smoothing/model.hpp"
#include <igl/cotmatrix.h>
#include <igl/massmatrix.h>
#include <map>
#include <set>
#include <array>

namespace afs {
static void validate_faces(const Mesh& m, double scale) {
    std::set<std::array<int,3>> unique;
    for (int i=0;i<m.faces.rows();++i) {
        std::array<int,3> ids{m.faces(i,0),m.faces(i,1),m.faces(i,2)};
        require(*std::min_element(ids.begin(),ids.end())>=0 && *std::max_element(ids.begin(),ids.end())<m.vertices.rows(),"Face index out of range");
        Eigen::Vector3d a=m.vertices.row(ids[1])-m.vertices.row(ids[0]), b=m.vertices.row(ids[2])-m.vertices.row(ids[0]);
        require(a.cross(b).norm()>scale*scale*1e-12,"Degenerate or excessively thin triangle");
        std::sort(ids.begin(),ids.end());
        require(unique.insert(ids).second,"Duplicate triangle");
    }
}
static void validate_edges(const Mesh& m) {
    std::map<std::pair<int,int>,std::pair<int,int>> edges;
    std::vector<int> used(m.vertices.rows());
    for (int i=0;i<m.faces.rows();++i) for (int k=0;k<3;++k) {
        int a=m.faces(i,k), b=m.faces(i,(k+1)%3); used[a]=1;
        auto& e=edges[std::minmax(a,b)]; e.first++; e.second+=(a<b?1:-1);
    }
    for (auto e:edges) require(e.second.first<=2 && (e.second.first==1 || e.second.second==0),"Nonmanifold edge or inconsistent orientation");
    for (int value:used) require(value!=0,"Isolated vertex");
}
void validate_mesh(const Mesh& m) {
    require(m.vertices.cols()==3 && m.faces.cols()==3,"Mesh arrays must have three columns");
    require(m.vertices.rows()>=3 && m.faces.rows()>0,"Empty mesh");
    require(m.vertices.allFinite(),"Nonfinite mesh coordinates");
    double scale=(m.vertices.colwise().maxCoeff()-m.vertices.colwise().minCoeff()).norm();
    require(std::isfinite(scale) && scale>0,"Zero or nonfinite mesh extent");
    validate_faces(m,scale);
    validate_edges(m);
}
void validate_field(const Field& f, int n) {
    require(f.target.size()==n && f.lower.size()==n && f.upper.size()==n,"Field length mismatch");
    require(f.target.allFinite() && f.lower.allFinite() && f.upper.allFinite(),"Nonfinite field or bounds");
    require((f.lower.array()<=f.upper.array()).all(),"Inverted bounds");
    require(std::isfinite(f.radius) && f.radius>=0 && std::isfinite(f.strength) && f.strength>=0,"Invalid smoothing parameters");
    require(std::isfinite(f.strength*std::pow(f.radius,4)),"Smoothing weight overflow");
}
void validate_options(const Options& o) {
    require(std::isfinite(o.tolerance) && o.tolerance>=1e-10 && o.tolerance<=1e-3,"Invalid tolerance");
    require(o.max_iterations>0 && o.max_rounds>0,"Invalid iteration budget");
}
Energy CotangentBiharmonic::build(const Mesh& m) const {
    validate_mesh(m);
    Sparse L,M,inverse; igl::cotmatrix(m.vertices,m.faces,L);
    igl::massmatrix(m.vertices,m.faces,igl::MASSMATRIX_TYPE_BARYCENTRIC,M);
    Energy e; e.mass=M.diagonal();
    require(e.mass.allFinite() && e.mass.minCoeff()>0,"Invalid vertex mass");
    inverse.resize(M.rows(),M.cols()); inverse.setIdentity();
    inverse.diagonal()=e.mass.cwiseInverse();
    e.curvature=L.transpose()*inverse*L;
    e.curvature=.5*(e.curvature+Sparse(e.curvature.transpose()));
    e.curvature.makeCompressed(); return e;
}
}

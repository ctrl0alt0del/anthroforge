#pragma once
#include <Eigen/SparseCholesky>
#include <Eigen/SVD>
#include <chrono>
#include <filesystem>
#include <queue>
#include <set>
#include <stdexcept>
namespace af_ad {
using M=Eigen::MatrixXd; using I=Eigen::MatrixXi; using V=Eigen::VectorXd;
using S=Eigen::SparseMatrix<double>; using T=Eigen::Triplet<double>; using R3=Eigen::Matrix3d;
using RM=Eigen::Matrix<double,Eigen::Dynamic,Eigen::Dynamic,Eigen::RowMajor>;
using RI=Eigen::Matrix<int,Eigen::Dynamic,Eigen::Dynamic,Eigen::RowMajor>;
struct Element { R3 inverse; Eigen::Matrix<double,4,3> g; double volume; };
struct State {
    M rest, points, samples, weights, basis, controls; I tets,boundary; Eigen::VectorXi owners,handles,groups;
    std::vector<Element> elements; S skin, constraints, weighted, block, stiffness, lbs, reduced_constraints;
    Eigen::SimplicialLDLT<S> factor; Eigen::LDLT<M> reduced_factor;
    igl::ArapDOFData<S,double> fast; M reduced_hessian;
    V sample_weights, identity; int method=0, iterations=0; double lambda=10, residual=0, minimum_j=1;
    double max_outside=0; int outside=0; std::string cancel; uint64_t budget=8ULL<<30;
    std::chrono::steady_clock::time_point started; std::vector<std::vector<std::pair<int,double>>> edges;
};
inline void check(const State& s) {
    if(!s.cancel.empty() && std::filesystem::exists(s.cancel))throw std::runtime_error("CANCELLED");
    if(std::chrono::duration<double>(std::chrono::steady_clock::now()-s.started).count()>600)
        throw std::runtime_error("WORKER_TIMEOUT");
}
inline R3 frame(const M& p,const I& t,int e) {
    R3 result; for(int j=0;j<3;++j)result.col(j)=(p.row(t(e,j+1))-p.row(t(e,0))).transpose(); return result;
}
inline R3 rotation(const R3& f) {
    Eigen::JacobiSVD<R3> svd(f,Eigen::ComputeFullU|Eigen::ComputeFullV);
    R3 d=R3::Identity(); d(2,2)=(svd.matrixU()*svd.matrixV().transpose()).determinant();
    return svd.matrixU()*d*svd.matrixV().transpose();
}
inline V vector(const M& p) { return Eigen::Map<const V>(p.data(),p.size()); }
inline M matrix(const V& v,int n) { return Eigen::Map<const M>(v.data(),n,3); }
inline S blocks(const S& a) {
    std::vector<T> triplets;
    for(int d=0;d<3;++d)for(int j=0;j<a.outerSize();++j)for(S::InnerIterator it(a,j);it;++it)
        triplets.emplace_back(d*a.rows()+it.row(),d*a.cols()+it.col(),it.value());
    S result(3*a.rows(),3*a.cols()); result.setFromTriplets(triplets.begin(),triplets.end()); return result;
}
inline void elements(State& s) {
    s.elements.resize(s.tets.rows());
    for(int i=0;i<s.tets.rows();++i) {
        R3 dm=frame(s.rest,s.tets,i); if(dm.determinant()<0){std::swap(s.tets(i,1),s.tets(i,2));dm=frame(s.rest,s.tets,i);}
        if(dm.determinant()<=1e-18)throw std::runtime_error("INVALID_PROXY_TET");
        auto& e=s.elements[i]; e.inverse=dm.inverse(); e.volume=dm.determinant()/6;
        e.g.bottomRows<3>()=e.inverse; e.g.row(0)=-e.g.bottomRows<3>().colwise().sum();
    }
}
inline S embedding(State& s,const M& points) {
    igl::AABB<M,3> tree,bounds; tree.init(s.rest,s.tets); bounds.init(s.rest,s.boundary);
    Eigen::VectorXi ids; igl::in_element(s.rest,s.tets,points,tree,ids); std::vector<T> rows;
    for(int i=0;i<points.rows();++i) {
        int e=ids[i]; if(e<0) { int f; Eigen::RowVector3d nearest;
            double d=bounds.squared_distance(s.rest,s.boundary,points.row(i).eval(),f,nearest);
            e=s.owners[f]; s.outside++; s.max_outside=std::max(s.max_outside,std::sqrt(d)); }
        Eigen::Vector3d b=s.elements[e].inverse*(points.row(i)-s.rest.row(s.tets(e,0))).transpose();
        rows.emplace_back(i,s.tets(e,0),1-b.sum());
        for(int j=0;j<3;++j)rows.emplace_back(i,s.tets(e,j+1),b[j]);
    }
    S result(points.rows(),s.rest.rows()); result.setFromTriplets(rows.begin(),rows.end()); return result;
}
inline void common(State& s) {
    elements(s); Eigen::VectorXi corners; igl::boundary_facets(s.tets,s.boundary,s.owners,corners);
    s.skin=embedding(s,s.points); s.constraints=embedding(s,s.samples);
    s.weighted=s.sample_weights.cwiseSqrt().asDiagonal()*s.constraints; s.block=blocks(s.weighted);
}
}

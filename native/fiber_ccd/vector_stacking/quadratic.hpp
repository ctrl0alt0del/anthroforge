#pragma once
namespace af_stack_vector {
using Terms=std::vector<std::pair<int,double>>;
struct LinearRows { std::vector<afs::Triplet> a,g;std::vector<double> b,lower,upper;std::map<Terms,double> equalities; };
static void linear_row(LinearRows& rows,const Terms& terms,double lower,double upper) {
    if(lower==upper){auto inserted=rows.equalities.emplace(terms,lower);
        if(!inserted.second){require(inserted.first->second==lower,"STACK_VECTOR_CONFLICTING_EQUALITIES");return;}
        for(auto [j,v]:terms)rows.a.emplace_back(rows.b.size(),j,v);rows.b.push_back(lower);}
    else{for(auto [j,v]:terms)rows.g.emplace_back(rows.lower.size(),j,v);rows.lower.push_back(lower);rows.upper.push_back(upper);}
}
static void bounds(LinearRows& rows,const Layout& l,const Mat& raw,const Locality& local,const VectorSettings& settings) {
    double outside=std::min(settings.adjustment,raw.rowwise().norm().maxCoeff());
    for(int i=0;i<l.sample_rows.rows();++i){Terms terms;
        for(Eigen::SparseMatrix<double,Eigen::RowMajor>::InnerIterator t(l.sample_rows,i);t;++t)terms.emplace_back(t.col(),t.value());
        double cap=local.falloff[i/3]<1?outside*local.falloff[i/3]:settings.adjustment;
        linear_row(rows,terms,raw(i/3,i%3)-cap,raw(i/3,i%3)+cap);}
}
static void exact_rows(LinearRows& rows,const afs::Sparse& matrix) {
    Eigen::SparseMatrix<double,Eigen::RowMajor> c=matrix;
    for(int i=0;i<c.rows();++i){Terms terms;for(decltype(c)::InnerIterator t(c,i);t;++t)if(t.value()!=0)terms.emplace_back(t.col(),t.value());
        if(!terms.empty())linear_row(rows,terms,0,0);}
}
static void linear_matrices(afs::Quadratic& qp,const LinearRows& rows,int columns) {
    qp.A.resize(rows.b.size(),columns);qp.A.setFromTriplets(rows.a.begin(),rows.a.end());
    qp.G.resize(rows.lower.size(),columns);qp.G.setFromTriplets(rows.g.begin(),rows.g.end());
    qp.b=Eigen::Map<const afs::Vector>(rows.b.data(),rows.b.size());
    qp.lower=Eigen::Map<const afs::Vector>(rows.lower.data(),rows.lower.size());qp.upper=Eigen::Map<const afs::Vector>(rows.upper.data(),rows.upper.size());
}
static afs::Quadratic objective(const Layout& l,const afs::Energy& e,const Locality& local,const Mat& raw,const af_layer::Settings& settings) {
    afs::Quadratic qp;afs::Vector mass=e.mass.array()*local.weight.array();afs::Sparse h=e.curvature*(settings.strength*std::pow(settings.radius,4));
    for(int i=0;i<mass.size();++i)h.coeffRef(i,i)+=mass[i];double scale=mass.size()/mass.sum();
    auto energy=vectorize(h);afs::Vector linear(3*mass.size());
    for(int i=0;i<raw.rows();++i)for(int c=0;c<3;++c)linear[3*i+c]=mass[i]*raw(i,c);
    qp.P=scale*(l.sample.transpose()*energy*l.sample);qp.P.makeCompressed();qp.q=-scale*(l.sample.transpose()*linear);return qp;
}
static afs::Quadratic quadratic(const Layout& l,const afs::Energy& e,const Locality& local,const Mat& raw,const std::vector<afs::Row>& support,const State& state) {
    auto qp=objective(l,e,local,raw,state.settings);LinearRows rows;bounds(rows,l,raw,local,state.vector_settings);exact_rows(rows,l.constraints);
    for(const auto& row:support)linear_row(rows,row.terms,row.lower,INFINITY);linear_matrices(qp,rows,int(l.sample.cols()));return qp;
}
static afs::Solution solve(const afs::Quadratic& qp,double* metrics) {
    auto solver=afs::make_piqp();afs::Options options;options.robust_linear_solve=true;afs::Diagnostics diagnostics;
    auto out=solver->solve(qp,options,diagnostics);metrics[6]=diagnostics.setup_ms+diagnostics.solve_ms;
    require(out.status==afs::QpStatus::solved,"STACK_VECTOR_QP_FAILED");
    require(afs::certify(qp,out,options.tolerance,diagnostics),"STACK_VECTOR_QP_CERTIFICATION_FAILED");metrics[7]=diagnostics.violation;return out;
}
}

#include "af_smoothing/model.hpp"
namespace afs {
static Sparse matrix(int rows,int columns,const std::vector<Triplet>& entries) {
    Sparse m(rows,columns); m.setFromTriplets(entries.begin(),entries.end());
    m.makeCompressed(); return m;
}
static void objective(Quadratic& p,const Energy& e,const Field& f) {
    double scale=e.mass.size()/e.mass.sum();
    p.P=e.curvature*(f.strength*std::pow(f.radius,4));
    for (int i=0;i<e.mass.size();++i) p.P.coeffRef(i,i)+=e.mass[i];
    p.P*=scale; p.P.makeCompressed();
    p.q=-scale*(e.mass.array()*f.target.array()).matrix();
    require(p.q.allFinite(),"Objective overflow");
    for (int i=0;i<p.P.nonZeros();++i) require(std::isfinite(p.P.valuePtr()[i]),"Objective matrix overflow");
}
static void boundaries(Quadratic& p,const Field& f,std::vector<Triplet>& a,std::vector<Triplet>& g) {
    int equal=0,unequal=0;
    for (int i=0;i<f.target.size();++i) {
        if (f.lower[i]==f.upper[i]) { a.emplace_back(equal,i,1); p.b[equal++]=f.lower[i]; }
        else { g.emplace_back(unequal,i,1); p.lower[unequal]=f.lower[i]; p.upper[unequal++]=f.upper[i]; }
    }
}
static void support(Quadratic& p,const std::vector<Row>& rows,int start,std::vector<Triplet>& g) {
    for (int k=0;k<int(rows.size());++k) {
        require(std::isfinite(rows[k].lower),"Nonfinite support bound");
        p.lower[start+k]=rows[k].lower; p.upper[start+k]=std::numeric_limits<double>::infinity();
        for (auto t:rows[k].terms) {
            require(t.first>=0 && t.first<p.q.size() && std::isfinite(t.second),"Invalid support coefficient");
            g.emplace_back(start+k,t.first,t.second);
        }
    }
}
Quadratic assemble(const Energy& e,const Field& f,const std::vector<Row>& rows) {
    validate_field(f,int(e.mass.size())); Quadratic p; objective(p,e,f);
    int n=int(f.target.size()), equal=int((f.lower.array()==f.upper.array()).count());
    p.b.resize(equal); p.lower.resize(n-equal+rows.size()); p.upper.resize(p.lower.size());
    std::vector<Triplet> a,g; boundaries(p,f,a,g); support(p,rows,n-equal,g);
    p.A=matrix(equal,n,a); p.G=matrix(int(p.lower.size()),n,g); return p;
}
double support_violation(const std::vector<Row>& rows,const Vector& x) {
    double error=0;
    for (const auto& r:rows) {
        require(std::isfinite(r.lower),"Invalid remapped support bound"); double sum=0;
        for (auto t:r.terms) {
            require(t.first>=0 && t.first<x.size() && std::isfinite(t.second),"Invalid remapped support coefficient");
            sum+=t.second*x[t.first];
        }
        error=std::max(error,r.lower-sum);
    }
    return error;
}
bool box_feasible(const std::vector<Row>& rows,const Field& f) {
    for (const auto& r:rows) {
        double available=0;
        for (auto t:r.terms) {
            require(t.first>=0 && t.first<f.target.size() && std::isfinite(t.second),"Invalid support coefficient");
            available+=t.second*(t.second>=0?f.upper[t.first]:f.lower[t.first]);
        }
        require(std::isfinite(r.lower),"Invalid support bound");
        if (available+1e-9<r.lower) return false;
    }
    return true;
}
}

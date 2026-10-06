#include "af_smoothing/model.hpp"
namespace afs {
static double primal_error(const Quadratic& p,const Solution& s) {
    Vector g=p.G*s.x; double error=max_abs(p.A*s.x-p.b);
    for (int i=0;i<g.size();++i) error=std::max({error,p.lower[i]-g[i],g[i]-p.upper[i]});
    return error;
}
static double complementarity(const Quadratic& p,const Solution& s) {
    Vector g=p.G*s.x; double error=0;
    for (int i=0;i<g.size();++i) {
        error=std::max({error,-s.z_lower[i],-s.z_upper[i]});
        if (std::isfinite(p.lower[i])) error=std::max(error,std::abs(s.z_lower[i]*(g[i]-p.lower[i])));
        if (std::isfinite(p.upper[i])) error=std::max(error,std::abs(s.z_upper[i]*(p.upper[i]-g[i])));
    }
    return error;
}
static double dual_energy(const Quadratic& p,const Solution& s) {
    double energy=0;
    for(int i=0;i<p.lower.size();++i) {
        if(std::isfinite(p.lower[i])) energy+=std::abs(p.lower[i]*s.z_lower[i]);
        if(std::isfinite(p.upper[i])) energy+=std::abs(p.upper[i]*s.z_upper[i]);
    }
    return energy+std::abs(p.b.dot(s.y));
}
bool certify(const Quadratic& p,const Solution& s,double tolerance,Diagnostics& d) {
    if (!s.x.allFinite() || !s.y.allFinite() || !s.z_lower.allFinite() || !s.z_upper.allFinite()) return false;
    Vector px=p.P*s.x, a=p.A.transpose()*s.y, g=p.G.transpose()*(s.z_upper-s.z_lower);
    double scale=1+std::max({max_abs(px),max_abs(p.q),max_abs(a),max_abs(g)});
    d.violation=primal_error(p,s); d.stationarity=max_abs(px+p.q+a+g)/scale;
    d.complementarity=complementarity(p,s); d.objective=.5*s.x.dot(px)+p.q.dot(s.x);
    double energy=1+std::max({std::abs(s.x.dot(px)),std::abs(p.q.dot(s.x)),dual_energy(p,s)});
    d.complementarity_relative=d.complementarity/energy;
    bool dual_sign=(s.z_lower.size()==0 || s.z_lower.minCoeff()>=-tolerance) && (s.z_upper.size()==0 || s.z_upper.minCoeff()>=-tolerance);
    return d.violation<=tolerance && d.stationarity<=tolerance && d.complementarity_relative<=tolerance && dual_sign;
}
}

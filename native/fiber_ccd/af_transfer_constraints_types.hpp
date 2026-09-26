// Versioned optional constraint solve. ABI 1 shape transfer remains unchanged.
#pragma once
#include "af_transfer_shape.hpp"
namespace af_transfer_constraints {
using namespace af_transfer_shape;
enum Kind { Attachment, Shape, Guide, Clearance, Protection };
struct Rule {
    int kind,enabled,bins_u,bins_v;
    const int *selected,*allowed,*intended,*worlds;
    const double *targets,*axes;
    double weight,falloff,gap,tolerance,min_coverage;
};
struct Input {
    int abi,count;af_transfer_shape::Input *base;const Rule *rules;const int *owners;
    double *factors,*residuals,*movement,*summary,*coverage;
};
struct State {
    std::vector<P> rest,x,hard;std::vector<int> fixed;
    std::vector<std::vector<int>> clusters;std::vector<std::pair<int,int>> edges;
};
struct Query { std::vector<double>near,normals,distance;std::vector<int>owner,inside; };
static Query query(void*world,const std::vector<P>&x) {
    int n=(int)x.size();Query q{std::vector<double>(3*n),std::vector<double>(3*n),std::vector<double>(n),std::vector<int>(n),std::vector<int>(n)};
    std::vector<double>flat(3*n);store(x,flat.data());
    if(af_world_nearest_points(world,flat.data(),n,q.near.data(),q.normals.data(),q.distance.data(),q.owner.data(),q.inside.data()))throw std::runtime_error("query");
    return q;
}
static double violation(const Query&q,int i,double gap) { return std::max(0.,gap+(q.inside[i]?q.distance[i]:-q.distance[i])); }
static bool hard(const Rule&r) { return r.kind==Attachment||r.kind==Protection; }
static bool active(const Rule&r) { return r.enabled&&(hard(r)||r.weight>0); }
static P point(const Rule&r,int i) { return {r.targets[3*i],r.targets[3*i+1],r.targets[3*i+2]}; }
static void validate_rule(const Rule&r,const af_transfer_shape::Input&a) {
    if(r.kind<0||r.kind>4||!r.selected||!r.allowed||!r.intended||!r.worlds||!r.targets||!r.axes)throw std::invalid_argument("rule");
    for(double v:{r.weight,r.falloff,r.gap,r.tolerance,r.min_coverage})if(!std::isfinite(v)||v<0)throw std::invalid_argument("rule value");
    if(r.weight>1000||r.min_coverage>1||r.bins_u<1||r.bins_u>16||r.bins_v<1||r.bins_v>16||(hard(r)&&r.falloff>0))throw std::invalid_argument("rule bound");
    int seeds=0;for(int i=0;i<a.n;++i){seeds+=r.selected[i];if((r.selected[i]!=0&&r.selected[i]!=1)||(r.allowed[i]!=0&&r.allowed[i]!=1)||(r.intended[i]!=0&&r.intended[i]!=1))throw std::invalid_argument("mask");
        if((r.selected[i]||r.intended[i])&&!r.allowed[i])throw std::invalid_argument("domain");}
    if(!seeds)throw std::invalid_argument("empty domain");
    for(int i=0;i<a.n*3;++i)if(!std::isfinite(r.targets[i]))throw std::invalid_argument("target");
    for(int i=0;i<6;++i)if(!std::isfinite(r.axes[i]))throw std::invalid_argument("axis");
}
static void validate(const Input&a) {
    if(a.abi!=1||!a.base||!a.rules||!a.owners||!a.factors||!a.residuals||!a.movement||!a.summary||!a.coverage||a.count<1||a.count>128)throw std::invalid_argument("input");
    af_transfer_shape::validate(*a.base);if((long long)a.count*a.base->n>4000000)throw std::invalid_argument("allocation budget");
    for(int k=0;k<a.count;++k)validate_rule(a.rules[k],*a.base);
}
}

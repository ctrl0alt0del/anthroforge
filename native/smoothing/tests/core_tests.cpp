#include "af_smoothing/model.hpp"
#include <iostream>
using namespace afs;
struct StaticRows final : ConstraintSource {
    std::vector<Row> rows;
    std::vector<Row> map(const Vector&) override { return rows; }
};
struct WrongSolver final : QpSolver {
    Solution solve(const Quadratic& p,const Options&,Diagnostics&) override {
        return {Vector::Ones(p.q.size()),Vector::Zero(p.b.size()),Vector::Zero(p.lower.size()),Vector::Zero(p.upper.size()),QpStatus::solved,1};
    }
};
static Mesh fixture() {
    Mesh m; m.vertices.resize(5,3); m.vertices<<0,0,0, 1,0,0, 1,1,0, 0,1,0, .5,.5,0;
    m.faces.resize(4,3); m.faces<<0,1,4, 1,2,4, 2,3,4, 3,0,4; return m;
}
static Field field() {
    return {Vector::Zero(5),Vector::Zero(5),Vector::Ones(5),.18,.8};
}
static void energy_test() {
    CotangentBiharmonic builder; auto e=builder.build(fixture());
    require(std::abs(e.mass.sum()-1)<1e-12,"Area mass incorrect");
    require(max_abs(e.curvature*Vector::Ones(5))<1e-12,"Constant nullspace broken");
    Vector x(5); x<<.1,-1,2,.2,5;
    require(x.dot(e.curvature*x)>=0,"Curvature energy must be PSD");
}
static void constrained_test() {
    CotangentBiharmonic builder; Session session(fixture(),builder,make_piqp(),{}); StaticRows source;
    source.rows.push_back({{{4,1.}},.4}); auto f=field();
    f.upper.head(4).setZero(); auto r=session.run(f,source);
    require(r.status==Status::success && r.values[4]>=.4-1e-7,"Support solve failed");
    require(r.values.head(4).isZero(0),"Pins were moved");
    source.rows.push_back({{{4,-1.}},-.3}); r=session.run(f,source);
    require(r.status!=Status::success && r.values.size()==0,"Joint infeasibility not rejected");
}
static void certification_test() {
    CotangentBiharmonic builder; Session session(fixture(),builder,std::make_unique<WrongSolver>(),{});
    StaticRows source; auto r=session.run(field(),source);
    require(r.status==Status::validation_failure && r.values.size()==0,"Unverified output escaped");
}
static void validation_test() {
    CotangentBiharmonic builder; Session session(fixture(),builder,make_piqp(),{});
    StaticRows source; source.rows.push_back({{{7,1.}},1.});
    require(session.run(field(),source).status==Status::invalid_input,"Invalid constraint index accepted");
    auto m=fixture(); m.faces(1,1)=1;
    bool rejected=false; try { builder.build(m); } catch (const std::invalid_argument&) { rejected=true; }
    require(rejected,"Degenerate face accepted");
}
static void objective_scale_test() {
    Quadratic p; p.P.resize(1,1); p.P.insert(0,0)=1; p.A.resize(0,1); p.G.resize(1,1); p.G.insert(0,0)=1;
    p.q=Vector::Constant(1,-.5); p.b.resize(0); p.lower=Vector::Zero(1); p.upper=Vector::Ones(1);
    Solution s{Vector::Constant(1,.5),Vector(0),Vector::Constant(1,1e-9),Vector::Constant(1,1e-9),QpStatus::solved,1};
    Diagnostics d; require(certify(p,s,2e-7,d),"Valid small residual rejected");
    p.P*=1e6; p.q*=1e6; s.z_lower*=1e6; s.z_upper*=1e6;
    require(certify(p,s,2e-7,d),"Objective scaling changed certification");
    require(d.complementarity>2e-7 && d.complementarity_relative<2e-7,"Absolute diagnostic missing");
    s.z_lower.setConstant(1e6); s.z_upper.setConstant(1e6);
    require(!certify(p,s,2e-7,d),"Noncomplementary duals accepted");
}
int main() {
    try { energy_test(); constrained_test(); certification_test(); validation_test(); objective_scale_test();
        std::cout<<"5 native core test groups passed\n"; return 0;
    } catch (const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}

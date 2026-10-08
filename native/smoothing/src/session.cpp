#include "af_smoothing/model.hpp"
namespace afs {
Session::Session(const Mesh& m,const EnergyBuilder& builder,std::unique_ptr<QpSolver> solver,Options options)
    : options_(options),solver_(std::move(solver)) {
    validate_options(options); require(bool(solver_),"Missing QP solver");
    double begin=now_ms(); energy_=builder.build(m); energy_ms_=now_ms()-begin;
}
static std::vector<Row> map_rows(ConstraintSource& source,const Vector& x,Diagnostics& d) {
    double begin=now_ms(); auto rows=source.map(x); d.map_ms+=now_ms()-begin;
    d.rows=int(rows.size()); return rows;
}
static void exact_pins(Vector& x,const Field& f) {
    for (int i=0;i<x.size();++i) if (f.lower[i]==f.upper[i]) x[i]=f.lower[i];
}
static bool same_rows(const std::vector<Row>& a,const std::vector<Row>& b) {
    if (a.size()!=b.size()) return false;
    for (size_t i=0;i<a.size();++i)
        if (a[i].terms!=b[i].terms || a[i].lower!=b[i].lower || a[i].provider!=b[i].provider || a[i].face!=b[i].face) return false;
    return true;
}
bool Session::step(const Field& f,ConstraintSource& source,Vector& x,Result& r) {
    auto rows=map_rows(source,x,r.metrics);
    if (!box_feasible(rows,f)) { r.status=Status::infeasible; r.message="Support conflicts with fixed values or bounds"; return true; }
    double begin=now_ms(); auto p=assemble(energy_,f,rows); r.metrics.assembly_ms+=now_ms()-begin;
    auto s=solver_->solve(p,options_,r.metrics);
    if (s.status!=QpStatus::solved) { r.status=s.status==QpStatus::infeasible?Status::infeasible:Status::solver_failure;
        r.message="QP solver failure: status="+std::to_string(r.metrics.solver_status)+", round="+std::to_string(r.metrics.rounds)+", iterations="+std::to_string(s.iterations)+r.metrics.solver_detail; return true; }
    exact_pins(s.x,f);
    if (!certify(p,s,options_.tolerance,r.metrics)) { r.status=Status::validation_failure; r.message="Independent KKT verification failed"; return true; }
    double change=max_abs(x-s.x); x=s.x; auto current=map_rows(source,x,r.metrics);
    r.metrics.violation=std::max(r.metrics.violation,support_violation(current,x));
    return r.metrics.violation<=options_.tolerance && (same_rows(rows,current) || change<=options_.tolerance);
}
Result Session::run(const Field& f,ConstraintSource& source) {
    return run(f,source,f.target);
}
Result Session::run(const Field& f,ConstraintSource& source,const Vector& initial) {
    Result r; r.metrics.energy_ms=energy_ms_; double begin=now_ms();
    try { validate_field(f,int(energy_.mass.size())); require(initial.size()==f.target.size()&&initial.allFinite(),"Invalid initial field"); Vector x=initial.cwiseMax(f.lower).cwiseMin(f.upper);
        for (int i=0;i<options_.max_rounds;++i) {
            r.metrics.rounds=i+1;
            if (step(f,source,x,r)) { if (r.status==Status::success) r.values=x; break; }
        }
        if (r.status==Status::success && !r.values.size()) { r.status=Status::budget_exhausted; r.message="Contact remapping did not converge"; }
    } catch (const std::invalid_argument& e) { r.status=Status::invalid_input; r.message=e.what(); }
      catch (const ContactError& e) { r.status=Status::invalid_contact; r.message=e.what(); }
      catch (const std::exception& e) { r.status=Status::validation_failure; r.message=e.what(); }
    r.metrics.total_ms=now_ms()-begin; return r;
}
}

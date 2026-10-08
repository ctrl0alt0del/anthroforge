#include "af_smoothing/model.hpp"
#include <piqp/piqp.hpp>
#include <sstream>
namespace afs {
static QpStatus status_of(piqp::Status status) {
    if (status==piqp::PIQP_SOLVED) return QpStatus::solved;
    return status==piqp::PIQP_PRIMAL_INFEASIBLE?QpStatus::infeasible:QpStatus::failed;
}
static bool same_pattern(const Sparse& a,const Sparse& b) {
    if (a.rows()!=b.rows() || a.cols()!=b.cols() || a.nonZeros()!=b.nonZeros()) return false;
    return std::equal(a.outerIndexPtr(),a.outerIndexPtr()+a.cols()+1,b.outerIndexPtr()) &&
           std::equal(a.innerIndexPtr(),a.innerIndexPtr()+a.nonZeros(),b.innerIndexPtr());
}
class PiqpSolver final : public QpSolver {
    std::unique_ptr<piqp::SparseSolver<double>> solver_;
    Quadratic previous_;
    void configure(const Options& o) {
        auto& s=solver_->settings(); s.verbose=false; s.max_iter=o.max_iterations;
        s.eps_abs=s.eps_rel=s.eps_duality_gap_abs=s.eps_duality_gap_rel=std::min(1e-8,o.tolerance*.01);
        s.check_duality_gap=true;
        s.preconditioner_scale_cost=o.robust_linear_solve;
        s.iterative_refinement_always_enabled=o.robust_linear_solve;
    }
    bool reusable(const Quadratic& p) const {
        return solver_ && same_pattern(p.P,previous_.P) && same_pattern(p.A,previous_.A) && same_pattern(p.G,previous_.G);
    }
    void prepare(const Quadratic& p,const Options& o,Diagnostics& d) {
        double begin=now_ms();
        if (reusable(p)) { solver_->update(p.P,p.q,p.A,p.b,p.G,p.lower,p.upper); ++d.updates; }
        else { solver_=std::make_unique<piqp::SparseSolver<double>>(); configure(o);
            solver_->setup(p.P,p.q,p.A,p.b,p.G,p.lower,p.upper); ++d.setups; }
        configure(o); previous_=p; d.setup_ms+=now_ms()-begin;
    }
public:
    Solution solve(const Quadratic& p,const Options& o,Diagnostics& d) override {
        prepare(p,o,d); double begin=now_ms(); auto status=solver_->solve();
        d.solve_ms+=now_ms()-begin; auto& r=solver_->result();
        d.iterations+=int(r.info.iter); d.solver_status=int(status);
        std::ostringstream detail;detail<<" primal="<<r.info.primal_res<<" dual="<<r.info.dual_res<<" gap="<<r.info.duality_gap;
        d.solver_detail=detail.str();
        return {r.x,r.y,r.z_l,r.z_u,status_of(status),int(r.info.iter)};
    }
};
std::unique_ptr<QpSolver> make_piqp() { return std::make_unique<PiqpSolver>(); }
}

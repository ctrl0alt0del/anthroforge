#pragma once
#include <Eigen/Core>
#include <Eigen/Sparse>
#include <chrono>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace afs {
using Vector = Eigen::VectorXd;
using Sparse = Eigen::SparseMatrix<double>;
using Triplet = Eigen::Triplet<double>;
struct Mesh { Eigen::MatrixXd vertices; Eigen::MatrixXi faces; };
struct Energy { Sparse curvature; Vector mass; };
struct Row { std::vector<std::pair<int,double>> terms; double lower; int provider=-1, face=-1; };
struct Field { Vector target, lower, upper; double radius=.183, strength=.8; };
enum class Status { success, invalid_input, infeasible, invalid_contact, solver_failure, validation_failure, budget_exhausted };
class ContactError : public std::runtime_error { using std::runtime_error::runtime_error; };
struct Options { double tolerance=2e-7; int max_iterations=250, max_rounds=12;bool robust_linear_solve=false; };
struct Diagnostics {
    double energy_ms=0, assembly_ms=0, map_ms=0, setup_ms=0, solve_ms=0, total_ms=0;
    double violation=0, stationarity=0, complementarity=0, objective=0, complementarity_relative=0;
    int rounds=0, iterations=0, setups=0, updates=0, rows=0, solver_status=0;
    std::string solver_detail;
};
struct Result { Status status=Status::success; Vector values; Diagnostics metrics; std::string message; };
struct Quadratic { Sparse P,A,G; Vector q,b,lower,upper; };
enum class QpStatus { solved, infeasible, failed };
struct Solution { Vector x,y,z_lower,z_upper; QpStatus status=QpStatus::failed; int iterations=0; };

inline void require(bool condition, const char* message) {
    if (!condition) throw std::invalid_argument(message);
}
inline double now_ms() {
    return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
inline double max_abs(const Vector& v) { return v.size() ? v.cwiseAbs().maxCoeff() : 0.; }
void validate_mesh(const Mesh& mesh);
void validate_field(const Field& field, int count);
void validate_options(const Options& options);

class EnergyBuilder {
public:
    virtual ~EnergyBuilder() = default;
    virtual Energy build(const Mesh&) const = 0;
};
class CotangentBiharmonic final : public EnergyBuilder {
public:
    Energy build(const Mesh&) const override;
};
class ConstraintSource {
public:
    virtual ~ConstraintSource() = default;
    virtual std::vector<Row> map(const Vector&) = 0;
};
class NoSupport final : public ConstraintSource {
public:
    std::vector<Row> map(const Vector&) override { return {}; }
};
class QpSolver {
public:
    virtual ~QpSolver() = default;
    virtual Solution solve(const Quadratic&, const Options&, Diagnostics&) = 0;
};
std::unique_ptr<QpSolver> make_piqp();
Quadratic assemble(const Energy&, const Field&, const std::vector<Row>&);
bool certify(const Quadratic&, const Solution&, double, Diagnostics&);
double support_violation(const std::vector<Row>&, const Vector&);
bool box_feasible(const std::vector<Row>&, const Field&);

class Session {
    Energy energy_;
    Options options_;
    std::unique_ptr<QpSolver> solver_;
    double energy_ms_=0;
    bool step(const Field&, ConstraintSource&, Vector&, Result&);
public:
    Session(const Mesh&, const EnergyBuilder&, std::unique_ptr<QpSolver>, Options);
    Result run(const Field&, ConstraintSource&);
    Result run(const Field&, ConstraintSource&, const Vector& initial);
    const Energy& energy() const { return energy_; }
};
}

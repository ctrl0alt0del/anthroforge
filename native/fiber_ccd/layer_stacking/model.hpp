#pragma once
#include "af_smoothing/model.hpp"
namespace af_layer {
using namespace af_pair;
enum class OrderStatus { supported, no_upward, coincident, intersecting, conflicting, incompatible, projection, excluded };
enum class StackStatus { own_only, stacked, blocked, failed };
struct Settings { int enabled=1;double clearance=0,radius=.2,strength=.8,maximum=.5; };
struct Order {
    uint64_t first=0,second=0,underlying=0,covering=0;
    int status=1,warnings=0;double positive[2]{},negative[2]{},coincident=0,minimum=INFINITY,maximum=-INFINITY;
    int64_t fragments=0,points=0,crossings=0;char diagnostic[128]{};
};
struct Evidence { Order summary;std::shared_ptr<Result> geometry; };
struct CachedOrder { uint64_t a,b,used;Order summary; };
struct ConstraintInput {
    uint64_t id;const double* material;const int64_t* faces;const int64_t* interpolation;
    const double* weights;const int64_t* fixed;int vertices,triangles,samples,width,pins,valid;
};
struct Material {
    afs::Mesh mesh;std::vector<int64_t> interpolation,fixed;std::vector<double> weights;int width=0;std::string error;
};
struct ObstacleInput { const double* vertices;const int64_t* faces;int count,triangles; };
struct Output {
    uint64_t id=0;int status=0;int64_t vertices=0;double maximum=0,map_ms=0,solve_ms=0,validation_ms=0;
    int64_t baseline_self=0,baseline_bone_crossings=0,open_obstacles=0;double baseline_penetration=0;
    char message[256]{};
};
struct Solved { Output summary;std::vector<Vec> points;afs::Vector bonus; };
struct Evaluated { std::string signature;Solved result;uint64_t used=0; };
struct PolicyInput { uint64_t first,second,cover;int excluded,invalid,offset,count; };
struct Policy { uint64_t cover=0;bool excluded=false,invalid=false;std::set<std::pair<int64_t,int64_t>> faces; };
struct PolicyResult { uint64_t first=0,second=0;int status=0;char diagnostic[128]{}; };
struct State {
    Session bases;Settings settings;std::map<uint64_t,Material> materials;
    std::set<std::pair<uint64_t,uint64_t>> exclusions;
    std::map<std::pair<uint64_t,uint64_t>,CachedOrder> cache;
    std::vector<Evidence> orders;std::map<uint64_t,Solved> outputs;
    std::vector<Side> obstacles,incoming_obstacles;
    std::map<uint64_t,Evaluated> solved_cache;uint64_t clock=0;
    std::map<std::pair<uint64_t,uint64_t>,Policy> policies;
    std::map<std::pair<uint64_t,uint64_t>,PolicyResult> policy_results;
    double input_ms=0,order_ms=0,support_ms=0,solve_ms=0,validation_ms=0;uint64_t generation=0;
    uint64_t order_peak=0,order_computed=0,order_reused=0;
};
static Vec mean_direction(const Side& side,int face) {
    Vec value{};for(int i=0;i<3;++i)value=add(value,side.direction[side.faces[3*face+i]]);
    require(norm(value)>1e-12,"LAYER_ZERO_DIRECTION");return mul(value,1/norm(value));
}
static void message(Output& out,const std::string& value) {
    std::memcpy(out.message,value.data(),std::min(value.size(),sizeof(out.message)-1));
}
static Side base_copy(const Side& s) {
    Side out;out.id=s.id;out.base=s.base;out.own=s.base;out.direction=s.direction;out.faces=s.faces;
    out.parts=s.parts;out.sources=s.sources;out.family=s.family;out.root=s.root;out.instance=s.instance;
    out.enabled=s.enabled;out.inflation_side=s.inflation_side;return out;
}
}

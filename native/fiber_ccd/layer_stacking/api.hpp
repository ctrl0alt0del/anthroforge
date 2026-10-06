#pragma once
#include "model.hpp"
#include "relationship_policy.hpp"
#include "intersections.hpp"
#include "ordering.hpp"
#include "material_topology.hpp"
#include "material.hpp"
#include "support.hpp"
#include "collision.hpp"
#include "contact_validation.hpp"
#include "validation.hpp"
#include "reuse.hpp"
#include "graph.hpp"
namespace af_layer {
static void validate(const Settings& s) {
    require((s.enabled==0||s.enabled==1)&&std::isfinite(s.clearance)&&s.clearance>=0,"STACK_CLEARANCE");
    require(std::isfinite(s.radius)&&s.radius>=0&&std::isfinite(s.strength)&&s.strength>=0,"STACK_SMOOTHING");
    require(std::isfinite(s.maximum)&&s.maximum>=0,"STACK_MAXIMUM");
}
static Material checked_material(const ConstraintInput& input,const Side& side) {
    try{return capture_material(input,side);}catch(const std::exception& e){Material out;out.error=e.what();return out;}
}
static std::shared_ptr<State> configuration(Engine& engine,const Work& work,const Settings& settings,const ConstraintInput* material,const uint64_t* exclusions,int count) {
    validate(settings);require(count>=0&&(count==0||exclusions),"STACK_EXCLUSIONS");
    std::map<uint64_t,Material> materials;
    if(material)for(size_t i=0;i<work.incoming.size();++i){require(material[i].id==work.incoming[i].id,"STACK_MATERIAL_ID");materials.emplace(material[i].id,checked_material(material[i],work.incoming[i]));}
    std::set<std::pair<uint64_t,uint64_t>> excluded;for(int i=0;i<count;++i)excluded.insert(std::minmax(exclusions[2*i],exclusions[2*i+1]));
    auto state=std::make_shared<State>();
    state->settings=settings;state->materials=std::move(materials);state->exclusions=std::move(excluded);return state;
}
static void retain_caches(State& next,Engine& engine) {
    if(!engine.extension)return;auto& old=*std::static_pointer_cast<State>(engine.extension);
    next.bases=std::move(old.bases);next.cache=std::move(old.cache);next.solved_cache=std::move(old.solved_cache);
    next.obstacles=std::move(old.obstacles);next.clock=old.clock;
}
static void prepare_inputs(State& state,std::atomic<bool>& cancelled) {
    auto start=Clock::now();
    for(auto& item:state.materials)if(item.second.error.empty())try{normalize_material(item.second);}catch(const std::exception& e){item.second.error=e.what();}
    for(size_t i=0;i<state.incoming_obstacles.size();++i){require(!cancelled,"PAIR_CANCELLED");auto& next=state.incoming_obstacles[i];
        auto* old=i<state.obstacles.size()?&state.obstacles[i]:nullptr;
        if(old&&same(old->faces,next.faces)&&same(old->own,next.own)){next.snapshot=std::move(old->snapshot);next.enabled=old->enabled;continue;}
        prepare_snapshot(next,old);auto edges=edge_counts(next);
        next.enabled=std::all_of(edges.begin(),edges.end(),[](const auto& item){return item.second==2;});}
    state.obstacles=std::move(state.incoming_obstacles);state.input_ms=milliseconds(start);
}
static void pipeline(State& state,Session& session,std::atomic<bool>& cancelled) {
    state.generation=0;prepare_inputs(state,cancelled);order_pairs(state,session,cancelled);apply_policies(state);stack(state,session,cancelled);evict_solved(state,session);state.generation=session.published.generation;
}
static std::vector<Side> capture_obstacles(const ObstacleInput* inputs,int count) {
    require(count>=0&&(count==0||inputs),"STACK_OBSTACLES");std::vector<Side> result;
    for(int i=0;i<count;++i){const auto& in=inputs[i];require(in.vertices&&in.faces&&in.count>=3&&in.triangles>0,"STACK_OBSTACLE_INPUT");
        Side side;for(int j=0;j<in.count;++j){Vec point=load3(in.vertices+3*j);require(finite(point),"STACK_OBSTACLE_COORDINATES");side.base.push_back(point);}
        side.own=side.base;side.faces.assign(in.faces,in.faces+3*size_t(in.triangles));
        for(auto f:side.faces)require(f>=0&&f<in.count,"STACK_OBSTACLE_INDEX");result.push_back(std::move(side));}
    return result;
}
static State* ready_state(void* handle,uint64_t generation) {
    auto* engine=static_cast<Engine*>(handle);if(!ready(engine,generation)||!engine->extension)return nullptr;
    auto* state=static_cast<State*>(engine->extension.get());return state->generation==generation?state:nullptr;
}
}
AF_EXPORT int af_layer_order_version() { return 1; }
AF_EXPORT int af_layer_resolve_pair(void* handle,uint64_t generation,uint64_t a,uint64_t b,int exhaustive,af_layer::Order* result) {
    auto* state=af_layer::ready_state(handle,generation);if(!state||!result||!state->bases.indices.count(a)||!state->bases.indices.count(b))return 1;
    try{auto ai=state->bases.indices.at(a),bi=state->bases.indices.at(b);std::atomic<bool> cancel{false};
        *result=af_layer::resolve(state->bases,ai,bi,cancel,exhaustive!=0).summary;return 0;
    }catch(...){return 2;}
}
AF_EXPORT int af_stacking_version() { return 1; }
AF_EXPORT int af_stack_boundary_pins(const int64_t* faces,int count,int vertices,int64_t* flags) {
    if(!faces||!flags||count<1||vertices<3)return 1;std::map<af_layer::Edge,int> edges;
    for(int i=0;i<count;++i)for(int j=0;j<3;++j){auto a=faces[3*i+j],b=faces[3*i+(j+1)%3];
        if(a<0||b<0||a>=vertices||b>=vertices)return 1;++edges[std::minmax(a,b)];}
    std::fill(flags,flags+vertices,0);for(const auto& item:edges)if(item.second==1)flags[item.first.first]=flags[item.first.second]=1;
    return 0;
}
AF_EXPORT int af_stack_submit(void* handle,const af_pair::Input* inputs,int count,const af_pair::Settings* detection,const af_layer::ConstraintInput* material,const af_layer::Settings* settings,const uint64_t* excluded,int exclusions,const af_layer::ObstacleInput* obstacles,int obstacle_count,uint64_t generation) {
    using namespace af_pair;auto* engine=static_cast<Engine*>(handle);if(!engine||!settings||!detection)return 1;
    if(engine->work&&engine->work->state<2)return 2;
    try{auto work=capture_work(inputs,count,*detection,generation,false);auto bones=af_layer::capture_obstacles(obstacles,obstacle_count);
        auto state=af_layer::configuration(*engine,*work,*settings,material,excluded,exclusions);
        state->policies.clear();state->policy_results.clear();
        stop(*engine);af_layer::retain_caches(*state,*engine);
        state->incoming_obstacles=std::move(bones);engine->extension=state;engine->pipeline=[state](Session& s,std::atomic<bool>& c){af_layer::pipeline(*state,s,c);};
        engine->work=work;engine->worker=std::thread([engine,work]{run(*engine,work);});return 0;
    }catch(...){return 1;}
}
AF_EXPORT int af_layer_summary(void* handle,uint64_t generation,af_layer::Order* orders,int count,double* timings) {
    auto* state=af_layer::ready_state(handle,generation);if(!state)return 1;
    if(count<int(state->orders.size())||(!orders&&count)||!timings)return 2;
    for(size_t i=0;i<state->orders.size();++i)orders[i]=state->orders[i].summary;
    timings[0]=state->order_ms;timings[1]=state->support_ms;timings[2]=state->solve_ms;timings[3]=state->validation_ms;timings[4]=state->input_ms;return 0;
}
AF_EXPORT int af_layer_footprint(void* handle,uint64_t generation,int index,af_pair::Fragment* rows,int nf,af_pair::Point* points,int np) {
    auto* state=af_layer::ready_state(handle,generation);if(!state)return 1;
    if(index<0||index>=int(state->orders.size()))return 2;const auto& order=state->orders[index].summary;
    if(nf<order.fragments||np<order.points||(!rows&&nf)||(!points&&np))return 2;
    if(!order.fragments)return (nf||np)?2:0;
    try{std::atomic<bool> cancel{false};auto& s=state->bases;
        auto value=af_layer::order_geometry(s,s.indices.at(order.first),s.indices.at(order.second),cancel);
        af_pair::require(value->fragments.size()==size_t(order.fragments)&&value->points.size()==size_t(order.points),"LAYER_FOOTPRINT_MISMATCH");
        return af_pair::export_geometry(s,*value,rows,nf,points,np);
    }catch(const std::exception& e){return std::string(e.what()).find("BUDGET")!=std::string::npos?3:2;}catch(...){return 2;}
}
AF_EXPORT int af_layer_storage_stats(void* handle,uint64_t generation,double* values,int count) {
    auto* state=af_layer::ready_state(handle,generation);if(!state)return 1;if(!values||count<5)return 2;
    values[0]=double(state->order_peak);values[1]=double(af_layer::order_cache_bytes(*state));values[2]=double(state->orders.capacity()*sizeof(af_layer::Evidence));
    values[3]=double(state->order_computed);values[4]=double(state->order_reused);return 0;
}
AF_EXPORT int af_stack_summary(void* handle,uint64_t generation,af_layer::Output* rows,int count) {
    auto* state=af_layer::ready_state(handle,generation);if(!state)return 1;
    if(count<int(state->outputs.size())||(!rows&&count))return 2;int i=0;
    for(const auto& item:state->outputs)rows[i++]=item.second.summary;return 0;
}
AF_EXPORT int af_stack_output(void* handle,uint64_t generation,uint64_t id,double* points,int vertices) {
    auto* state=af_layer::ready_state(handle,generation);if(!state)return 1;auto it=state->outputs.find(id);
    if(it==state->outputs.end()||vertices!=int(it->second.points.size())||!points)return 2;
    std::memcpy(points,it->second.points.data(),vertices*sizeof(Vec));return 0;
}

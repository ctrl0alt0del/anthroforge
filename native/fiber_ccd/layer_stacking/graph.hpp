#pragma once
namespace af_layer {
struct Graph { std::map<uint64_t,std::set<uint64_t>> parents,children;std::set<uint64_t> blocked;std::map<uint64_t,std::string> reasons; };
static std::string order_failure(int status) {
    const char* names[]={"SUPPORTED","NO_UPWARD","COINCIDENT_BASES","INTERSECTING_BASES","CONFLICTING_LOCAL_ORDER","INCOMPATIBLE_DIRECTIONS","PROJECTION_FAILURE","EXCLUDED"};
    return std::string("STACK_")+names[status];
}
static Graph plan(const State& state) {
    Graph graph;for(const auto& item:state.outputs)graph.parents[item.first];
    for(const auto& item:state.materials)if(!item.second.error.empty()){graph.blocked.insert(item.first);graph.reasons[item.first]=item.second.error;}
    for(const auto& evidence:state.orders){const auto& order=evidence.summary;
        auto policy=state.policy_results.find(relationship_key(order.first,order.second));
        if(policy!=state.policy_results.end()&&policy->second.status==1)continue;
        if(policy!=state.policy_results.end()&&policy->second.status>1){graph.blocked.insert(order.first);graph.blocked.insert(order.second);graph.reasons[order.first]=graph.reasons[order.second]=policy->second.diagnostic;}
        if(order.status==int(OrderStatus::supported)){graph.parents[order.covering].insert(order.underlying);graph.children[order.underlying].insert(order.covering);}
        else if(order.status!=int(OrderStatus::no_upward)&&order.status!=int(OrderStatus::excluded)){
            graph.blocked.insert(order.first);graph.blocked.insert(order.second);graph.reasons[order.first]=graph.reasons[order.second]=order_failure(order.status);}
        if((state.materials.count(order.first)&&!state.materials.at(order.first).error.empty())||(state.materials.count(order.second)&&!state.materials.at(order.second).error.empty())){
            graph.blocked.insert(order.first);graph.blocked.insert(order.second);}}
    return graph;
}
static void propagate(Graph& graph) {
    std::vector<uint64_t> queue(graph.blocked.begin(),graph.blocked.end());
    for(size_t i=0;i<queue.size();++i)for(auto child:graph.children[queue[i]])if(graph.blocked.insert(child).second){queue.push_back(child);graph.reasons[child]="STACK_BLOCKED_BY_PROVIDER:"+std::to_string(queue[i]);}
}
static void own_outputs(State& state,const Session& detection) {
    state.outputs.clear();for(const auto& side:detection.sides)if(side.id){Solved out;
        out.summary.id=side.id;out.summary.vertices=side.own.size();out.points=side.own;
        if(state.materials.count(side.id)&&!state.materials.at(side.id).error.empty()){out.summary.status=3;message(out.summary,state.materials.at(side.id).error);}
        state.outputs[side.id]=std::move(out);}
}
static void evaluate_layer(State& state,const Session& detection,Graph& graph,const std::vector<uint64_t>& ready,std::atomic<bool>& cancelled) {
    std::vector<Solved> outputs(ready.size());int workers=std::max(1,std::min({4,int(ready.size()),af_parallel_limit()}));
    #pragma omp parallel for schedule(dynamic,1) num_threads(workers) if(workers>1)
    for(int i=0;i<int(ready.size());++i){auto id=ready[i];const auto& side=detection.sides[detection.indices.at(id)];
        if(graph.parents.at(id).empty()||graph.blocked.count(id))outputs[i]=state.outputs.at(id);
        else if(!state.materials.count(id)){outputs[i]=state.outputs.at(id);outputs[i].summary.status=3;message(outputs[i].summary,"STACK_MATERIAL_UNAVAILABLE");}
        else outputs[i]=cached_solve(side,state.materials.at(id),state,cancelled);}
    for(size_t i=0;i<ready.size();++i){auto id=ready[i];state.outputs[id]=std::move(outputs[i]);const auto& out=state.outputs[id].summary;
        state.support_ms+=out.map_ms;state.solve_ms+=out.solve_ms;state.validation_ms+=out.validation_ms;
        if(out.status==3)graph.blocked.insert(id);else if(!graph.parents[id].empty()&&!graph.blocked.count(id))remember_solved(state,detection.sides[detection.indices.at(id)],state.outputs[id]);}
    propagate(graph);
}
static void validate_pairs(State& state,const Session& detection,Graph& graph,std::atomic<bool>& cancelled) {
    for(const auto& pair:detection.published.pairs){auto& a=state.outputs.at(pair.first);auto& b=state.outputs.at(pair.second);
        if(a.summary.maximum==0&&b.summary.maximum==0)continue;
        const auto& sa=detection.sides[detection.indices.at(pair.first)];const auto& sb=detection.sides[detection.indices.at(pair.second)];
        try{auto oa=surface_copy(sa,sa.own),ob=surface_copy(sb,sb.own),fa=surface_copy(sa,a.points),fb=surface_copy(sb,b.points);
            validate_contact_pair(oa,fa,ob,fb,state,cancelled);
        }catch(const std::exception& e){for(auto* output:{&a,&b})if(output->summary.maximum>0){
            graph.blocked.insert(output->summary.id);message(output->summary,e.what());output->summary.status=3;}}}
    propagate(graph);
}
static void stack(State& state,const Session& detection,std::atomic<bool>& cancelled) {
    own_outputs(state,detection);state.support_ms=state.solve_ms=state.validation_ms=0;if(!state.settings.enabled)return;
    auto graph=plan(state);propagate(graph);std::set<uint64_t> pending,done;
    for(const auto& item:graph.parents)pending.insert(item.first);
    while(!pending.empty()){require(!cancelled,"PAIR_CANCELLED");std::vector<uint64_t> ready;
        for(auto id:pending)if(std::all_of(graph.parents[id].begin(),graph.parents[id].end(),[&](uint64_t p){return done.count(p);}))ready.push_back(id);
        if(ready.empty()){graph.blocked.insert(pending.begin(),pending.end());for(auto id:pending)graph.reasons[id]="STACK_DEPENDENCY_CYCLE_OR_DESCENDANT";break;}
        evaluate_layer(state,detection,graph,ready,cancelled);for(auto id:ready){pending.erase(id);done.insert(id);}}
    auto validation=Clock::now();validate_pairs(state,detection,graph,cancelled);state.validation_ms+=milliseconds(validation);
    for(auto id:graph.blocked){auto& out=state.outputs.at(id);if(out.summary.status!=3){message(out.summary,graph.reasons.count(id)?graph.reasons[id]:"STACK_INVALID_INPUT_DEPENDENCY");out.summary.status=2;}
        out.points=detection.sides[detection.indices.at(id)].own;out.bonus.resize(0);out.summary.maximum=0;}
}
}

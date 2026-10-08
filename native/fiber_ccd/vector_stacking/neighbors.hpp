#pragma once
namespace af_layer {
struct SurfacePair { Side own,final;Bounds sweep; };
static std::map<uint64_t,SurfacePair> final_snapshots(const State& state,const Session& detection) {
    std::map<uint64_t,SurfacePair> result;
    for(const auto& side:detection.sides)if(side.id){auto& entry=result[side.id];
        entry.own=surface_copy(side,side.own);entry.final=surface_copy(side,state.outputs.at(side.id).points);
        entry.sweep=af_pair::empty_bounds();for(Vec p:side.own)extend(entry.sweep,p);
        for(Vec p:entry.final.base)extend(entry.sweep,p);
        expand(entry.sweep,state.vector_settings.adjustment+state.settings.clearance);}
    return result;
}
static bool resolved_pair(const State& state,uint64_t a,uint64_t b) {
    if(!policy_allowed(state,a,b))return false;
    for(const auto& e:state.effective)if(relationship_key(a,b)==relationship_key(e.summary.first,e.summary.second))
        return e.summary.status==int(OrderStatus::supported);
    return false;
}
static void validate_neighbor(const SurfacePair& a,const SurfacePair& b,const State& state,std::atomic<bool>& cancel) {
    if(resolved_pair(state,a.final.id,b.final.id))validate_contact_pair(a.own,a.final,b.own,b.final,state,cancel);
    else require(intersections(a.final,b.final,false,cancel).empty(),"STACK_UNRESOLVED_NEW_NEIGHBOR_CONTACT");
}
static void block_contact(Graph& graph,State& state,uint64_t a,uint64_t b,const char* reason) {
    std::string text=std::string(reason)+":pair="+std::to_string(a)+","+std::to_string(b);
    for(auto id:{a,b}){auto& output=state.outputs.at(id);graph.blocked.insert(id);graph.reasons[id]=text;
        message(output.summary,text);output.summary.status=int(StackStatus::failed);}
}
static void validate_expanded_neighbors(State& state,const Session& detection,Graph& graph,std::atomic<bool>& cancel) {
    auto surfaces=final_snapshots(state,detection);
    for(auto first=surfaces.begin();first!=surfaces.end();++first)for(auto second=std::next(first);second!=surfaces.end();++second){
        require(!cancel,"PAIR_CANCELLED");auto a=first->first,b=second->first;
        if(graph.blocked.count(a)||graph.blocked.count(b)||!eligible(first->second.final,second->second.final))continue;
        if(state.outputs.at(a).summary.maximum==0&&state.outputs.at(b).summary.maximum==0)continue;
        if(!intersects(first->second.sweep,second->second.sweep))continue;
        try{validate_neighbor(first->second,second->second,state,cancel);}
        catch(const std::exception& e){if(cancel)throw;block_contact(graph,state,a,b,e.what());}}
    propagate(graph);
}
}

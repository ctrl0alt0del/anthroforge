#pragma once
namespace af_layer {
template<class T> static void signature_array(std::string& key,const T* values,size_t count) {
    key.append(reinterpret_cast<const char*>(&count),sizeof(count));if(count)key.append(reinterpret_cast<const char*>(values),count*sizeof(T));
}
template<class T> static void signature_vector(std::string& key,const std::vector<T>& values) {
    signature_array(key,values.data(),values.size());
}
static void policy_signature(std::string& key,const State& state,uint64_t id) {
    for(const auto& item:state.policies)if(item.first.first==id||item.first.second==id){
        signature_array(key,&item.first.first,1);signature_array(key,&item.first.second,1);signature_array(key,&item.second.cover,1);
        signature_array(key,&item.second.mode,1);signature_array(key,&item.second.excluded,1);signature_array(key,&item.second.invalid,1);auto size=item.second.faces.size();signature_array(key,&size,1);
        for(const auto& face:item.second.faces){signature_array(key,&face.first,1);signature_array(key,&face.second,1);}}
}
static void base_signature(std::string& key,const Side& side) {
    signature_vector(key,side.base);signature_vector(key,side.direction);signature_vector(key,side.faces);
    signature_vector(key,side.parts);signature_vector(key,side.sources);
}
static std::string solve_signature(const Side& side,const State& state,const Material& material) {
    std::string key;base_signature(key,side);signature_vector(key,side.own);
    key+="vector-localized-v1";signature_array(key,&state.vector_settings.blend,1);signature_array(key,&state.vector_settings.preservation,1);signature_array(key,&state.vector_settings.adjustment,1);
    double settings[]={state.settings.clearance,state.settings.maximum,state.settings.radius,state.settings.strength,state.bases.settings.area,state.bases.settings.epsilon};signature_array(key,settings,6);
    af_stack_vector::material_signature(key,material);
    policy_signature(key,state,side.id);
    for(const auto& e:state.effective)if(e.summary.status==0&&e.summary.covering==side.id&&policy_allowed(state,e.summary.first,e.summary.second)){
        signature_array(key,&e.summary.underlying,1);signature_vector(key,state.outputs.at(e.summary.underlying).points);
        base_signature(key,state.bases.sides[state.bases.indices.at(e.summary.underlying)]);}
    for(const auto& bone:state.obstacles){signature_vector(key,bone.base);signature_vector(key,bone.faces);}return key;
}
static Solved cached_solve(const Side& side,const Material& material,const State& state,std::atomic<bool>& cancelled) {
    try{auto signature=solve_signature(side,state,material);auto it=state.solved_cache.find(side.id);
    if(it!=state.solved_cache.end()&&it->second.signature==signature){auto out=it->second.result;
        for(int i:{0,3,4,5,6,14,15})out.vector_metrics[i]=0;out.vector_metrics[23]=1;
        out.summary.map_ms=out.summary.solve_ms=out.summary.validation_ms=0;return out;}
    return solve_side(side,material,state,cancelled);
    }catch(const std::exception& e){Solved out;out.summary.id=side.id;out.summary.vertices=side.own.size();out.points=side.own;
        out.summary.status=3;message(out.summary,e.what());return out;}
}
static void remember_solved(State& state,const Side& side,const Solved& result) {
    if(result.summary.status>1||!state.materials.count(side.id))return;
    state.solved_cache[side.id]={solve_signature(side,state,state.materials.at(side.id)),result,++state.clock};
}
static void evict_solved(State& state,const Session& session) {
    std::set<uint64_t> live;for(const auto& p:session.indices)live.insert(p.first);state.vector_cache->retain(live,session.settings.cache_bytes);
    uint64_t used=0;for(auto it=state.solved_cache.begin();it!=state.solved_cache.end();){
        if(!session.indices.count(it->first)){it=state.solved_cache.erase(it);continue;}
        used+=it->second.signature.capacity()+it->second.result.points.capacity()*sizeof(Vec)+it->second.result.bonus.size()*sizeof(double);++it;}
    while(used>session.settings.cache_bytes&&!state.solved_cache.empty()){
        auto oldest=std::min_element(state.solved_cache.begin(),state.solved_cache.end(),[](const auto& a,const auto& b){return a.second.used<b.second.used;});
        used-=oldest->second.signature.capacity()+oldest->second.result.points.capacity()*sizeof(Vec)+oldest->second.result.bonus.size()*sizeof(double);state.solved_cache.erase(oldest);}
}
}

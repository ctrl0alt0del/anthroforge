#pragma once
AF_EXPORT int af_relationship_policy_version() { return 1; }
AF_EXPORT int af_stack_submit_relationships_v1(void* handle,const af_pair::Input* inputs,int count,const af_pair::Settings* detection,const af_layer::ConstraintInput* material,const af_layer::Settings* settings,const uint64_t* excluded,int exclusions,const af_layer::ObstacleInput* obstacles,int obstacle_count,uint64_t generation,const af_layer::PolicyInput* policies,int policy_count,const int64_t* faces,int face_count) {
    using namespace af_pair;auto* engine=static_cast<Engine*>(handle);if(!engine||!settings||!detection)return 1;
    if(engine->work&&engine->work->state<2)return 2;
    try{auto work=capture_work(inputs,count,*detection,generation,false);auto bones=af_layer::capture_obstacles(obstacles,obstacle_count);
        auto state=af_layer::configuration(*engine,*work,*settings,material,excluded,exclusions);
        af_layer::capture_policies(*state,*work,policies,policy_count,faces,face_count);state->incoming_obstacles=std::move(bones);
        stop(*engine);af_layer::retain_caches(*state,*engine);engine->extension=state;engine->pipeline=[state](Session& s,std::atomic<bool>& c){af_layer::pipeline(*state,s,c);};
        engine->work=work;engine->worker=std::thread([engine,work]{run(*engine,work);});return 0;
    }catch(...){return 1;}
}
AF_EXPORT int af_relationship_policy_summary(void* handle,uint64_t generation,af_layer::PolicyResult* rows,int count) {
    auto* state=af_layer::ready_state(handle,generation);if(!state||count<int(state->orders.size())||(!rows&&count))return 1;
    int i=0;for(const auto& evidence:state->orders){const auto& o=evidence.summary;auto key=af_layer::relationship_key(o.first,o.second);
        auto it=state->policy_results.find(key);rows[i++]=it==state->policy_results.end()?af_layer::PolicyResult{o.first,o.second}:it->second;}return 0;
}

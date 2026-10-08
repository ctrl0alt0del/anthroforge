#pragma once
namespace af_stack_vector {
static void capture_exact(State& state,const ExactInput* inputs,int count) {
    require(count>=0&&(!count||inputs),"STACK_VECTOR_CONSTRAINT_INPUT");std::set<uint64_t> seen;
    for(int i=0;i<count;++i){const auto& in=inputs[i];require(seen.insert(in.id).second&&state.materials.count(in.id),"STACK_VECTOR_CONSTRAINT_ID");
        require(in.count>=0&&in.count<=2000000&&in.width>=1&&in.width<=4&&(!in.count||(in.indices&&in.weights)),"STACK_VECTOR_CONSTRAINT_SIZE");
        auto& m=state.materials.at(in.id);if(!m.error.empty())continue;
        for(int row=0;row<in.count;++row){afs::Row r;r.lower=0;double sum=0;std::map<int,double> terms;
            for(int j=0;j<in.width;++j){int k=row*in.width+j;double w=in.weights[k];auto id=in.indices[k];
                require(std::isfinite(w)&&id>=0&&id<m.mesh.vertices.rows(),"STACK_VECTOR_CONSTRAINT_VALUE");terms[int(id)]+=w;sum+=w;}
            require(std::abs(sum-1)<1e-9,"STACK_VECTOR_CONSTRAINT_SUM");for(auto t:terms)if(t.second!=0)r.terms.push_back(t);m.constraints.push_back(std::move(r));}}
    require(seen.size()==state.materials.size(),"STACK_VECTOR_CONSTRAINT_MISSING");
}
static void validate_vector(const VectorSettings& settings) {
    require(std::isfinite(settings.blend)&&settings.blend>=0,"STACK_VECTOR_BLEND");
    require(std::isfinite(settings.preservation)&&settings.preservation>=1,"STACK_VECTOR_PRESERVATION");
    require(std::isfinite(settings.adjustment)&&settings.adjustment>=0,"STACK_VECTOR_ADJUSTMENT");
}
}
AF_EXPORT int af_vector_stacking_version(){return 1;}
AF_EXPORT const char* af_stack_legacy_diagnostic(){return "STACK_SCALAR_SUBMISSION_RETIRED: use af_vector_stack_submit_v1";}
AF_EXPORT int af_vector_stack_submit_v1(void* handle,const af_pair::Input* inputs,int count,const af_pair::Settings* detection,const af_layer::ConstraintInput* material,const af_layer::Settings* settings,const uint64_t* excluded,int exclusions,const af_layer::ObstacleInput* obstacles,int obstacle_count,uint64_t generation,const af_layer::PolicyInputV2* policies,int policy_count,const int64_t* faces,int face_count,const af_layer::VectorSettings* vector_settings,const af_layer::ExactInput* exact,int exact_count) {
    using namespace af_pair;auto* engine=static_cast<Engine*>(handle);if(!engine||!settings||!detection||!vector_settings)return 1;
    if(engine->work&&engine->work->state<2)return 2;
    try{auto work=capture_work(inputs,count,*detection,generation,false);auto bones=af_layer::capture_obstacles(obstacles,obstacle_count);
        auto state=af_layer::configuration(*engine,*work,*settings,material,excluded,exclusions);af_stack_vector::validate_vector(*vector_settings);state->vector_settings=*vector_settings;
        af_layer::capture_policies_v2(*state,*work,policies,policy_count,faces,face_count);af_stack_vector::capture_exact(*state,exact,exact_count);
        state->incoming_obstacles=std::move(bones);stop(*engine);af_layer::retain_caches(*state,*engine);engine->extension=state;
        engine->pipeline=[state](Session& s,std::atomic<bool>& c){af_layer::pipeline(*state,s,c);};
        engine->work=work;engine->worker=std::thread([engine,work]{run(*engine,work);});return 0;
    }catch(...){return 1;}
}
AF_EXPORT int af_vector_stack_metrics(void* handle,uint64_t generation,uint64_t id,double* values,int count) {
    auto* state=af_layer::ready_state(handle,generation);if(!state||!values||count<24||!state->outputs.count(id))return 1;
    std::copy(state->outputs.at(id).vector_metrics,state->outputs.at(id).vector_metrics+24,values);return 0;
}

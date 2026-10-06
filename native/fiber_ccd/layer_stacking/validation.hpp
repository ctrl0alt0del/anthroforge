#pragma once
namespace af_layer {
static void validate_final(const Side& original,const std::vector<Vec>& final) {
    for(size_t f=0;f<original.faces.size();f+=3){Vec old[3],next[3];
        for(int j=0;j<3;++j){int id=int(original.faces[f+j]);old[j]=original.own[id];next[j]=final[id];require(finite(next[j]),"STACK_NONFINITE_OUTPUT");}
        Vec a=cross(sub(old[1],old[0]),sub(old[2],old[0])),b=cross(sub(next[1],next[0]),sub(next[2],next[0]));
        if(norm(a)<=1e-14)continue;require(norm(b)>1e-10*norm(a)&&dot(a,b)>0,"STACK_NEW_FOLD_OR_COLLAPSE");}
}
static Solved solve_side(const Side& side,const Material& material,const State& state,std::atomic<bool>& cancelled) {
    Solved out;out.summary.id=side.id;out.summary.vertices=side.own.size();out.points=side.own;
    try{auto mapping=Clock::now();SupportSource source(side,material,state,cancelled);afs::CotangentBiharmonic builder;
        bool needed=afs::support_violation(source.map(afs::Vector::Zero(material.mesh.vertices.rows())),afs::Vector::Zero(material.mesh.vertices.rows()))>2e-7;
        out.summary.map_ms=milliseconds(mapping);if(!needed)return out;
        afs::Session session(material.mesh,builder,afs::make_piqp(),afs::Options{});
        auto result=session.run(bonus_field(material,state.settings),source);
        out.summary.map_ms+=result.metrics.map_ms;out.summary.solve_ms=result.metrics.total_ms-result.metrics.map_ms;
        require(result.status==afs::Status::success,result.message.c_str());require(!cancelled,"PAIR_CANCELLED");
        auto start=Clock::now();baseline_diagnostics(side,state,out.summary,cancelled);auto final=displaced(side,material,result.values);validate_final(side,final);validate_collisions(side,final,state,cancelled);
        out.summary.validation_ms=milliseconds(start);out.points=std::move(final);out.bonus=result.values;
        out.summary.maximum=result.values.maxCoeff();out.summary.status=int(StackStatus::stacked);
    }catch(const std::exception& e){out.summary.status=int(StackStatus::failed);message(out.summary,e.what());}
    return out;
}
}

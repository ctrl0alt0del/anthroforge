#pragma once
#include "correspondence.hpp"
#include "material.hpp"
#include "providers.hpp"
#include "locality.hpp"
#include "support.hpp"
#include "quadratic.hpp"
namespace af_stack_vector {
static void summarize_displacement(const Side& side,const Mat& raw,const std::vector<Vec>& final,const Locality& local,double* metrics) {
    double before=0,after=0;metrics[10]=raw.rowwise().norm().maxCoeff();
    for(int i=0;i<raw.rows();++i){double d=norm(sub(final[i],side.own[i]));metrics[11]=std::max(metrics[11],d);
        if(local.falloff[i]==0)metrics[12]=std::max(metrics[12],d);
        if(raw.row(i).norm()>1e-9){before+=raw.row(i).norm();after+=d;}}
    metrics[13]=before?after/before:1;require(metrics[12]<1e-8,"STACK_VECTOR_FAR_REGION_MOVED");
}
static void validate_solution(const Side& side,const Layout& l,const std::vector<Provider>& p,const State& state,Solved& out,const afs::Vector& values,std::atomic<bool>& cancel) {
    require(!cancel,"PAIR_CANCELLED");auto final=evaluate(side,l,values);auto rows=support_rows(side,l,p,final,state,cancel);
    out.vector_metrics[8]=afs::support_violation(rows,values);require(out.vector_metrics[8]<=2e-7,"STACK_VECTOR_REMAPPED_SUPPORT_FAILED");
    out.vector_metrics[9]=afs::max_abs(l.constraints*values);require(out.vector_metrics[9]<=2e-7,"STACK_VECTOR_ATTACHMENT_MOVED");
    baseline_diagnostics(side,state,out.summary,cancel);out.vector_metrics[22]=1;validate_final(side,final);validate_collisions(side,final,state,cancel);
    auto surface=surface_copy(side,final);
    for(const auto& provider:p){auto other=surface_copy(provider.side,provider.side.own);
        require(intersections(surface,other,false,cancel).empty(),"STACK_VECTOR_PROVIDER_INTERSECTION");}
    out.vector_metrics[21]=1;out.points=std::move(final);out.bonus=values;out.summary.status=int(StackStatus::stacked);
}
static void locality_metrics(const Locality& local,const Mat& raw,double* d) {
    d[10]=raw.rowwise().norm().maxCoeff();d[16]=local.weight.minCoeff();d[17]=local.weight.maxCoeff();
    for(int i=0;i<local.falloff.size();++i){d[18]+=local.falloff[i]==0;d[19]+=local.falloff[i]>0&&local.falloff[i]<1;}
}
static void checked_solution(const Side& side,const Layout& l,const std::vector<Provider>& p,const State& state,Solved& out,const afs::Vector& values,std::atomic<bool>& cancel) {
    double start=afs::now_ms();
    try{validate_solution(side,l,p,state,out,values,cancel);}
    catch(...){out.summary.validation_ms=afs::now_ms()-start;throw;}
    out.summary.validation_ms=afs::now_ms()-start;
}
static void run(const Side& side,const Material& m,const State& state,Solved& out,std::atomic<bool>& cancel) {
    auto* d=out.vector_metrics;double start=afs::now_ms(),phase=start;auto prepared_value=prepared(side,m,state);
    const auto& l=prepared_value->layout;const auto& energy=prepared_value->energy;d[14]=afs::now_ms()-phase;
    auto p=providers(side,state,cancel,d);Mat raw=compose(side,p);pin_targets(raw,l);phase=afs::now_ms();
    auto locality_value=cached_locality(side,l,p,raw,energy,state,cancel);const auto& local=*locality_value;d[3]=afs::now_ms()-phase;phase=afs::now_ms();
    auto raw_points=side.own;for(int i=0;i<raw.rows();++i)raw_points[i]=add(raw_points[i],vector(raw.row(i)));
    locality_metrics(local,raw,d);auto rows=support_rows(side,l,p,raw_points,state,cancel);d[20]=rows.size();d[4]=afs::now_ms()-phase;phase=afs::now_ms();
    auto qp=quadratic(l,energy,local,raw,rows,state);d[5]=afs::now_ms()-phase;require(!cancel,"PAIR_CANCELLED");auto solution=solve(qp,d);
    summarize_displacement(side,raw,evaluate(side,l,solution.x),local,d);
    checked_solution(side,l,p,state,out,solution.x,cancel);out.summary.maximum=d[11];
}
}
namespace af_layer {
static Solved solve_side(const Side& side,const Material& material,const State& state,std::atomic<bool>& cancel) {
    Solved out;double start=afs::now_ms();out.summary.id=side.id;out.summary.vertices=side.own.size();out.points=side.own;
    try{af_stack_vector::run(side,material,state,out,cancel);}
    catch(const std::exception& e){out.points=side.own;out.bonus.resize(0);out.summary.maximum=0;out.summary.status=int(StackStatus::failed);message(out.summary,e.what());}
    out.vector_metrics[15]=afs::now_ms()-start;out.summary.map_ms=out.vector_metrics[0]+out.vector_metrics[3]+out.vector_metrics[4];out.summary.solve_ms=out.vector_metrics[5]+out.vector_metrics[6];return out;
}
}

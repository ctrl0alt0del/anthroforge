#pragma once
namespace af_layer {
// A transverse triangle contact is permissible only with a complete signed separation proof.
static bool final_support_separated(const Side& a,const Side& b,const State& state,std::atomic<bool>& cancel) {
    uint64_t cover=0;
    for(const auto& order:state.effective)if(order.summary.status==int(OrderStatus::supported)&&
        std::minmax(order.summary.first,order.summary.second)==std::minmax(a.id,b.id))cover=order.summary.covering;
    if(!cover)return false;
    std::vector<Side> inputs;inputs.push_back(base_copy(a));inputs.push_back(base_copy(b));
    Session session;auto settings=state.bases.settings;settings.search=extent(a,b);synchronize(session,inputs,settings);
    Result evidence;Budget budget;budget.cancelled=&cancel;budget.max_bytes=settings.result_bytes;budget.max_fragments=settings.limit;
    map_direction(session,cover==a.id?0:1,cover==a.id?1:0,evidence,budget,false);
    if(evidence.stats[4]!=0||evidence.fragments.empty())return false;
    return std::all_of(evidence.fragments.begin(),evidence.fragments.end(),[](const Fragment& f){return f.gap_max<=2e-7;});
}
static void validate_contact_pair(const Side& own,const Side& final,const Side& other,const Side& next,const State& state,std::atomic<bool>& cancel) {
    validate_explicit(final,next,state,cancel);
    try{no_new_crossings(own,final,other,next,false,cancel);}
    catch(const std::exception& error){
        if(cancel||std::string(error.what())!="STACK_NEW_SURFACE_INTERSECTION"||!final_support_separated(final,next,state,cancel))throw;
    }
}
}

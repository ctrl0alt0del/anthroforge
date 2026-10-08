#pragma once
namespace af_layer {
struct ExplicitCheck { double gap=-INFINITY;int64_t fragments=0,warnings=0;int face=-1; };
static uint64_t explicit_cover(const State& s,uint64_t a,uint64_t b) {
    auto it=s.policies.find(relationship_key(a,b));
    return it!=s.policies.end()&&!it->second.excluded&&!it->second.invalid&&it->second.mode==2?it->second.cover:0;
}
static ExplicitCheck signed_separation(const Side& cover,const Side& provider,const State& s,std::atomic<bool>& cancel) {
    Session session;auto settings=s.bases.settings;settings.search=extent(cover,provider);
    std::vector<Side> inputs;inputs.push_back(base_copy(cover));inputs.push_back(base_copy(provider));
    synchronize(session,inputs,settings);Result raw;Budget budget;
    budget.cancelled=&cancel;budget.max_bytes=settings.result_bytes;budget.max_fragments=settings.limit;
    map_direction(session,0,1,raw,budget,false);ExplicitCheck check;check.warnings=raw.stats[4];
    for(const auto& f:raw.fragments)if(selected_material(s,cover.id,provider.id,int(f.receiver_face))){
        ++check.fragments;if(f.gap_max>check.gap){check.gap=f.gap_max;check.face=int(f.receiver_face);}}
    return check;
}
static void validate_explicit(const Side& a,const Side& b,const State& s,std::atomic<bool>& cancel) {
    auto id=explicit_cover(s,a.id,b.id);if(!id)return;
    const auto& cover=id==a.id?a:b;const auto& provider=id==a.id?b:a;
    auto outer=signed_separation(cover,provider,s,cancel);
    require(!outer.warnings,"EXPLICIT_SEPARATION_PROJECTION_FAILED");
    require(outer.gap<=2e-7-s.settings.clearance,"EXPLICIT_REMAINING_OUTER_PENETRATION");
}
}

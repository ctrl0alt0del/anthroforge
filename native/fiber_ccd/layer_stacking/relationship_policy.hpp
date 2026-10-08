#pragma once
namespace af_layer {
static std::pair<uint64_t,uint64_t> relationship_key(uint64_t a,uint64_t b) { return std::minmax(a,b); }
static bool policy_allowed(const State& state,uint64_t a,uint64_t b) {
    auto it=state.policy_results.find(relationship_key(a,b));return it==state.policy_results.end()||it->second.status==0;
}
static bool selected_material(const State& state,uint64_t cover,uint64_t provider,int face) {
    auto it=state.policies.find(relationship_key(cover,provider));if(it==state.policies.end()||it->second.faces.empty())return true;
    const auto& side=state.bases.sides[state.bases.indices.at(cover)];
    return it->second.faces.count({side.parts[face],side.sources[face]})!=0;
}
static Policy checked_policy(const PolicyInput& in,const int64_t* faces,int count,const std::set<uint64_t>& ids) {
    require(ids.count(in.first)&&ids.count(in.second)&&in.first!=in.second,"RELATIONSHIP_PAIR");
    require(!in.cover||in.cover==in.first||in.cover==in.second,"RELATIONSHIP_COVER");
    require((in.excluded==0||in.excluded==1)&&(in.invalid==0||in.invalid==1),"RELATIONSHIP_FLAGS");
    require(in.offset>=0&&in.count>=0&&in.offset<=count&&in.count<=count-in.offset,"RELATIONSHIP_OFFSETS");
    require(!in.count||in.cover,"RELATIONSHIP_REGION_COVER");Policy out;out.cover=in.cover;out.excluded=in.excluded;out.invalid=in.invalid;
    for(int j=in.offset;j<in.offset+in.count;++j){require(faces[2*j]>=0&&faces[2*j+1]>=0,"RELATIONSHIP_FACE");out.faces.insert({faces[2*j],faces[2*j+1]});}
    return out;
}
static void capture_policies(State& state,const Work& work,const PolicyInput* inputs,int count,const int64_t* faces,int size) {
    require(count>=0&&count<=1000000&&size>=0&&size<=2000000&&(!count||inputs)&&(!size||faces),"RELATIONSHIP_INPUT");
    require(count||!size,"RELATIONSHIP_OFFSETS");std::set<uint64_t> ids;for(const auto& side:work.incoming)ids.insert(side.id);
    state.policies.clear();state.policy_results.clear();int end=0;
    for(int i=0;i<count;++i){const auto& in=inputs[i];require(in.offset==end,"RELATIONSHIP_OFFSETS");
        auto value=checked_policy(in,faces,size,ids);end=in.offset+in.count;
        require(state.policies.emplace(relationship_key(in.first,in.second),std::move(value)).second,"RELATIONSHIP_DUPLICATE");}
    require(end==size,"RELATIONSHIP_OFFSETS");
}
static bool region_known(const State& state,const Policy& policy) {
    if(policy.faces.empty())return true;const auto& side=state.bases.sides[state.bases.indices.at(policy.cover)];
    auto missing=policy.faces;for(size_t i=0;i<side.parts.size();++i)missing.erase({side.parts[i],side.sources[i]});return missing.empty();
}
static void capture_policies_v2(State& state,const Work& work,const PolicyInputV2* inputs,int count,const int64_t* faces,int size) {
    require(count>=0&&count<=1000000&&(!count||inputs),"RELATIONSHIP_INPUT");std::vector<PolicyInput> legacy;
    std::map<uint64_t,uint64_t> roots;for(const auto& side:work.incoming)roots.emplace(side.id,side.root);
    for(int i=0;i<count;++i){const auto& in=inputs[i];require(in.mode>=0&&in.mode<=2,"RELATIONSHIP_ORDER_MODE");
        require(roots.count(in.legacy.first)&&roots.count(in.legacy.second)&&roots.at(in.legacy.first)==roots.at(in.legacy.second),"RELATIONSHIP_ROOT_MISMATCH");
        require(in.mode==0?!in.legacy.cover:bool(in.legacy.cover),"RELATIONSHIP_ORDER_COVER");legacy.push_back(in.legacy);}
    capture_policies(state,work,legacy.data(),count,faces,size);
    for(int i=0;i<count;++i)state.policies.at(relationship_key(inputs[i].legacy.first,inputs[i].legacy.second)).mode=inputs[i].mode;
}
static bool intrinsic_directions_valid(const Side& side) {
    for(size_t i=0;i<side.base.size();++i)
        if(dot(sub(side.own[i],side.base[i]),side.direction[i])<-1e-8)return false;
    return true;
}
static void explicit_order(Evidence& evidence,const Policy& policy,const State& state) {
    auto& order=evidence.summary;
    if(order.warnings||order.status==int(OrderStatus::projection))return;
    // Vector transport does not require two distinct muscles' directions to be parallel.
    for(auto id:{order.first,order.second})if(state.invalid_directions.count(id)){
        order.status=int(OrderStatus::incompatible);return;}
    if(!order.fragments){order.status=int(OrderStatus::no_upward);const char text[]="EXPLICIT_NO_PROJECTED_OVERLAP";std::memcpy(order.diagnostic,text,sizeof(text));return;}
    order.status=int(OrderStatus::supported);order.covering=policy.cover;
    order.underlying=policy.cover==order.first?order.second:order.first;
}
static void apply_policies(State& state) {
    state.effective=state.orders;state.policy_results.clear();for(auto& evidence:state.effective){auto& order=evidence.summary;auto key=relationship_key(order.first,order.second);
        auto it=state.policies.find(key);if(it==state.policies.end())continue;const auto& p=it->second;PolicyResult row;row.first=order.first;row.second=order.second;
        row.status=p.excluded?1:p.invalid||!region_known(state,p)?3:p.mode==1&&order.status==0&&p.cover&&p.cover!=order.covering?2:0;
        if(row.status==0&&p.mode==2)explicit_order(evidence,p,state);
        const char* names[]={"","RELATIONSHIP_EXCLUDED","MANUAL_ORDER_CONFLICT","STALE_SELECTED_REGION"};
        std::memcpy(row.diagnostic,names[row.status],std::strlen(names[row.status])+1);state.policy_results[key]=row;}
}
}

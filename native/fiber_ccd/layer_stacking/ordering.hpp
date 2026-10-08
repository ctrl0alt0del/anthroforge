#pragma once
namespace af_layer {
static FixedPolygon depth_polygon(const Fragment& f,const Result& geometry,Vec d) {
    auto frame=ly_frame(d);FixedPolygon poly;Vec origin=load3(geometry.points[f.start].world_receiver);
    for(int64_t i=0;i<f.count;++i){const auto& p=geometry.points[f.start+i];Vec a=load3(p.world_receiver),b=load3(p.world_provider);
        Vec v=ly_project(sub(a,origin),frame);v.z=dot(sub(b,a),d);poly.push_back(v);}return poly;
}
static void accumulate(Order& out,const Fragment& f,const Result& geometry,const Session& bases,double& incompatible) {
    const auto& a=bases.sides[f.receiver];const auto& b=bases.sides[f.provider];int side=a.id==out.first?0:1;
    Vec d=mean_direction(a,int(f.receiver_face));auto poly=depth_polygon(f,geometry,d);double area=fixed_area(poly);
    if(area<=0)return;double scale=f.area/area,lo=INFINITY,hi=-INFINITY;
    double positive=scale*fixed_area(fixed_clip(poly,[](Vec p){return p.z-1e-6;}));
    double negative=scale*fixed_area(fixed_clip(poly,[](Vec p){return -p.z-1e-6;}));
    out.positive[side]+=positive;out.negative[side]+=negative;
    for(Vec p:poly){lo=std::min(lo,p.z);hi=std::max(hi,p.z);}
    out.minimum=std::min(out.minimum,lo);out.maximum=std::max(out.maximum,hi);
    if(lo>=-1e-6&&hi<=1e-6)out.coincident+=f.area;
    if(dot(d,mean_direction(b,int(f.provider_face)))<0)incompatible+=positive;
    if(lo<-1e-6&&hi>1e-6)++out.crossings;
}
static OrderStatus classify(Order& out,double incompatible,double area) {
    if(out.crossings)return OrderStatus::intersecting;
    if(out.coincident>area)return OrderStatus::coincident;
    if(out.positive[0]>area&&out.positive[1]>area)return OrderStatus::conflicting;
    if(incompatible>area)return OrderStatus::incompatible;
    if(out.warnings)return OrderStatus::projection;
    if(out.positive[0]<=area&&out.positive[1]<=area)return OrderStatus::no_upward;
    out.underlying=out.positive[0]>area?out.first:out.second;out.covering=out.underlying==out.first?out.second:out.first;
    return OrderStatus::supported;
}
static double extent(const Side& a,const Side& b);
static std::shared_ptr<Result> order_geometry(const Session& bases,int a,int b,std::atomic<bool>& cancelled,bool exhaustive=false,uint64_t retained=0) {
    auto settings=bases.settings;settings.search=extent(bases.sides[a],bases.sides[b]);auto out=std::make_shared<Result>();
    require(retained<=settings.result_bytes,"LAYER_RESULT_BUDGET");
    Budget budget;budget.cancelled=&cancelled;budget.max_bytes=settings.result_bytes-retained;budget.max_fragments=settings.limit;
    map_direction(bases,a,b,*out,budget,exhaustive,&settings);map_direction(bases,b,a,*out,budget,exhaustive,&settings);
    out->allocation_peak=budget.peak.load();return out;
}
static Evidence resolve(const Session& bases,int a,int b,std::atomic<bool>& cancelled,bool exhaustive=false) {
    Evidence out;auto& order=out.summary;
    order.first=bases.sides[a].id;order.second=bases.sides[b].id;double incompatible=0;
    out.geometry=order_geometry(bases,a,b,cancelled,exhaustive);
    order.warnings=int(out.geometry->stats[4]);
    for(const auto& f:out.geometry->fragments){accumulate(order,f,*out.geometry,bases,incompatible);
        if(dot(mean_direction(bases.sides[f.receiver],int(f.receiver_face)),mean_direction(bases.sides[f.provider],int(f.provider_face)))<0)out.compatible=false;}
    order.crossings+=crossing_count(bases.sides[a],bases.sides[b],cancelled);
    order.status=int(classify(order,incompatible,bases.settings.area));
    order.fragments=out.geometry->fragments.size();order.points=out.geometry->points.size();return out;
}
static double extent(const Side& a,const Side& b) {
    Vec low{INFINITY,INFINITY,INFINITY},high{-INFINITY,-INFINITY,-INFINITY};
    for(const auto* side:{&a,&b})for(Vec p:side->base)for(int j=0;j<3;++j){
        (&low.x)[j]=std::min((&low.x)[j],(&p.x)[j]);(&high.x)[j]=std::max((&high.x)[j],(&p.x)[j]);}
    return norm(sub(high,low))+1e-6;
}
static Evidence safe_resolve(const Session& bases,int a,int b,std::atomic<bool>& cancelled) {
    try{return resolve(bases,a,b,cancelled);}
    catch(const std::invalid_argument& error){std::string text=error.what();
        if(cancelled||text.find("BUDGET")!=std::string::npos)throw;
        Evidence value;value.summary.first=bases.sides[a].id;value.summary.second=bases.sides[b].id;
        value.summary.status=int(OrderStatus::projection);value.summary.warnings=1;
        std::memcpy(value.summary.diagnostic,text.data(),std::min(text.size(),sizeof(value.summary.diagnostic)-1));return value;}
}
static Evidence cached_order(State& state,uint64_t a,uint64_t b,std::atomic<bool>& cancelled) {
    int ai=state.bases.indices.at(a),bi=state.bases.indices.at(b);auto& sa=state.bases.sides[ai];auto& sb=state.bases.sides[bi];
    auto key=std::make_pair(a,b);auto it=state.cache.find(key);
    if(it!=state.cache.end()&&it->second.a==sa.revision&&it->second.b==sb.revision){
        it->second.used=++state.clock;++state.order_reused;return {it->second.summary,{},it->second.compatible};}
    auto result=safe_resolve(state.bases,ai,bi,cancelled);++state.order_computed;
    if(result.geometry)state.order_peak=std::max(state.order_peak,result.geometry->allocation_peak);
    state.cache[key]={sa.revision,sb.revision,++state.clock,result.summary,result.compatible};result.geometry.reset();return result;
}
static uint64_t order_cache_bytes(const State& state){return state.cache.size()*(sizeof(CachedOrder)+64);}
static void evict_orders(State& state) {
    while(order_cache_bytes(state)>state.bases.settings.cache_bytes&&!state.cache.empty()){
        auto oldest=std::min_element(state.cache.begin(),state.cache.end(),[](const auto& a,const auto& b){return a.second.used<b.second.used;});
        state.cache.erase(oldest);}
}
static void order_pairs(State& state,Session& detection,std::atomic<bool>& cancelled) {
    auto start=Clock::now();std::vector<Side> incoming;std::set<std::pair<uint64_t,uint64_t>> live;
    for(const auto& side:detection.sides)if(side.id)incoming.push_back(base_copy(side));
    if(state.bases.settings.area!=detection.settings.area||state.bases.settings.epsilon!=detection.settings.epsilon)state.cache.clear();
    synchronize(state.bases,incoming,detection.settings);state.orders.clear();state.order_peak=state.order_computed=state.order_reused=0;
    require(detection.published.pairs.size()*sizeof(Evidence)<=detection.settings.result_bytes,"LAYER_RESULT_BUDGET");
    state.orders.reserve(detection.published.pairs.size());
    for(const auto& pair:detection.published.pairs){auto key=std::minmax(uint64_t(pair.first),uint64_t(pair.second));live.emplace(pair.first,pair.second);
        bool explicit_pair=state.policies.count(key)&&state.policies.at(key).mode==2;
        Evidence value;if((!pair.count&&!explicit_pair)||state.exclusions.count(key)){value.summary.first=pair.first;value.summary.second=pair.second;value.summary.status=int(state.exclusions.count(key)?OrderStatus::excluded:OrderStatus::no_upward);}
        else value=cached_order(state,pair.first,pair.second,cancelled);
        state.orders.push_back(value);}
    for(auto it=state.cache.begin();it!=state.cache.end();)if(!live.count(it->first))it=state.cache.erase(it);else ++it;
    evict_orders(state);state.order_ms=milliseconds(start);
}
}

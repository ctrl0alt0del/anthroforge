#pragma once
namespace af_stack_vector {
using Adjacency=std::vector<std::vector<std::pair<double,int>>>;
struct Locality { std::vector<double> distance;afs::Vector weight,falloff; };
static Adjacency adjacency(const afs::Mesh& mesh) {
    Adjacency graph(mesh.vertices.rows());std::set<std::pair<int,int>> edges;
    for(int f=0;f<mesh.faces.rows();++f)for(int j=0;j<3;++j)edges.insert(std::minmax(mesh.faces(f,j),mesh.faces(f,(j+1)%3)));
    for(auto [a,b]:edges){double d=(mesh.vertices.row(a)-mesh.vertices.row(b)).norm();graph[a].push_back({d,b});graph[b].push_back({d,a});}return graph;
}
static FixedPolygon clipped_bary(FixedPolygon poly,const Mask& mask) {
    double sign=0;for(size_t j=0;j<mask.barycentrics.size();++j){auto a=mask.barycentrics[j],b=mask.barycentrics[(j+1)%mask.barycentrics.size()];sign+=a.y*b.z-a.z*b.y;}
    for(size_t j=0;j<mask.barycentrics.size();++j){auto a=mask.barycentrics[j],b=mask.barycentrics[(j+1)%mask.barycentrics.size()];
        poly=fixed_clip(poly,[&](Vec p){return (sign<0?-1:1)*((b.y-a.y)*(p.z-a.z)-(b.z-a.z)*(p.y-a.y));},1e-12);}return poly;
}
static Result base_footprint(const Side& under,const Side& cover,std::atomic<bool>& cancel) {
    auto a=surface_copy(under,under.base),b=surface_copy(cover,cover.base);Session s;auto config=s.settings;config.search=extent(under,cover)*4;
    std::vector<Side> values;values.push_back(std::move(a));values.push_back(std::move(b));synchronize(s,values,config);
    Result out;Budget budget;budget.cancelled=&cancel;budget.max_bytes=config.result_bytes;budget.max_fragments=config.limit;
    map_direction(s,0,1,out,budget,false);require(out.stats[4]==0,"STACK_FOOTPRINT_PROJECTION_FAILED");return out;
}
static void seed_polygon(const Side& cover,int f,const FixedPolygon& poly,std::vector<double>& distance) {
    Vec tri[3];face(cover,f,tri);
    for(int j=0;j<3;++j){int v=int(cover.faces[3*f+j]);
        for(size_t k=1;k+1<poly.size();++k){Vec points[3]={weighted(tri,poly[0]),weighted(tri,poly[k]),weighted(tri,poly[k+1])};
            distance[v]=std::min(distance[v],point_triangle(cover.base[v],points));}}
}
static std::vector<double> seeds(const Side& cover,const std::vector<Provider>& providers,std::atomic<bool>& cancel) {
    std::vector<double> distance(cover.base.size(),INFINITY);
    for(const auto& p:providers){auto footprint=base_footprint(p.side,cover,cancel);std::map<int,std::vector<const Mask*>> masks;
        for(const auto& m:p.masks)masks[m.face].push_back(&m);
        for(const auto& f:footprint.fragments){FixedPolygon poly;for(int64_t j=0;j<f.count;++j)poly.push_back(load3(footprint.points[f.start+j].provider));
            for(auto m:masks[int(f.provider_face)])seed_polygon(cover,int(f.provider_face),clipped_bary(poly,*m),distance);}}
    return distance;
}
static void spread(const Adjacency& graph,std::vector<double>& distance,std::atomic<bool>& cancel) {
    using Item=std::pair<double,int>;std::priority_queue<Item,std::vector<Item>,std::greater<Item>> pending;
    for(int i=0;i<int(distance.size());++i)if(std::isfinite(distance[i]))pending.push({distance[i],i});
    while(!pending.empty()){require(!cancel,"PAIR_CANCELLED");auto [d,i]=pending.top();pending.pop();if(d!=distance[i])continue;
        for(auto [length,j]:graph[i])if(d+length<distance[j]){distance[j]=d+length;pending.push({distance[j],j});}}
}
static std::vector<int> component(const Adjacency& graph,const afs::Vector& amount,int start,std::vector<bool>& seen) {
    std::vector<int> ids{start};seen[start]=true;
    for(size_t k=0;k<ids.size();++k)for(auto [length,j]:graph[ids[k]])if(!seen[j]&&amount[j]>1e-9){seen[j]=true;ids.push_back(j);}return ids;
}
static double percentile(const std::vector<int>& ids,const afs::Vector& amount,const afs::Vector& mass) {
    std::vector<std::pair<double,double>> sorted;double total=0;
    for(int i:ids){sorted.push_back({amount[i],mass[i]});total+=mass[i];}std::sort(sorted.begin(),sorted.end());double sum=0;
    for(auto [height,area]:sorted){sum+=area;if(sum>=.9*total)return height;}return sorted.back().first;
}
static afs::Vector preservation(const Adjacency& graph,const Mat& raw,const afs::Vector& mass,double maximum) {
    afs::Vector amount=raw.rowwise().norm(),weights=afs::Vector::Ones(raw.rows());std::vector<bool> seen(raw.rows(),false);
    for(int i=0;i<raw.rows();++i)if(!seen[i]&&amount[i]>1e-9){auto ids=component(graph,amount,i,seen);double ref=percentile(ids,amount,mass);
        for(int j:ids){double t=std::min(1.,amount[j]/ref);weights[j]=1+(maximum-1)*t*t;}}return weights;
}
static double falloff(double distance,double radius) {
    if(radius==0)return distance<=1e-9?1:0;double t=std::clamp(distance/radius,0.,1.);return 1-t*t*(3-2*t);
}
static Locality locality(const Side& side,const Layout& l,const std::vector<Provider>& p,const Mat& raw,const afs::Energy& e,const State& state,std::atomic<bool>& cancel) {
    Locality out;out.distance=seeds(side,p,cancel);auto graph=adjacency(l.mesh);
    for(int i=0;i<raw.rows();++i)if(raw.row(i).norm()>1e-9)out.distance[i]=0;spread(graph,out.distance,cancel);
    out.weight=preservation(graph,raw,e.mass,state.vector_settings.preservation);out.falloff.resize(raw.rows());
    for(int i=0;i<raw.rows();++i)out.falloff[i]=falloff(out.distance[i],state.vector_settings.blend);return out;
}
static void mask_signature(std::string& key,const std::vector<Provider>& providers) {
    auto count=providers.size();append_signature(key,&count,1);
    for(const auto& p:providers){append_signature(key,&p.side.id,1);append_signature(key,p.side.base);
        append_signature(key,p.side.direction);append_signature(key,p.side.faces);auto size=p.masks.size();append_signature(key,&size,1);
        for(const auto& m:p.masks){append_signature(key,&m.face,1);append_signature(key,m.barycentrics);}}
}
static std::shared_ptr<Locality> cached_locality(const Side& side,const Layout& l,const std::vector<Provider>& p,const Mat& raw,const afs::Energy& e,const State& state,std::atomic<bool>& cancel) {
    std::string key="vector-locality-v1";append_signature(key,side.base);append_signature(key,side.faces);append_signature(key,side.direction);
    append_dense(key,raw);append_dense(key,e.mass);mask_signature(key,p);
    append_signature(key,&state.vector_settings.blend,1);append_signature(key,&state.vector_settings.preservation,1);
    CacheKey id{2,side.id,0};auto out=state.vector_cache->find<Locality>(id,key);if(out)return out;
    out=std::make_shared<Locality>(locality(side,l,p,raw,e,state,cancel));
    state.vector_cache->put(id,std::move(key),out,sizeof(Locality)+out->distance.capacity()*sizeof(double)+2*out->weight.size()*sizeof(double),state.bases.settings.cache_bytes);
    return out;
}
}

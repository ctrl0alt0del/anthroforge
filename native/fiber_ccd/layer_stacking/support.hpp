#pragma once
namespace af_layer {
struct Mask { uint64_t provider;int face;std::vector<Vec> barycentrics; };
static void append_mask(std::vector<Mask>& masks,const Result& raw,const Fragment& f,uint64_t provider,uint64_t& used,uint64_t limit) {
    auto count=masks.size()==masks.capacity()?masks.capacity()+masks.capacity()/2+8:masks.capacity();auto polygon=uint64_t(f.count)*sizeof(Vec);
    auto previous=count==masks.capacity()?0:masks.capacity()*sizeof(Mask);
    require(used+count*sizeof(Mask)+previous+polygon+bytes(raw)<=limit,"STACK_MASK_MEMORY_BUDGET");
    masks.reserve(count);Mask mask{provider,int(f.provider_face),{}};mask.barycentrics.reserve(f.count);
    for(int64_t i=0;i<f.count;++i)mask.barycentrics.push_back(load3(raw.points[f.start+i].provider));
    used+=mask.barycentrics.capacity()*sizeof(Vec);masks.push_back(std::move(mask));
}
static std::vector<Mask> material_masks(const State& state,uint64_t cover,std::atomic<bool>& cancelled) {
    std::vector<Mask> result;uint64_t used=0;
    for(const auto& order:state.orders){const auto& o=order.summary;if(o.status!=0||o.covering!=cover)continue;
        if(!policy_allowed(state,o.first,o.second))continue;
        auto geometry=order_geometry(state.bases,state.bases.indices.at(o.first),state.bases.indices.at(o.second),cancelled,false,used+result.capacity()*sizeof(Mask));const auto& raw=*geometry;
        for(const auto& f:raw.fragments){if(state.bases.sides[f.receiver].id!=o.underlying||f.gap_max<=1e-6)continue;
            if(!selected_material(state,cover,o.underlying,int(f.provider_face)))continue;
            append_mask(result,raw,f,o.underlying,used,state.bases.settings.result_bytes);}}
    return result;
}
static FixedPolygon clip_material(FixedPolygon poly,const Query& q,const Mask& mask) {
    FixedPolygon region;for(Vec bary:mask.barycentrics)region.push_back(weighted(q.projected,bary));
    double area=0;for(size_t j=0;j<region.size();++j)area+=ly_cross(region[j],region[(j+1)%region.size()]);
    for(size_t j=0;j<region.size();++j){Vec a=region[j],edge=sub(region[(j+1)%region.size()],a);
        poly=fixed_clip(poly,[&](Vec p){return (area>0?1:-1)*ly_cross(edge,sub(p,a));},1e-12);}return poly;
}
static afs::Row support_row(Vec point,const Query& q,const ProviderChart& p,const Side& original,const Material& material,double clearance,int provider) {
    Vec w=cached_bary(point,q.projected,q.denominator),n=cross(sub(p.world[1],p.world[0]),sub(p.world[2],p.world[0]));
    double den=dot(n,q.frame.d);require(std::abs(den)>1e-10*norm(n),"STACK_PROJECTION_DEGENERATE");
    // Support the virtual carrier B+b*d; preserve Xown-B when publishing the final surface.
    Vec base{};std::map<int,double> terms;
    for(int j=0;j<3;++j){int vertex=int(original.faces[q.rf*3+j]);double weight=(&w.x)[j];
        base=add(base,mul(sub(original.base[vertex],q.origin),weight));
        interpolate_terms(terms,material,vertex,weight*dot(n,original.direction[vertex])/den);}
    afs::Row row;row.lower=dot(n,sub(p.world[0],base))/den+clearance;row.provider=provider;row.face=q.rf;
    for(auto term:terms)if(std::abs(term.second)>1e-15)row.terms.push_back(term);return row;
}
static void support_triangle(const Query& q,int face,const Mask& mask,const Side& original,const Material& material,double clearance,std::vector<afs::Row>& rows) {
    ProviderChart provider;snapshot_face(*q.provider.snapshot,face,provider.world);
    for(int j=0;j<3;++j){provider.world[j]=sub(provider.world[j],q.origin);provider.projected[j]=ly_project(provider.world[j],q.frame);}
    auto poly=clip_material(fast_overlap(q,provider),q,mask);
    if(poly.size()<3||fixed_area(poly)<=q.settings.area)return;
    for(Vec point:poly)rows.push_back(support_row(point,q,provider,original,material,clearance,int(mask.provider)));
}
class SupportSource final : public afs::ConstraintSource {
    const Side& original_;const Material& material_;const State& state_;std::atomic<bool>& cancelled_;
    std::vector<Mask> masks_;std::map<uint64_t,Side> providers_;
    void map_mask(const Side& receiver,const Mask& mask,std::vector<afs::Row>& rows);
public:
    SupportSource(const Side& side,const Material& material,const State& state,std::atomic<bool>& cancelled);
    std::vector<afs::Row> map(const afs::Vector& bonus) override;
};
SupportSource::SupportSource(const Side& side,const Material& material,const State& state,std::atomic<bool>& cancelled)
    :original_(side),material_(material),state_(state),cancelled_(cancelled),masks_(material_masks(state,side.id,cancelled)) {
    for(const auto& mask:masks_)if(!providers_.count(mask.provider)){
        const auto& source=state.bases.sides[state.bases.indices.at(mask.provider)];Side provider=base_copy(source);
        provider.own=state.outputs.at(mask.provider).points;prepare_snapshot(provider,nullptr);providers_.emplace(mask.provider,std::move(provider));}
}
void SupportSource::map_mask(const Side& receiver,const Mask& mask,std::vector<afs::Row>& rows) {
    require(!cancelled_,"PAIR_CANCELLED");const auto& provider=providers_.at(mask.provider);auto settings=state_.bases.settings;
    settings.search=extent(receiver,provider)+state_.settings.maximum;Result diagnostics;
    Query q{receiver,provider,settings,0,0,mask.face,{}, {}};std::vector<int> candidates;
    require(prepare(q,diagnostics),"STACK_RECEIVER_PROJECTION_FAILED");cache_chart(q);find_faces(q,false,candidates);
    for(int face:candidates)support_triangle(q,face,mask,original_,material_,state_.settings.clearance,rows);
    require(rows.size()<=size_t(settings.limit),"STACK_CONSTRAINT_BUDGET");
    size_t bytes=rows.capacity()*sizeof(afs::Row);for(const auto& row:rows)bytes+=row.terms.capacity()*sizeof(std::pair<int,double>);
    require(bytes<=settings.result_bytes,"STACK_CONSTRAINT_MEMORY_BUDGET");
}
std::vector<afs::Row> SupportSource::map(const afs::Vector& bonus) {
    Side receiver=base_copy(original_);receiver.base=displaced(original_,material_,bonus);receiver.own=receiver.base;
    std::vector<afs::Row> rows;for(const auto& mask:masks_)map_mask(receiver,mask,rows);return rows;
}
}

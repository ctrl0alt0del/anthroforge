#pragma once
namespace af_pair {
struct FixedPolygon {
    std::array<Vec,32> points; size_t count=0;
    size_t size() const { return count; }
    bool empty() const { return count==0; }
    const Vec* begin() const { return points.data(); }
    const Vec* end() const { return points.data()+count; }
    Vec back() const { return points[count-1]; }
    Vec operator[](size_t i) const { return points[i]; }
    void push_back(Vec p) { require(count<points.size(),"clipping capacity exceeded");points[count++]=p; }
};
struct FixedPieces { std::array<FixedPolygon,2> values; int count=0; };
struct ProviderChart { Vec world[3],projected[3]; };
static Vec cached_bary(Vec p,const Vec* r,double denominator) {
    Vec e=sub(r[1],r[0]),f=sub(r[2],r[0]),q=sub(p,r[0]);
    double v=ly_cross(q,f)/denominator,w=ly_cross(e,q)/denominator;return {1-v-w,v,w};
}
static void cache_chart(Query& q) {
    for(int i=0;i<3;++i){q.projected[i]=ly_project(q.triangle[i],q.frame);
        q.own[i]=sub(q.receiver.own[q.receiver.faces[q.rf*3+i]],q.origin);}
    q.denominator=ly_cross(sub(q.projected[1],q.projected[0]),sub(q.projected[2],q.projected[0]));
}
static double fast_height(Vec p,const Query& q) {
    Vec w=cached_bary(p,q.projected,q.denominator);
    return dot(sub(weighted(q.own,w),weighted(q.triangle,w)),q.frame.d);
}
static double fast_gap(Vec p,const Query& q) {
    return p.z-dot(weighted(q.triangle,cached_bary(p,q.projected,q.denominator)),q.frame.d);
}
template<class Value> static FixedPolygon fixed_clip(const FixedPolygon& poly,Value value,double tolerance=0) {
    FixedPolygon result;if(poly.empty())return result;Vec old=poly.back();double ov=value(old);
    for(Vec p:poly){double current=value(p);
        if((current>=0)!=(ov>=0)){double t=ov/(ov-current);result.push_back(add(old,mul(sub(p,old),t)));}
        if(current>=-tolerance)result.push_back(p);old=p;ov=current;}return result;
}
static FixedPolygon fast_affine(const FixedPolygon& poly,const Query& q,Vec coefficients) {
    return fixed_clip(poly,[&](Vec p){double value=coefficients.z;
        if(coefficients.x!=0)value+=coefficients.x*fast_gap(p,q);
        if(coefficients.y!=0)value+=coefficients.y*fast_height(p,q);return value;});
}
static FixedPolygon fast_overlap(const Query& q,const ProviderChart& p) {
    FixedPolygon poly;for(Vec v:p.projected)poly.push_back(v);
    if(std::abs(q.denominator)<1e-14)return {};
    for(int i=0;i<3;++i){Vec a=q.projected[i],delta=sub(q.projected[(i+1)%3],a);
        double sign=q.denominator>0?1:-1;
        poly=fixed_clip(poly,[&](Vec v){return sign*ly_cross(delta,sub(v,a));},1e-12);}return poly;
}
static FixedPieces fast_reachable(FixedPolygon poly,const Query& q) {
    double low=-q.settings.search-q.provider.displacement;
    double high=q.settings.search+q.receiver.displacement+q.provider.displacement;
    poly=fast_affine(poly,q,{1,0,-low});double lo=INFINITY,hi=-INFINITY;FixedPieces out;
    for(Vec p:poly){double h=fast_height(p,q);lo=std::min(lo,h);hi=std::max(hi,h);}
    out.count=1;
    if(lo>=0){out.values[0]=fast_affine(poly,q,{-1,1,high});return out;}
    if(hi<=0){out.values[0]=fast_affine(poly,q,{-1,0,high});return out;}
    out.count=2;out.values[0]=fast_affine(fast_affine(poly,q,{0,1,0}),q,{-1,1,high});
    out.values[1]=fast_affine(fast_affine(poly,q,{0,-1,0}),q,{-1,0,high});return out;
}
static double fixed_area(const FixedPolygon& poly) {
    double area=0;for(size_t i=0;i<poly.size();++i)area+=ly_cross(poly[i],poly[(i+1)%poly.size()]);return std::abs(area)*.5;
}
static Point fast_point(Vec p,const Query& q,const ProviderChart& provider) {
    Point out{};double den=ly_cross(sub(provider.projected[1],provider.projected[0]),sub(provider.projected[2],provider.projected[0]));
    Vec rw=cached_bary(p,q.projected,q.denominator),pw=cached_bary(p,provider.projected,den);
    Vec r=add(weighted(q.triangle,rw),q.origin),v=add(weighted(provider.world,pw),q.origin);
    std::memcpy(out.receiver,&rw,sizeof(Vec));std::memcpy(out.provider,&pw,sizeof(Vec));
    std::memcpy(out.world_receiver,&r,sizeof(Vec));std::memcpy(out.world_provider,&v,sizeof(Vec));return out;
}
static void fast_emit(const FixedPolygon& poly,const Query& q,const ProviderChart& p,int pf,Result& out) {
    reserve_fragment(out,poly.size(),*q.budget);
    double lo=INFINITY,hi=-INFINITY;Vec n=af_env_unit(cross(sub(p.world[1],p.world[0]),sub(p.world[2],p.world[0])));
    Vec normal=cross(sub(q.triangle[1],q.triangle[0]),sub(q.triangle[2],q.triangle[0]));
    double jac=norm(normal),projected=std::abs(dot(normal,q.frame.d));auto start=out.points.size();
    for(Vec pnt:poly){lo=std::min(lo,fast_gap(pnt,q));hi=std::max(hi,fast_gap(pnt,q));out.points.push_back(fast_point(pnt,q,p));}
    out.fragments.push_back({q.r,q.p,q.rf,pf,int64_t(start),int64_t(poly.size()),fixed_area(poly)*jac/projected,lo,hi,dot(n,q.frame.d)});
}
static void map_fast(const Query& q,int pf,Result& out) {
    ProviderChart p{};snapshot_face(*q.provider.snapshot,pf,p.world);++out.stats[3];
    for(int i=0;i<3;++i){p.world[i]=sub(p.world[i],q.origin);p.projected[i]=ly_project(p.world[i],q.frame);}
    if(q.gate&&outside_edges(q,p.world)){++out.profile[2];return;}
    auto poly=fast_overlap(q,p);bool empty=poly.size()<3||fixed_area(poly)<=q.settings.area;
    out.profile[3]+=empty;auto count=out.fragments.size();auto pieces=fast_reachable(poly,q);
    for(int i=0;i<pieces.count;++i){const auto& fragment=pieces.values[i];
        if(fragment.size()<3||fixed_area(fragment)<=q.settings.area)continue;fast_emit(fragment,q,p,pf,out);}
    out.profile[4]+=!empty&&count==out.fragments.size();
}
}

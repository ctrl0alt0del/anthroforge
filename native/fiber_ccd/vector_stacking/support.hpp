#pragma once
namespace af_stack_vector {
static afs::Row plane_row(Vec point,const Query& q,const ProviderChart& p,int f,const Side& cover,const Layout& l) {
    double den=ly_cross(sub(p.projected[1],p.projected[0]),sub(p.projected[2],p.projected[0]));Vec w=cached_bary(point,p.projected,den);
    Vec normal=cross(sub(q.triangle[1],q.triangle[0]),sub(q.triangle[2],q.triangle[0]));normal=mul(normal,(dot(normal,q.frame.d)<0?-1.:1.)/norm(normal));
    afs::Row row;row.lower=dot(normal,add(q.triangle[0],q.origin));row.face=f;row.provider=q.rf;std::map<int,double> terms;
    const auto& sample=l.sample_rows;
    for(int j=0;j<3;++j){int v=int(cover.faces[3*f+j]);double weight=(&w.x)[j];row.lower-=weight*dot(normal,cover.own[v]);
        for(int c=0;c<3;++c)for(Eigen::SparseMatrix<double,Eigen::RowMajor>::InnerIterator t(sample,3*v+c);t;++t)terms[t.col()]+=weight*(&normal.x)[c]*t.value();}
    for(auto [id,value]:terms)if(std::abs(value)>1e-15)row.terms.emplace_back(id,value);return row;
}
static FixedPolygon restrict_overlap(FixedPolygon poly,const Query& q,const ProviderChart& p,const Mask& mask) {
    FixedPolygon bary;double den=ly_cross(sub(p.projected[1],p.projected[0]),sub(p.projected[2],p.projected[0]));
    for(auto point:poly)bary.push_back(cached_bary(point,p.projected,den));bary=clipped_bary(bary,mask);poly.count=0;
    for(auto point:bary)poly.push_back(weighted(p.projected,point));return poly;
}
static void triangle_rows(const Query& q,int f,const Mask& mask,const Side& cover,const Layout& l,double clearance,std::vector<afs::Row>& rows) {
    ProviderChart p;snapshot_face(*q.provider.snapshot,f,p.world);
    for(int j=0;j<3;++j){p.world[j]=sub(p.world[j],q.origin);p.projected[j]=ly_project(p.world[j],q.frame);}
    auto poly=restrict_overlap(fast_overlap(q,p),q,p,mask);if(poly.size()<3||fixed_area(poly)<=q.settings.area)return;
    for(auto point:poly){auto row=plane_row(point,q,p,f,cover,l);row.lower+=clearance;rows.push_back(std::move(row));}
}
static void map_provider(const Provider& provider,const Side& target,const Side& cover,const Layout& l,const State& state,std::vector<afs::Row>& rows,std::atomic<bool>& cancel) {
    auto source=surface_copy(provider.side,provider.side.own);auto config=state.bases.settings;config.search=extent(source,target)*4;Result diagnostics;
    std::map<int,std::vector<const Mask*>> masks;for(const auto& m:provider.masks)masks[m.face].push_back(&m);
    for(int f=0;f<int(source.faces.size()/3);++f){require(!cancel,"PAIR_CANCELLED");Query q{source,target,config,0,1,f,{}, {}};
        require(prepare(q,diagnostics),"STACK_VECTOR_SUPPORT_PROJECTION_FAILED");cache_chart(q);std::vector<int> candidates;find_faces(q,false,candidates);
        for(int face:candidates)for(auto mask:masks[face])triangle_rows(q,face,*mask,cover,l,state.settings.clearance,rows);
        require(rows.size()<=size_t(config.limit),"STACK_CONSTRAINT_BUDGET");}
    size_t bytes=rows.capacity()*sizeof(afs::Row);for(const auto& row:rows)bytes+=row.terms.capacity()*sizeof(std::pair<int,double>);
    require(bytes<=config.result_bytes,"STACK_CONSTRAINT_MEMORY_BUDGET");
}
static std::vector<afs::Row> support_rows(const Side& cover,const Layout& l,const std::vector<Provider>& providers,const std::vector<Vec>& current,const State& state,std::atomic<bool>& cancel) {
    auto target=surface_copy(cover,current);std::vector<afs::Row> rows;
    for(const auto& p:providers)map_provider(p,target,cover,l,state,rows,cancel);return unique_support(std::move(rows));
}
}

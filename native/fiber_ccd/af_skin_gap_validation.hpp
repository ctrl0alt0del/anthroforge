#pragma once
namespace af_skin {
// Numerical surface classification only: this is not a minimum air-gap radius.
inline double gap_boundary_tolerance(const TriangleSnapshot& mesh,Vec p) {
    const auto& b=mesh.nodes[0].bounds;
    double span=std::max({b.hi[0]-b.lo[0],b.hi[1]-b.lo[1],b.hi[2]-b.lo[2]});
    double coordinate=std::max({std::abs(p.x),std::abs(p.y),std::abs(p.z)});
    return std::max(64*std::numeric_limits<double>::epsilon()*span,
                    2*std::numeric_limits<float>::epsilon()*coordinate);
}
inline bool gap_point_buried(const TriangleSnapshot& mesh,Vec p,double distance) {
    if(distance<=gap_boundary_tolerance(mesh,p))return false;
    return snapshot_inside(mesh,p,0,int(mesh.triangles.size()/3));
}
inline void corridor_coverage(const TriangleSnapshot& output,const SkinTiles& tiles,double* stats) {
    int failed=0; double minimum=INFINITY; int count=int(tiles.corridor_checks.size());
#pragma omp parallel for reduction(+:failed) reduction(min:minimum) schedule(static) num_threads(af_parallel_workers(count))
    for(int i=0;i<count;++i) {
        if(tiles.scene->cancelled)continue; Vec p=tiles.corridor_checks[i]; Hit hit; nearest_node(output,p,0,hit);
        minimum=std::min(minimum,hit.distance);
        if(gap_point_buried(output,p,hit.distance))++failed;
    }
    tile_cancelled(tiles); stats[4]+=count; stats[5]+=failed;
    if(count)stats[6]=stats[4]>count?std::min(stats[6],minimum):minimum;
}
inline void gap_coverage(const TriangleSnapshot& output,const SkinTiles& tiles,double* stats) {
    int checked=0,failed=0; double minimum=INFINITY; int count=int(tiles.separators.items.size());
#pragma omp parallel for reduction(+:checked,failed) reduction(min:minimum) schedule(static) num_threads(af_parallel_workers(count))
    for(int i=0;i<count;++i) { const auto& s=tiles.separators.items[i]; if(s.strength>0 || tiles.scene->cancelled)continue;
        Hit hit; nearest_node(output,s.center,0,hit); ++checked; minimum=std::min(minimum,hit.distance);
        if(gap_point_buried(output,s.center,hit.distance))++failed; }
    tile_cancelled(tiles); stats[4]=checked; stats[5]=failed; stats[6]=checked?minimum:0;
    corridor_coverage(output,tiles,stats);
}
inline bool crossing_edge(Vec a,Vec b,const Vec* triangle) {
    Vec d=sub(b,a); double length=norm(d); if(length<1.e-9)return false;
    double distance=ray_parameter(a,mul(d,1/length),triangle);
    return distance>1.e-8*length && distance<length*(1-1.e-8);
}
inline bool shared_vertex(const TriangleSnapshot& mesh,int a,int b) {
    for(int i=0;i<3;++i)for(int j=0;j<3;++j)
        if(mesh.triangles[size_t(a)*3+i]==mesh.triangles[size_t(b)*3+j])return true;
    return false;
}
inline int source_face_intersections(const GapScene& source,int index) {
    std::vector<int> candidates; const auto& mesh=*source.mesh; Vec a[3]; snapshot_face(mesh,index,a);
    collect_candidates(mesh,0,mesh.indexed_faces[index],candidates); int count=0;
    for(int face:candidates) {
        if(face<=index || shared_vertex(mesh,index,face))continue; Vec b[3]; snapshot_face(mesh,face,b); bool crossing=false;
        for(int j=0;j<3 && !crossing;++j)crossing=crossing_edge(a[j],a[(j+1)%3],b)||crossing_edge(b[j],b[(j+1)%3],a);
        if(crossing)++count;
    }
    return count;
}
inline void tile_statistics(const SkinTiles& t,double* out) {
    std::fill(out,out+8,0.); out[0]=double(t.coordinates.size()); out[1]=double(t.surface_tiles.size());
    out[2]=double(t.values.size()); out[3]=double(t.values.bytes()+t.separators.items.size()*sizeof(Separator));
    out[4]=double(t.separators.items.size()); out[5]=INFINITY;
    for(const auto& s:t.separators.items)if(s.strength==0) { out[5]=std::min(out[5],s.width); ++out[6]; }
    if(!out[6])out[5]=0;
    out[7]=double(size_t(t.grid.nx)*t.grid.ny*t.grid.nz);
}
}
AF_EXPORT int af_skin_tiles_validate(void* tiles,const double* vertices,int count,const int64_t* faces,int triangles,double* stats) {
    if(!tiles || !af_skin::finish_valid(vertices,count,faces,triangles) || !stats)return 1;
    try {
        const auto& t=*static_cast<af_skin::SkinTiles*>(tiles); std::unique_ptr<TriangleSnapshot> mesh(create_snapshot(vertices,faces,triangles,false));
        af_skin::source_coverage(*mesh,*t.scene,t.grid.h*.001,stats); af_skin::gap_coverage(*mesh,t,stats); return 0;
    } catch(...) { return 2; }
}
AF_EXPORT int af_skin_gap_validation_version() { return 2; }
AF_EXPORT int af_skin_validate_gap_points(const double* vertices,int count,const int64_t* faces,int triangles,
                                         const double* points,int samples,double* rows) {
    if(!af_skin::finish_valid(vertices,count,faces,triangles) || !points || samples<0 || !rows)return 1;
    for(int i=0;i<3*samples;++i)if(!std::isfinite(points[i]))return 1;
    try {
        std::unique_ptr<TriangleSnapshot> mesh(create_snapshot(vertices,faces,triangles,false));
#pragma omp parallel for schedule(static) num_threads(af_parallel_workers(samples))
        for(int i=0;i<samples;++i) { Vec p=load3(points+3*i); af_skin::Hit hit; af_skin::nearest_node(*mesh,p,0,hit);
            rows[3*i]=hit.distance; rows[3*i+1]=af_skin::gap_point_buried(*mesh,p,hit.distance);
            rows[3*i+2]=af_skin::gap_boundary_tolerance(*mesh,p); }
        return 0;
    } catch(...) { return 2; }
}
AF_EXPORT int af_skin_tiles_statistics(void* tiles,double* stats) {
    if(!tiles || !stats)return 1; af_skin::tile_statistics(*static_cast<af_skin::SkinTiles*>(tiles),stats); return 0;
}
AF_EXPORT int af_skin_tiles_memory_statistics(void* tiles,double* out) {
    if(!tiles || !out)return 1; const auto& t=*static_cast<af_skin::SkinTiles*>(tiles);
    out[0]=double(t.values.resident.load()); out[1]=double(t.values.peak.load()); out[2]=double(t.peak_bytes);
    out[3]=double(t.initial_tiles); out[4]=double(t.propagation_tiles); out[5]=double(tile_auxiliary_bytes(t)); return 0;
}
AF_EXPORT int af_skin_tiles_memory_version() { return 1; }
AF_EXPORT int af_skin_tiles_constraints(void* tiles,double* rows) {
    if(!tiles || !rows)return 1; const auto& t=*static_cast<af_skin::SkinTiles*>(tiles);
    for(size_t i=0;i<t.separators.items.size();++i) {
        const auto& s=t.separators.items[i]; double* out=rows+12*i;
        for(int a=0;a<3;++a) { out[a]=(&s.center.x)[a]; out[a+3]=(&s.normal.x)[a]; }
        out[6]=s.width; out[7]=s.limit; out[8]=s.strength;
        out[9]=s.first; out[10]=s.second; out[11]=af_skin::nearest(*t.scene,s.center).distance;
    }
    return 0;
}
AF_EXPORT int af_skin_source_intersections(void* source,int64_t* count) {
    if(!source || !count)return 1; const auto& s=*static_cast<af_skin::GapScene*>(source);
    int64_t intersections=0; int faces=int(s.mesh->triangles.size()/3);
#pragma omp parallel for reduction(+:intersections) schedule(dynamic) num_threads(af_parallel_workers(faces))
    for(int i=0;i<faces;++i)if(!s.cancelled)intersections+=af_skin::source_face_intersections(s,i);
    *count=intersections; return s.cancelled?2:0;
}

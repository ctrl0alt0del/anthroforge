#pragma once
namespace af_skin {
inline Vec tile_gradient(const SkinTiles& t,Vec p) {
    Vec gradient{}; double h=t.grid.h*.25;
    for(int a=0;a<3;++a) { Vec low=p,high=p; (&low.x)[a]-=h; (&high.x)[a]+=h;
        (&gradient.x)[a]=(interpolate_skin(t,high)-interpolate_skin(t,low))/(2*h); }
    return gradient;
}
inline Vec tile_project(const SkinTiles& t,Vec p) {
    for(int i=0;i<4;++i) {
        double value=interpolate_skin(t,p); if(std::abs(value)<t.grid.h*.001)break;
        Vec gradient=tile_gradient(t,p); double squared=dot(gradient,gradient); if(squared<1.e-15)break;
        Vec step=mul(gradient,value/squared); double length=norm(step);
        if(length>t.grid.h*.4)step=mul(step,t.grid.h*.4/length); p=sub(p,step);
    }
    return p;
}
inline Vec face_normal(const std::vector<Vec>& points,const int64_t* face) {
    return cross(sub(points[size_t(face[1])],points[size_t(face[0])]),sub(points[size_t(face[2])],points[size_t(face[0])]));
}
inline bool rollback_inversions(const std::vector<Vec>& previous,std::vector<Vec>& next,const int64_t* faces,int count,double minimum) {
    std::vector<unsigned char> bad(next.size()); bool clean=true;
    for(int i=0;i<count;++i) {
        const int64_t* f=faces+3*i; Vec before=face_normal(previous,f),after=face_normal(next,f);
        if(dot(before,after)>0 && norm(after)>std::max(minimum,norm(before)*.05))continue;
        clean=false; for(int j=0;j<3;++j)bad[size_t(f[j])]=1;
    }
    for(size_t i=0;i<bad.size();++i)if(bad[i])next[i]=previous[i]; return clean;
}
inline void tile_smooth_pass(const SkinTiles& t,FinishMesh& mesh,const int64_t* faces,int triangles,double factor) {
    tile_cancelled(t); std::vector<Vec> next(mesh.points.size());
#pragma omp parallel for schedule(static) num_threads(af_parallel_workers(int(next.size())))
    for(int i=0;i<int(next.size());++i) {
        Vec mean{}; for(int j:mesh.neighbors[i])mean=add(mean,mesh.points[j]);
        if(mesh.neighbors[i].empty()) { next[i]=mesh.points[i]; continue; }
        mean=mul(mean,1./mesh.neighbors[i].size()); Vec trial=at(mesh.points[i],mean,factor);
        next[i]=tile_project(t,bounded_step(trial,mesh.reference[i],t.grid.h*.5));
    }
    for(int attempt=0;attempt<4;++attempt)if(rollback_inversions(mesh.points,next,faces,triangles,t.grid.h*t.grid.h*1.e-4)) {
        mesh.points.swap(next); return; }
}
inline void finish_skin_tiles(SkinTiles& t,double* vertices,int count,const int64_t* faces,int triangles,int iterations) {
    FinishMesh mesh; for(int i=0;i<count;++i)mesh.points.push_back(load3(vertices+3*i)); mesh.reference=mesh.points;
    mesh_neighbors(mesh,faces,triangles); tile_stage(t,6,iterations);
    for(int i=0;i<iterations;++i) {
        tile_smooth_pass(t,mesh,faces,triangles,.45); tile_smooth_pass(t,mesh,faces,triangles,-.47); ++t.scene->done; }
    for(int i=0;i<count;++i)for(int a=0;a<3;++a)vertices[3*i+a]=(&mesh.points[i].x)[a];
}
}
AF_EXPORT int af_skin_tiles_finish(void* tiles,double* vertices,int count,const int64_t* faces,int triangles,int iterations) {
    if(!tiles || !af_skin::finish_valid(vertices,count,faces,triangles) || iterations<0 || iterations>64)return 1;
    auto& t=*static_cast<af_skin::SkinTiles*>(tiles);
    try { af_skin::finish_skin_tiles(t,vertices,count,faces,triangles,iterations); return 0; }
    catch(const std::exception& error) { t.scene->error=error.what(); return 2; }
}

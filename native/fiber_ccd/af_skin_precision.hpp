#pragma once
namespace af_skin {
inline bool face_gap_sample(const GapScene& scene,int face,Vec p,Vec direction,double reach,double* sample) {
    Hit opposite; opposite.distance=reach; ray_node(*scene.mesh,add(p,mul(direction,reach*1.e-9)),direction,0,face,opposite);
    if(opposite.face<0 || std::abs(dot(opposite.normal,direction))<.05)return false;
    double width=norm(sub(opposite.point,p)); int a=scene.owners[face],b=scene.owners[opposite.face];
    double limit=std::min(scene.limits[a],scene.limits[b]),strength=std::min(scene.strengths[a],scene.strengths[b]);
    if(width<=limit && strength==1)return false;
    Vec center=mul(add(p,opposite.point),.5); std::fill(sample,sample+13,0.);
    sample[0]=width*.5; sample[1]=width; sample[2]=limit; sample[3]=strength;
    sample[4]=face; sample[5]=opposite.face;
    for(int k=0;k<3;++k) { sample[6+k]=(&center.x)[k]; sample[9+k]=(&direction.x)[k]; }
    return resolve_gap_center(scene,sample,reach);
}
inline double face_gap_width(const GapScene& scene,int face,Vec p,Vec direction,double reach) {
    double sample[13]; return face_gap_sample(scene,face,p,direction,reach,sample)?sample[1]:INFINITY;
}
inline double precision_face(const GapScene& scene,int face,double reach) {
    Vec vertices[3]; snapshot_face(*scene.mesh,face,vertices);
    Vec normal=unit(cross(sub(vertices[1],vertices[0]),sub(vertices[2],vertices[0])));
    Vec center=mul(add(add(vertices[0],vertices[1]),vertices[2]),1./3);
    return std::min(face_gap_width(scene,face,center,normal,reach),face_gap_width(scene,face,center,mul(normal,-1),reach));
}
inline void precision_preflight(GapScene& scene,double reach,double* output) {
    int faces=int(scene.owners.size()),found=0; double smallest=INFINITY; scene.stage=0; scene.total=faces; scene.done=0;
#pragma omp parallel for reduction(+:found) reduction(min:smallest) schedule(dynamic) num_threads(af_parallel_workers(faces))
    for(int i=0;i<faces;++i) {
        if(scene.cancelled)continue; double width=precision_face(scene,i,reach);
        if(std::isfinite(width)) { smallest=std::min(smallest,width); ++found; } ++scene.done;
    }
    output[0]=found?smallest:0; output[1]=found;
}
inline bool valid_skin_grid(const int* shape,const double* transform,uint64_t budget) {
    if(!shape || !transform || transform[3]<=0 || !std::isfinite(transform[3]))return false;
    uint64_t count=1;
    for(int a=0;a<3;++a) {
        if(shape[a]<2 || shape[a]>1048576 || !std::isfinite(transform[a]))return false;
        uint64_t tiles=(uint64_t(shape[a])+31)/32; if(count>budget/(4*tiles))return false; count*=tiles;
    }
    return true;
}
}
AF_EXPORT int af_skin_gap_precision(void* source,double reach,double* output) {
    if(!source || !output || !std::isfinite(reach) || reach<=0)return 1;
    auto& scene=*static_cast<af_skin::GapScene*>(source);
    try { af_skin::precision_preflight(scene,reach,output); return scene.cancelled?2:0; } catch(...) { return 3; }
}

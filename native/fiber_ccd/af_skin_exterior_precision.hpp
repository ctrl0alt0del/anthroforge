#pragma once
namespace af_skin {
inline double exterior_face_precision(const SkinTiles& t,int face) {
    Vec vertices[3]; snapshot_face(*t.scene->mesh,face,vertices);
    Vec normal=unit(cross(sub(vertices[1],vertices[0]),sub(vertices[2],vertices[0])));
    Vec center=mul(add(add(vertices[0],vertices[1]),vertices[2]),1./3); double width=INFINITY;
    for(int sign=-1;sign<=1;sign+=2) {
        double sample[13];
        if(face_gap_sample(*t.scene,face,center,mul(normal,sign),t.reach,sample) && exterior_gap(t,sample))
            width=std::min(width,sample[1]);
    }
    return width;
}
inline void exterior_precision(SkinTiles& t,double* output) {
    int faces=int(t.scene->owners.size()),found=0; double smallest=INFINITY; tile_stage(t,0,faces);
#pragma omp parallel for reduction(+:found) reduction(min:smallest) schedule(dynamic) num_threads(af_parallel_workers(faces))
    for(int i=0;i<faces;++i) {
        if(t.scene->cancelled)continue; double width=exterior_face_precision(t,i);
        if(std::isfinite(width)) { smallest=std::min(smallest,width); ++found; } ++t.scene->done;
    }
    tile_cancelled(t); output[0]=found?smallest:0; output[1]=found;
}
}
AF_EXPORT int af_skin_gap_precision_field(void* scene,const float* field,const int* shape,const double* transform,
                                         double reach,double* output) {
    if(!scene || !field || !output || !std::isfinite(reach) || reach<=0 ||
       !af_skin::valid_skin_grid(shape,transform,UINT64_MAX))return 1;
    try {
        af_skin::SkinTiles t; t.scene=static_cast<af_skin::GapScene*>(scene); t.reach=reach;
        t.grid={shape[0],shape[1],shape[2],transform[3],load3(transform),nullptr,field,shape,transform,{}};
        af_skin::exterior_precision(t,output); return 0;
    } catch(...) { return 2; }
}

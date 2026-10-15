#pragma once
namespace af_skin {
inline void nearest_owner(const GapScene& scene,Vec p,int node_id,const std::vector<int>& excluded,Hit& hit) {
    const auto& node=scene.mesh->nodes[node_id]; if(af_bounds_distance(p,node.bounds)>hit.distance)return;
    if(node.left>=0) {
        int a=node.left,b=node.right;
        if(af_bounds_distance(p,scene.mesh->nodes[a].bounds)>af_bounds_distance(p,scene.mesh->nodes[b].bounds))std::swap(a,b);
        nearest_owner(scene,p,a,excluded,hit); nearest_owner(scene,p,b,excluded,hit); return;
    }
    for(int i=node.begin;i<node.end;++i) {
        int f=scene.mesh->faces[i].index;
        if(std::find(excluded.begin(),excluded.end(),scene.owners[f])!=excluded.end())continue;
        Hit candidate=face_hit(*scene.mesh,p,f); if(candidate.distance<hit.distance)hit=candidate;
    }
}
inline Vec barycentric(const TriangleSnapshot& mesh,const Hit& hit) {
    Vec t[3]; snapshot_face(mesh,hit.face,t); Vec a=sub(t[1],t[0]),b=sub(t[2],t[0]),p=sub(hit.point,t[0]);
    double aa=dot(a,a),ab=dot(a,b),bb=dot(b,b),pa=dot(p,a),pb=dot(p,b),denom=aa*bb-ab*ab;
    if(std::abs(denom)<1.e-30)return {1,0,0};
    double y=(bb*pa-ab*pb)/denom,z=(aa*pb-ab*pa)/denom; return {1-y-z,y,z};
}
inline bool visible(const GapScene& scene,Vec p,const Hit& hit) {
    if(hit.distance<=1.e-9)return true;
    Hit blocker; blocker.distance=hit.distance*(1-1.e-6);
    ray_node(*scene.mesh,p,mul(sub(hit.point,p),1/hit.distance),0,hit.face,blocker);
    return blocker.face<0;
}
inline void bind_point(const GapScene& scene,Vec p,int* owners,int* triangles,float* bary,float* weights,float& offset,float& support) {
    std::vector<int> excluded; std::vector<Hit> chosen;
    for(int i=0;i<8 && chosen.size()<4;++i) {
        Hit hit; nearest_owner(scene,p,0,excluded,hit); if(hit.face<0)break;
        excluded.push_back(scene.owners[hit.face]); if(visible(scene,p,hit) || chosen.empty())chosen.push_back(hit);
    }
    double sum=0; for(const auto& hit:chosen)sum+=1/std::max(1.e-12,hit.distance*hit.distance);
    offset=0; support=chosen.empty()?0:1;
    for(int i=0;i<4;++i) {
        owners[i]=triangles[i]=-1; weights[i]=0; for(int a=0;a<3;++a)bary[3*i+a]=0;
        if(i>=int(chosen.size()))continue; const auto& hit=chosen[i]; Vec bc=barycentric(*scene.mesh,hit);
        owners[i]=scene.owners[hit.face]; triangles[i]=scene.local_faces[hit.face];
        weights[i]=float((1/std::max(1.e-12,hit.distance*hit.distance))/sum);
        for(int a=0;a<3;++a)bary[3*i+a]=float((&bc.x)[a]); offset+=weights[i]*float(dot(sub(p,hit.point),hit.normal));
    }
}
}
AF_EXPORT int af_skin_bind(void* handle,const double* points,int count,int* owners,int* triangles,
                           float* bary,float* weights,float* offsets,float* support) {
    if(!handle || !points || count<0 || !owners || !triangles || !bary || !weights || !offsets || !support)return 1;
    const auto& scene=*static_cast<af_skin::GapScene*>(handle);
    try {
#pragma omp parallel for schedule(static) num_threads(af_parallel_workers(count))
        for(int i=0;i<count;++i)if(!scene.cancelled)af_skin::bind_point(scene,load3(points+3*i),owners+4*i,triangles+4*i,
            bary+12*i,weights+4*i,offsets[i],support[i]);
        return scene.cancelled?3:0;
    } catch(...) { return 2; }
}

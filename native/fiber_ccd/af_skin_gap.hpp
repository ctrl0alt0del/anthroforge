#pragma once
#include <atomic>
// Source-aware clearance queries. Included after the existing triangle BVH helpers.
namespace af_skin {
inline Vec unit(Vec value) { return mul(value,1.0/std::max(norm(value),1.e-30)); }
struct Hit { Vec point{}, normal{}; double distance=INFINITY; int face=-1; };
struct GapScene {
    std::unique_ptr<TriangleSnapshot> mesh;
    std::vector<int> owners;
    std::vector<int> local_faces;
    std::vector<unsigned char> used_vertices;
    std::vector<double> limits, strengths;
    std::vector<double> normal_sign;
    std::vector<bool> skeletal;
    std::atomic<int> cancelled{0},stage{0},done{0},total{0};
    std::string error;
};
inline Hit face_hit(const TriangleSnapshot& mesh, Vec p, int index) {
    Vec t[3]; snapshot_face(mesh,index,t); Vec q=af_closest_triangle(p,t);
    return {q,unit(cross(sub(t[1],t[0]),sub(t[2],t[0]))),norm(sub(p,q)),index};
}
inline void nearest_node(const TriangleSnapshot& mesh, Vec p, int index, Hit& hit) {
    const auto& node=mesh.nodes[index]; if(af_bounds_distance(p,node.bounds)>hit.distance)return;
    if(node.left>=0) {
        int a=node.left,b=node.right;
        if(af_bounds_distance(p,mesh.nodes[a].bounds)>af_bounds_distance(p,mesh.nodes[b].bounds))std::swap(a,b);
        nearest_node(mesh,p,a,hit); nearest_node(mesh,p,b,hit); return;
    }
    for(int i=node.begin;i<node.end;++i) {
        Hit candidate=face_hit(mesh,p,mesh.faces[i].index);
        if(candidate.distance<hit.distance)hit=candidate;
    }
}
inline double ray_parameter(Vec p,Vec d,const Vec* t) {
    Vec a=sub(t[1],t[0]), b=sub(t[2],t[0]), h=cross(d,b); double det=dot(a,h);
    if(std::abs(det)<1.e-15)return INFINITY;
    Vec s=sub(p,t[0]); double u=dot(s,h)/det; if(u<0 || u>1)return INFINITY;
    Vec q=cross(s,a); double v=dot(d,q)/det; if(v<0 || u+v>1)return INFINITY;
    double distance=dot(b,q)/det; return distance>1.e-9 ? distance : INFINITY;
}
inline bool ray_box(Vec p,Vec d,const Bounds& box,double limit) {
    double low=0,high=limit;
    for(int a=0;a<3;++a) {
        double x=(&p.x)[a],v=(&d.x)[a];
        if(std::abs(v)<1.e-15) { if(x<box.lo[a] || x>box.hi[a])return false; continue; }
        double left=(box.lo[a]-x)/v,right=(box.hi[a]-x)/v; if(left>right)std::swap(left,right);
        low=std::max(low,left); high=std::min(high,right); if(low>high)return false;
    }
    return high>0;
}
inline void ray_node(const TriangleSnapshot& mesh,Vec p,Vec d,int index,int skip,Hit& hit) {
    const auto& node=mesh.nodes[index]; if(!ray_box(p,d,node.bounds,hit.distance))return;
    if(node.left>=0) { ray_node(mesh,p,d,node.left,skip,hit); ray_node(mesh,p,d,node.right,skip,hit); return; }
    for(int i=node.begin;i<node.end;++i) {
        int f=mesh.faces[i].index; if(f==skip)continue; Vec t[3]; snapshot_face(mesh,f,t);
        double distance=ray_parameter(p,d,t);
        if(distance<hit.distance)hit={add(p,mul(d,distance)),unit(cross(sub(t[1],t[0]),sub(t[2],t[0]))),distance,f};
    }
}
inline Hit nearest(const GapScene& scene,Vec p,double reach=INFINITY) {
    Hit hit; hit.distance=reach; nearest_node(*scene.mesh,p,0,hit); return hit;
}
inline void owner_ray(const GapScene& scene,Vec p,Vec d,int index,int skip,int owner,Hit& hit) {
    const auto& mesh=*scene.mesh; const auto& node=mesh.nodes[index];
    if(!ray_box(p,d,node.bounds,hit.distance))return;
    if(node.left>=0) { owner_ray(scene,p,d,node.left,skip,owner,hit); owner_ray(scene,p,d,node.right,skip,owner,hit); return; }
    for(int i=node.begin;i<node.end;++i) {
        int f=mesh.faces[i].index; if(f==skip || scene.owners[f]!=owner)continue;
        Vec t[3]; snapshot_face(mesh,f,t); double distance=ray_parameter(p,d,t);
        if(distance<hit.distance)hit={add(p,mul(d,distance)),{},distance,f};
    }
}
inline double thickness(const GapScene& scene,const Hit& hit,Vec p,double reach) {
    if(!scene.skeletal[scene.owners[hit.face]])return INFINITY;
    Vec direction=dot(hit.normal,sub(p,hit.point))>=0?mul(hit.normal,-1):hit.normal;
    Hit opposite; opposite.distance=reach;
    owner_ray(scene,add(hit.point,mul(direction,1.e-8)),direction,0,hit.face,scene.owners[hit.face],opposite);
    return opposite.face>=0 && opposite.distance>1.e-6 ? opposite.distance : INFINITY;
}
inline void sample(const GapScene& scene,Vec p,double reach,double* out) {
    std::fill(out,out+13,0.0); out[12]=INFINITY;
    Hit a=nearest(scene,p,reach); out[0]=a.distance; out[1]=0; out[2]=out[3]=0; out[4]=out[5]=-1;
    if(a.face<0 || a.distance<1.e-9)return;
    Vec direction=mul(sub(p,a.point),1/a.distance); out[4]=a.face;
    Hit b; b.distance=reach; ray_node(*scene.mesh,p,direction,0,a.face,b);
    if(b.face<0 || std::abs(dot(b.normal,direction))<0.05)return;
    int first=scene.owners[a.face],second=scene.owners[b.face];
    out[1]=a.distance+b.distance; out[2]=std::min(scene.limits[first],scene.limits[second]);
    out[3]=std::min(scene.strengths[first],scene.strengths[second]); out[5]=b.face;
    Vec center=mul(add(a.point,b.point),0.5);
    for(int k=0;k<3;++k) { out[6+k]=(&center.x)[k]; out[9+k]=(&direction.x)[k]; }
}
inline bool valid_input(const double* v,int nv,const int64_t* f,int nf,const int* owners,int ns,const double* policies) {
    if(!v || !f || !owners || !policies || nv<3 || nf<1 || ns<1)return false;
    for(int i=0;i<3*nv;++i)if(!std::isfinite(v[i]))return false;
    for(int i=0;i<3*nf;++i)if(f[i]<0 || f[i]>=nv)return false;
    for(int i=0;i<nf;++i)if(owners[i]<0 || owners[i]>=ns)return false;
    for(int i=0;i<ns;++i)if(!std::isfinite(policies[3*i]) || policies[3*i]<0 ||
        !std::isfinite(policies[3*i+1]) || policies[3*i+1]<0 || policies[3*i+1]>1)return false;
    return true;
}
inline void orient_gap_sources(GapScene& scene,int count) {
    std::vector<Vec> centers(count); std::vector<int> sizes(count); std::vector<double> volumes(count),areas(count);
    int faces=int(scene.owners.size());
    for(int i=0;i<faces;++i) { Vec p[3]; snapshot_face(*scene.mesh,i,p); int owner=scene.owners[i];
        centers[owner]=add(centers[owner],add(add(p[0],p[1]),p[2])); sizes[owner]+=3; }
    for(int i=0;i<count;++i)centers[i]=mul(centers[i],1./std::max(1,sizes[i]));
    for(int i=0;i<faces;++i) { Vec p[3]; snapshot_face(*scene.mesh,i,p); int owner=scene.owners[i];
        Vec n=cross(sub(p[1],p[0]),sub(p[2],p[0])); volumes[owner]+=dot(sub(p[0],centers[owner]),n); areas[owner]+=norm(n); }
    for(int i=0;i<count;++i)scene.normal_sign.push_back(std::abs(volumes[i])>areas[i]*1.e-8?std::copysign(1.,volumes[i]):0.);
}
inline bool opposing_patches(const GapScene& scene,const double* sample) {
    int first=int(sample[4]),second=int(sample[5]); if(first<0 || second<0)return false;
    for(int i=0;i<3;++i)for(int j=0;j<3;++j)
        if(scene.mesh->triangles[size_t(first)*3+i]==scene.mesh->triangles[size_t(second)*3+j])return false;
    double a=scene.normal_sign[scene.owners[first]],b=scene.normal_sign[scene.owners[second]];
    if(a==0 || b==0)return true;
    Vec n=mul(face_hit(*scene.mesh,load3(sample+6),first).normal,a);
    Vec m=mul(face_hit(*scene.mesh,load3(sample+6),second).normal,b),axis=load3(sample+9);
    return dot(n,axis)>.25 && dot(m,axis)<-.25 && dot(n,m)<-.2;
}
}
AF_EXPORT int af_skin_gap_version() { return 3; }
AF_EXPORT void* af_skin_gap_create(const double* vertices,int nv,const int64_t* faces,int nf,
                                  const int* owners,int ns,const double* policies) {
    if(!af_skin::valid_input(vertices,nv,faces,nf,owners,ns,policies))return nullptr;
    try {
        auto s=std::make_unique<af_skin::GapScene>(); s->mesh.reset(create_snapshot(vertices,faces,nf));
        s->used_vertices.resize(s->mesh->vertices.size());
        for(int i=0;i<3*nf;++i)s->used_vertices[size_t(faces[i])]=1;
        s->owners.assign(owners,owners+nf);
        std::vector<int> counts(ns,0); for(int i=0;i<nf;++i)s->local_faces.push_back(counts[owners[i]]++);
        for(int i=0;i<ns;++i) { s->limits.push_back(policies[3*i]); s->strengths.push_back(policies[3*i+1]);
            s->skeletal.push_back(policies[3*i+2]!=0); }
        af_skin::orient_gap_sources(*s,ns);
        return s.release();
    } catch(...) { return nullptr; }
}
AF_EXPORT void af_skin_gap_destroy(void* handle) { delete static_cast<af_skin::GapScene*>(handle); }
AF_EXPORT void af_skin_gap_cancel(void* handle) { if(handle)static_cast<af_skin::GapScene*>(handle)->cancelled=1; }
AF_EXPORT int af_skin_gap_progress(void* handle,int* output) {
    if(!handle || !output)return 1; auto& s=*static_cast<af_skin::GapScene*>(handle);
    output[0]=s.stage; output[1]=s.done; output[2]=s.total; return 0;
}
AF_EXPORT const char* af_skin_gap_error(void* handle) { return handle?static_cast<af_skin::GapScene*>(handle)->error.c_str():"Missing gap scene"; }
AF_EXPORT int af_skin_gap_sample(void* handle,const double* points,int count,double reach,double* output) {
    if(!handle || !points || !output || count<0 || !std::isfinite(reach) || reach<=0)return 1;
    const auto& scene=*static_cast<af_skin::GapScene*>(handle);
#pragma omp parallel for schedule(static) num_threads(af_parallel_workers(count))
    for(int i=0;i<count;++i)af_skin::sample(scene,load3(points+3*i),reach,output+13*i);
    return 0;
}

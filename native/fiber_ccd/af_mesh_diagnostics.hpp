#pragma once
#include <atomic>
namespace af_diag {
struct Task { std::atomic<bool> cancelled{false}; int64_t tests=0, crossings=0, contacts=0; };
inline bool proper(Vec a,Vec b,const Vec* t) {
    Vec n=af_skin::unit(cross(sub(t[1],t[0]),sub(t[2],t[0])));
    double da=dot(sub(a,t[0]),n),db=dot(sub(b,t[0]),n);
    return da*db<0 && std::abs(da)>1.e-10 && std::abs(db)>1.e-10 && af_skin::crossing_edge(a,b,t);
}
inline bool crossed(const Vec* a,const Vec* b) {
    for(int k=0;k<3;++k)if(proper(a[k],a[(k+1)%3],b)||proper(b[k],b[(k+1)%3],a))return true;
    return false;
}
inline void pair(Task& task,const TriangleSnapshot& mesh,int i,int j,int64_t* pairs,int capacity) {
    if(j<=i || af_skin::shared_vertex(mesh,i,j))return;
    if(++task.tests>50000000)throw std::runtime_error("Diagnostic pair budget exceeded");
    Vec a[3],b[3]; snapshot_face(mesh,i,a); snapshot_face(mesh,j,b);
    if(crossed(a,b)) {
        if(task.crossings<capacity) { pairs[2*task.crossings]=i; pairs[2*task.crossings+1]=j; }
        ++task.crossings;
    } else if(af_skin::triangle_distance(a,b)<=1.e-10)++task.contacts;
}
inline void visit(Task& task,const TriangleSnapshot& mesh,int i,int node,int64_t* pairs,int capacity) {
    if(task.cancelled)throw std::runtime_error("Cancelled");
    const auto& n=mesh.nodes[node]; const auto& box=mesh.indexed_faces[i];
    if(!bounds_overlap(box,n.bounds))return;
    if(n.left>=0) { visit(task,mesh,i,n.left,pairs,capacity); visit(task,mesh,i,n.right,pairs,capacity); return; }
    for(int k=n.begin;k<n.end;++k)if(bounds_overlap(box,mesh.faces[k]))
        pair(task,mesh,i,mesh.faces[k].index,pairs,capacity);
}
inline int run(Task& task,const double* v,int count,const int64_t* f,int faces,int64_t budget,int64_t* pairs,int cap) {
    if(int64_t(count)*64+int64_t(faces)*256>budget)return 3;
    std::unique_ptr<TriangleSnapshot> mesh(create_snapshot(v,f,faces));
    for(int i=0;i<faces;++i)visit(task,*mesh,i,0,pairs,cap);
    return 0;
}
}
AF_EXPORT int af_mesh_diagnostics_version() { return 1; }
AF_EXPORT void* af_mesh_diagnostics_create() { try { return new af_diag::Task(); } catch(...) { return nullptr; } }
AF_EXPORT void af_mesh_diagnostics_cancel(void* p) { if(p)static_cast<af_diag::Task*>(p)->cancelled=true; }
AF_EXPORT void af_mesh_diagnostics_destroy(void* p) { delete static_cast<af_diag::Task*>(p); }
AF_EXPORT int af_mesh_diagnostics_run(void* p,const double* v,int count,const int64_t* f,int faces,
                                    int64_t budget,int64_t* pairs,int capacity,int64_t* stats) {
    if(!p||!pairs||!stats||capacity<0||!af_skin::finish_valid(v,count,f,faces))return 1;
    auto& task=*static_cast<af_diag::Task*>(p); int code=0;
    try { code=af_diag::run(task,v,count,f,faces,budget,pairs,capacity); } catch(...) { code=task.cancelled?4:2; }
    stats[0]=task.crossings; stats[1]=task.contacts; stats[2]=task.tests;
    return code;
}

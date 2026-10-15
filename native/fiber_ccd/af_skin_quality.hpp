#pragma once
namespace af_skin {
inline int component_root(std::vector<int>& parent,int i) {
    int root=i; while(parent[root]!=root)root=parent[root];
    while(parent[i]!=i) { int next=parent[i]; parent[i]=root; i=next; } return root;
}
inline void join_components(std::vector<int>& parent,int a,int b) {
    a=component_root(parent,a); b=component_root(parent,b); if(a!=b)parent[std::max(a,b)]=std::min(a,b);
}
inline void quality_face(const double* vertices,const int64_t* face,Vec origin,double threshold,
                          std::vector<int>& parent,std::vector<uint64_t>& edges,double* out) {
    Vec p[3]; for(int j=0;j<3;++j) { int a=int(face[j]),b=int(face[(j+1)%3]); p[j]=load3(vertices+3*a);
        uint64_t edge=(uint64_t(std::min(a,b))<<32)|uint32_t(std::max(a,b));
        edges.push_back((edge<<1)|(a<b?0:1)); join_components(parent,a,b); }
    Vec normal=cross(sub(p[1],p[0]),sub(p[2],p[0])); double area=norm(normal);
    out[6]=std::min(out[6],area); if(area<=threshold)out[5]=0;
    out[7]+=dot(sub(p[0],origin),cross(sub(p[1],origin),sub(p[2],origin)))/6;
}
inline void quality_edges(std::vector<uint64_t>& edges,double* out) {
    std::sort(edges.begin(),edges.end());
    for(size_t i=0;i<edges.size();) { size_t end=i+1;
        while(end<edges.size() && (edges[end]>>1)==(edges[i]>>1))++end;
        if(end-i!=2)out[2]=out[3]=0;
        else if((edges[i]&1)==(edges[i+1]&1))out[3]=0;
        ++out[8]; i=end;
    }
}
inline void mesh_quality(const double* vertices,int count,const int64_t* faces,int triangles,double* out) {
    std::fill(out,out+9,0.); out[0]=out[2]=out[3]=out[5]=1; out[6]=INFINITY;
    Vec low=load3(vertices),high=low;
    for(int i=1;i<count;++i)for(int a=0;a<3;++a) {
        (&low.x)[a]=std::min((&low.x)[a],vertices[3*i+a]); (&high.x)[a]=std::max((&high.x)[a],vertices[3*i+a]); }
    double length=std::max({high.x-low.x,high.y-low.y,high.z-low.z,1.});
    std::vector<int> parents(count); std::iota(parents.begin(),parents.end(),0);
    std::vector<uint64_t> edges; edges.reserve(size_t(triangles)*3);
    for(int i=0;i<triangles;++i)quality_face(vertices,faces+3*i,low,length*length*1.e-12,parents,edges,out);
    quality_edges(edges,out); out[4]=out[7]>0;
    for(int i=0;i<count;++i)if(component_root(parents,i)==i)++out[1];
}
inline double triangle_distance(const Vec* a,const Vec* b) {
    double distance=INFINITY;
    for(int i=0;i<3;++i) {
        distance=std::min(distance,segment_triangle(a[i],a[(i+1)%3],b));
        distance=std::min(distance,segment_triangle(b[i],b[(i+1)%3],a));
    }
    return distance;
}
inline bool source_face_crosses(const TriangleSnapshot& output,const GapScene& source,int face) {
    Vec original[3]; snapshot_face(*source.mesh,face,original); std::vector<int> candidates;
    collect_candidates(output,0,source.mesh->indexed_faces[face],candidates);
    for(int index:candidates) { Vec skin[3]; snapshot_face(output,index,skin);
        if(triangle_distance(original,skin)<=1.e-10)return true; }
    return false;
}
inline bool source_point_outside(const TriangleSnapshot& output,const GapScene& source,int i,double tolerance) {
    if(source.cancelled || !source.used_vertices[i])return false;
    Vec p=source.mesh->vertices[i]; Hit hit; nearest_node(output,p,0,hit);
    return hit.distance>tolerance && !snapshot_inside(output,p,0,int(output.triangles.size()/3));
}
inline void source_coverage(const TriangleSnapshot& output,const GapScene& source,double tolerance,double* out) {
    int outside=0,crossed=0,count=int(source.mesh->vertices.size()),faces=int(source.mesh->triangles.size()/3);
#pragma omp parallel for reduction(+:outside) schedule(static) num_threads(af_parallel_workers(count))
    for(int i=0;i<count;++i)if(source_point_outside(output,source,i,tolerance))++outside;
#pragma omp parallel for reduction(+:crossed) schedule(dynamic) num_threads(af_parallel_workers(faces))
    for(int i=0;i<faces;++i)if(!source.cancelled && source_face_crosses(output,source,i))++crossed;
    if(source.cancelled)throw std::runtime_error("Draft skin validation was cancelled.");
    out[0]=outside; out[1]=crossed; out[2]=std::count(source.used_vertices.begin(),source.used_vertices.end(),1); out[3]=faces;
}
}
AF_EXPORT int af_skin_mesh_quality(const double* vertices,int count,const int64_t* faces,int triangles,double* output) {
    if(!af_skin::finish_valid(vertices,count,faces,triangles) || !output)return 1;
    try { af_skin::mesh_quality(vertices,count,faces,triangles,output); return 0; } catch(...) { return 2; }
}
AF_EXPORT int af_skin_source_coverage(void* source,const double* vertices,int count,const int64_t* faces,
                                      int triangles,double tolerance,double* output) {
    if(!source || !af_skin::finish_valid(vertices,count,faces,triangles) || !output || tolerance<0)return 1;
    try {
        std::unique_ptr<TriangleSnapshot> mesh(create_snapshot(vertices,faces,triangles,false));
        af_skin::source_coverage(*mesh,*static_cast<af_skin::GapScene*>(source),tolerance,output); return 0;
    } catch(...) { return 2; }
}
AF_EXPORT int af_skin_source_coverage_marks(void* source,const double* vertices,int count,const int64_t* faces,
                                           int triangles,double tolerance,unsigned char* points,unsigned char* crossed) {
    if(!source || !af_skin::finish_valid(vertices,count,faces,triangles) || !points || !crossed)return 1;
    const auto& s=*static_cast<af_skin::GapScene*>(source);
    try {
        std::unique_ptr<TriangleSnapshot> mesh(create_snapshot(vertices,faces,triangles,false));
#pragma omp parallel for schedule(static) num_threads(af_parallel_workers(int(s.mesh->vertices.size())))
        for(int i=0;i<int(s.mesh->vertices.size());++i)points[i]=af_skin::source_point_outside(*mesh,s,i,tolerance);
#pragma omp parallel for schedule(dynamic) num_threads(af_parallel_workers(int(s.owners.size())))
        for(int i=0;i<int(s.owners.size());++i)crossed[i]=af_skin::source_face_crosses(*mesh,s,i);
        return 0;
    } catch(...) { return 2; }
}

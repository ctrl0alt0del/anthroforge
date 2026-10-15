#pragma once
namespace af_skin {
struct FinishMesh {
    std::vector<Vec> points,reference;
    std::vector<std::vector<int>> neighbors;
    WrapGrid grid;
};
inline Vec bounded_step(Vec p,Vec reference,double limit) {
    Vec delta=sub(p,reference); double length=norm(delta);
    return length>limit?add(reference,mul(delta,limit/length)):p;
}
inline void mesh_neighbors(FinishMesh& mesh,const int64_t* faces,int count) {
    mesh.neighbors.resize(mesh.points.size());
    for(int i=0;i<count;++i)for(int j=0;j<3;++j) {
        int a=int(faces[3*i+j]),b=int(faces[3*i+(j+1)%3]);
        mesh.neighbors[a].push_back(b); mesh.neighbors[b].push_back(a);
    }
    for(auto& row:mesh.neighbors) { std::sort(row.begin(),row.end()); row.erase(std::unique(row.begin(),row.end()),row.end()); }
}
inline bool finish_valid(const double* vertices,int count,const int64_t* faces,int triangles) {
    if(!vertices || !faces || count<3 || triangles<1)return false;
    for(int i=0;i<3*count;++i)if(!std::isfinite(vertices[i]))return false;
    for(int i=0;i<3*triangles;++i)if(faces[i]<0 || faces[i]>=count)return false;
    return true;
}
}

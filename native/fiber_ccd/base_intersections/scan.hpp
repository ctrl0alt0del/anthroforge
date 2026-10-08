#pragma once
#include "triangles.hpp"
namespace af_base_check {
struct Input { const double* vertices;const int64_t* faces;int vertex_count,face_count; };
struct Witness { int64_t first_face,second_face,kind;double first[3],second[3]; };
struct Pair { int64_t first,second,counts[3]{},start=0,size=0;double area=0; };
struct Mesh { std::unique_ptr<TriangleSnapshot> tree;std::vector<bool> valid;std::vector<int> boundaries;int64_t degenerate=0; };
struct Result { std::vector<Pair> pairs;std::vector<Witness> witnesses;std::vector<int64_t> degenerate;int64_t broad=0,tests=0; };
static Bounds expanded(Bounds box,double epsilon) {
    for(int i=0;i<3;++i){box.lo[i]-=epsilon;box.hi[i]+=epsilon;}return box;
}
static void validate(const Input& in) {
    af_pair::require(in.vertices&&in.faces&&in.vertex_count>=3&&in.face_count>0,"BASE_INPUT_SIZE");
    for(int i=0;i<in.vertex_count;++i)af_pair::require(af_pair::finite(load3(in.vertices+3*i)),"BASE_COORDINATES");
    for(int64_t i=0;i<int64_t(in.face_count)*3;++i)af_pair::require(in.faces[i]>=0&&in.faces[i]<in.vertex_count,"BASE_FACE_INDEX");
}
static Mesh capture(const Input& in,double epsilon) {
    validate(in);Mesh mesh;mesh.tree.reset(create_snapshot(in.vertices,in.faces,in.face_count));
    std::map<std::pair<int64_t,int64_t>,int> edges;
    for(int i=0;i<in.face_count;++i)for(int j=0;j<3;++j)++edges[std::minmax(in.faces[3*i+j],in.faces[3*i+(j+1)%3])];
    for(int i=0;i<in.face_count;++i){Vec p[3];snapshot_face(*mesh.tree,i,p);
        double longest=std::max({norm(sub(p[1],p[0])),norm(sub(p[2],p[0])),norm(sub(p[2],p[1]))});
        bool valid=norm(cross(sub(p[1],p[0]),sub(p[2],p[0])))>epsilon*longest;
        mesh.valid.push_back(valid);mesh.degenerate+=!valid;int mask=0;
        for(int j=0;j<3;++j)if(edges[std::minmax(in.faces[3*i+j],in.faces[3*i+(j+1)%3])]==1)mask|=1<<j;
        mesh.boundaries.push_back(mask);}
    return mesh;
}
static bool on_boundary(const Mesh& mesh,int face,Vec p,double epsilon) {
    Vec tri[3];snapshot_face(*mesh.tree,face,tri);
    for(int j=0;j<3;++j)if(mesh.boundaries[face]&(1<<j)){
        Vec d=sub(tri[(j+1)%3],tri[j]);double t=std::clamp(dot(sub(p,tri[j]),d)/dot(d,d),0.,1.);
        if(norm(sub(p,add(tri[j],mul(d,t))))<=epsilon)return true;}
    return false;
}
static void record(Result& out,Pair& pair,Hit hit,int a,int b,int limit) {
    ++pair.counts[hit.kind-1];pair.area+=hit.area;
    // Reserve a bounded number of witnesses per category, but count every hit.
    if(pair.counts[hit.kind-1]>limit)return;
    af_pair::require(out.witnesses.size()<2000000,"BASE_WITNESS_RESOURCE_LIMIT");
    Witness w{a,b,hit.kind,{hit.first.x,hit.first.y,hit.first.z},{hit.second.x,hit.second.y,hit.second.z}};
    out.witnesses.push_back(w);++pair.size;
}
static void test_face(Result& out,Pair& pair,const Mesh& a,int fa,const Mesh& b,int fb,double epsilon,int limit) {
    if(!a.valid[fa]||!b.valid[fb])return;++out.tests;Vec p[3],q[3];snapshot_face(*a.tree,fa,p);snapshot_face(*b.tree,fb,q);
    Hit hit=intersection(p,q,epsilon);if(!hit.kind)return;Vec middle=mul(add(hit.first,hit.second),.5);
    if(hit.kind==1&&on_boundary(a,fa,middle,epsilon)&&on_boundary(b,fb,middle,epsilon))hit.kind=3;
    record(out,pair,hit,fa,fb,limit);
}
static void test_pair(Result& out,Pair& pair,const Mesh& a,const Mesh& b,double epsilon,int limit) {
    std::vector<int> stack;
    for(int fa=0;fa<int(a.valid.size());++fa){if(!a.valid[fa])continue;Bounds box=expanded(a.tree->indexed_faces[fa],epsilon);stack={0};
        while(!stack.empty()){int n=stack.back();stack.pop_back();const auto& node=b.tree->nodes[n];
            if(!bounds_overlap(box,node.bounds))continue;
            if(node.left>=0){stack.push_back(node.left);stack.push_back(node.right);continue;}
            for(int j=node.begin;j<node.end;++j)if(bounds_overlap(box,b.tree->faces[j]))
                test_face(out,pair,a,fa,b,b.tree->faces[j].index,epsilon,limit);}}
}
static Result scan(const Input* inputs,int count,double epsilon,int limit) {
    af_pair::require(count>=0&&count<=4096&&(inputs||!count)&&std::isfinite(epsilon)&&epsilon>0&&limit>=0&&limit<=64,"BASE_SETTINGS");
    Result out;std::vector<Mesh> meshes;
    for(int i=0;i<count;++i){meshes.push_back(capture(inputs[i],epsilon));out.degenerate.push_back(meshes.back().degenerate);}
    for(int a=0;a<count;++a)for(int b=a+1;b<count;++b){
        if(!bounds_overlap(expanded(meshes[a].tree->nodes[0].bounds,epsilon),meshes[b].tree->nodes[0].bounds))continue;
        ++out.broad;Pair pair{};pair.first=a;pair.second=b;pair.start=out.witnesses.size();test_pair(out,pair,meshes[a],meshes[b],epsilon,limit);
        if(pair.counts[0]+pair.counts[1]+pair.counts[2])out.pairs.push_back(pair);}
    return out;
}
}

#pragma once
namespace af_layer {
using Edge=std::pair<int64_t,int64_t>;
static Bounds triangle_box(const Vec* points) {
    Bounds box{};for(int j=0;j<3;++j){box.lo[j]=INFINITY;box.hi[j]=-INFINITY;
        for(int i=0;i<3;++i){box.lo[j]=std::min(box.lo[j],(&points[i].x)[j]-1e-9);box.hi[j]=std::max(box.hi[j],(&points[i].x)[j]+1e-9);}}
    return box;
}
static std::map<Edge,int> edge_counts(const Side& side) {
    std::map<Edge,int> result;
    for(size_t f=0;f<side.faces.size();f+=3)for(int j=0;j<3;++j){
        auto a=side.faces[f+j],b=side.faces[f+(j+1)%3];++result[std::minmax(a,b)];}
    return result;
}
static double triangle_hit(Vec o,Vec d,const Vec* f) {
    Vec e1=sub(f[1],f[0]),e2=sub(f[2],f[0]),h=cross(d,e2);double det=dot(e1,h);
    if(std::abs(det)<1e-16)return INFINITY;Vec s=sub(o,f[0]);double u=dot(s,h)/det;
    if(u<-1e-9||u>1+1e-9)return INFINITY;Vec q=cross(s,e1);double v=dot(d,q)/det;
    if(v<-1e-9||u+v>1+1e-9)return INFINITY;return dot(e2,q)/det;
}
static void segment_hits(const Vec* a,const Vec* b,std::vector<Vec>& hits) {
    for(int i=0;i<3;++i){Vec delta=sub(a[(i+1)%3],a[i]);double t=triangle_hit(a[i],delta,b);
        if(t>=-1e-9&&t<=1+1e-9)hits.push_back(add(a[i],mul(delta,t)));}
}
static bool on_boundary(const Side& s,int f,Vec point,const std::map<Edge,int>& counts) {
    for(int j=0;j<3;++j){int64_t a=s.faces[f*3+j],b=s.faces[f*3+(j+1)%3];
        if(counts.at(std::minmax(a,b))!=1)continue;Vec delta=sub(s.base[b],s.base[a]);double length=dot(delta,delta);
        if(length<1e-24)continue;double t=dot(sub(point,s.base[a]),delta)/length;
        if(t>=-1e-8&&t<=1+1e-8&&norm(sub(point,add(s.base[a],mul(delta,t))))<1e-8)return true;}
    return false;
}
static bool transverse(const Side& a,int fa,const Side& b,int fb,const std::map<Edge,int>& ea,const std::map<Edge,int>& eb) {
    Vec va[3],vb[3];face(a,fa,va);face(b,fb,vb);
    Vec na=cross(sub(va[1],va[0]),sub(va[2],va[0])),nb=cross(sub(vb[1],vb[0]),sub(vb[2],vb[0]));
    if(norm(cross(na,nb))<=1e-10*norm(na)*norm(nb))return false;
    std::vector<Vec> hits;segment_hits(va,vb,hits);segment_hits(vb,va,hits);
    double longest=0;Vec middle{};
    for(Vec p:hits)for(Vec q:hits)if(norm(sub(p,q))>longest){longest=norm(sub(p,q));middle=mul(add(p,q),.5);}
    return longest>1e-8&&!(on_boundary(a,fa,middle,ea)&&on_boundary(b,fb,middle,eb));
}
static int crossing_count(const Side& a,const Side& b,std::atomic<bool>& cancelled) {
    auto ea=edge_counts(a),eb=edge_counts(b);int result=0;std::vector<int> stack;
    for(size_t f=0;f<a.faces.size()/3;++f){
        require(!cancelled,"PAIR_CANCELLED");Vec points[3];face(a,int(f),points);Bounds box=triangle_box(points);
        stack={0};while(!stack.empty()){int n=stack.back();stack.pop_back();const auto& node=b.snapshot->nodes[n];
            if(!bounds_overlap(box,node.bounds))continue;
            if(node.left>=0){stack.push_back(node.left);stack.push_back(node.right);continue;}
            for(int j=node.begin;j<node.end;++j)if(bounds_overlap(box,b.snapshot->faces[j])&&transverse(a,int(f),b,b.snapshot->faces[j].index,ea,eb))++result;}}
    return result;
}
}

#pragma once
namespace af_skin {
struct ComponentBound { Vec low{INFINITY,INFINITY,INFINITY},high{-INFINITY,-INFINITY,-INFINITY}; double radius=0; bool keep=true; };
inline std::vector<int> component_labels(int count,const int64_t* faces,int triangles,int& components) {
    std::vector<int> labels(count),indices(count,-1); std::iota(labels.begin(),labels.end(),0);
    for(int i=0;i<triangles;++i)for(int j=0;j<3;++j)join_components(labels,int(faces[3*i+j]),int(faces[3*i+(j+1)%3]));
    for(int i=0;i<count;++i)labels[i]=component_root(labels,i);
    components=0;
    for(int i=0;i<count;++i) { int root=labels[i]; if(indices[root]<0)indices[root]=components++;
        labels[i]=indices[root]; }
    return labels;
}
inline void bounds_point(ComponentBound& bound,Vec p) {
    for(int a=0;a<3;++a) {
        (&bound.low.x)[a]=std::min((&bound.low.x)[a],(&p.x)[a]);
        (&bound.high.x)[a]=std::max((&bound.high.x)[a],(&p.x)[a]); }
}
inline void classify_components(const GapScene& source,const double* vertices,int count,const std::vector<int>& labels,
                                 std::vector<ComponentBound>& bounds) {
    for(int i=0;i<count;++i)bounds_point(bounds[labels[i]],load3(vertices+3*i));
    for(int i=0;i<count;++i) { auto& b=bounds[labels[i]]; Vec center=mul(add(b.low,b.high),.5);
        b.radius=std::max(b.radius,norm(sub(load3(vertices+3*i),center))); }
    for(auto& b:bounds) { Vec center=mul(add(b.low,b.high),.5);
        b.keep=nearest(source,center).distance<=b.radius*(1+1.e-6); }
}
inline void keep_supported_components(const GapScene& source,const double* vertices,int count,const int64_t* faces,
                                       int triangles,unsigned char* keep,int* stats) {
    int components=0; auto labels=component_labels(count,faces,triangles,components);
    std::vector<ComponentBound> bounds(components); classify_components(source,vertices,count,labels,bounds);
    stats[0]=components; stats[1]=stats[2]=0;
    for(const auto& b:bounds)if(!b.keep)++stats[1];
    for(int i=0;i<count;++i) { keep[i]=bounds[labels[i]].keep; if(!keep[i])++stats[2]; }
}
}
AF_EXPORT int af_skin_supported_components(void* source,const double* vertices,int count,const int64_t* faces,
                                           int triangles,unsigned char* keep,int* stats) {
    if(!source || !af_skin::finish_valid(vertices,count,faces,triangles) || !keep || !stats)return 1;
    try { af_skin::keep_supported_components(*static_cast<af_skin::GapScene*>(source),vertices,count,faces,triangles,keep,stats); return 0; }
    catch(...) { return 2; }
}

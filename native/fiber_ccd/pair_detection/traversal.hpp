#pragma once
namespace af_pair {
static bool outside_box(const Query& q,const Bounds& b) {
    Vec center{(b.lo[0]+b.hi[0])*.5,(b.lo[1]+b.hi[1])*.5,(b.lo[2]+b.hi[2])*.5};
    center=sub(center,q.origin);
    for(Vec edge:q.edges){
        Vec n=add(mul(q.frame.u,edge.x),mul(q.frame.v,edge.y)); double radius=0;
        for(int i=0;i<3;++i)radius+=std::abs((&n.x)[i])*(b.hi[i]-b.lo[i])*.5;
        if(dot(n,center)+edge.z+radius < -1e-10)return true;
    }
    return false;
}
static void collect_tight(const TriangleSnapshot& s,int node,const Query& q,const Bounds& bounds,std::vector<int>& hits) {
    const auto& value=s.nodes[node];
    if(!bounds_overlap(bounds,value.bounds)||outside_box(q,value.bounds))return;
    if(value.left>=0){
        collect_tight(s,value.left,q,bounds,hits);collect_tight(s,value.right,q,bounds,hits);return;
    }
    for(int i=value.begin;i<value.end;++i)
        if(bounds_overlap(bounds,s.faces[i])&&!outside_box(q,s.faces[i]))hits.push_back(s.faces[i].index);
}
static void find_faces(const Query& q,bool exhaustive,std::vector<int>& faces) {
    faces.clear();
    if(exhaustive){faces.resize(q.provider.faces.size()/3);std::iota(faces.begin(),faces.end(),0);return;}
    collect_tight(*q.provider.snapshot,0,q,query_bounds(q),faces);
}
static void map_direction(const Session& s,int r,int p,Result& out,Budget& budget,bool exhaustive,const Settings* settings=nullptr) {
    const auto& receiver=s.sides[r];const auto& provider=s.sides[p];std::vector<int> faces;
    for(size_t f=0;f<receiver.faces.size()/3;++f){
        check_cancel(budget);
        Query q{receiver,provider,settings?*settings:s.settings,r,p,int(f),{}, {}};q.budget=&budget;
        auto start=Clock::now();if(!prepare(q,out))continue;cache_chart(q);
        find_faces(q,exhaustive,faces);out.profile[0]+=milliseconds(start);start=Clock::now();
        for(int id:faces)map_fast(q,id,out);
        out.profile[1]+=milliseconds(start);
    }
}
}

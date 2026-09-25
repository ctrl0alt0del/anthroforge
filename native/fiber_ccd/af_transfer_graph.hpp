// Deterministic native neighborhoods for joint muscle-family shape matching.
#pragma once
#include <map>
#include <set>
#include <queue>
#include <stdexcept>
namespace af_transfer_shape {
using Neighbor = std::pair<double, int>;
static void knn(const Tree&t,int node,P p,int count,std::priority_queue<Neighbor>&hits) {
    if(node<0)return;const auto&k=t.nodes[node];P delta=sub(p,t.p[k.id]);Neighbor hit{norm2(delta),k.id};
    if((int)hits.size()<count)hits.push(hit);else if(hit<hits.top()){hits.pop();hits.push(hit);}
    double d=delta[k.axis];knn(t,d<0?k.left:k.right,p,count,hits);
    if((int)hits.size()<count||d*d<=hits.top().first)knn(t,d<0?k.right:k.left,p,count,hits);
}
static std::vector<Neighbor> neighbors(const Tree&t,P p,int count) {
    std::priority_queue<Neighbor>hits;knn(t,0,p,count,hits);std::vector<Neighbor>out;
    while(!hits.empty()){out.push_back(hits.top());hits.pop();}std::reverse(out.begin(),out.end());return out;
}
static Tree tree(const std::vector<P>&points) {
    Tree t;t.p=points;t.order.resize(points.size());std::iota(t.order.begin(),t.order.end(),0);
    build(t,0,(int)points.size(),0);return t;
}
static double extent(const std::vector<P>&points) {
    P lo=points[0],hi=lo;for(P p:points)for(int j=0;j<3;++j){lo[j]=std::min(lo[j],p[j]);hi[j]=std::max(hi[j],p[j]);}
    return std::max({hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2]});
}
static std::vector<std::pair<int,int>> edges(const Tree&t,const int*faces,int nf,double bridge) {
    std::set<std::pair<int,int>>out;
    for(int f=0;f<nf;++f)for(int j=0;j<3;++j){int a=faces[3*f+j],b=faces[3*f+(j+1)%3];out.insert(std::minmax(a,b));}
    if(bridge>0)for(int i=0;i<(int)t.p.size();++i){int taken=0;
        for(auto [distance,j]:neighbors(t,t.p[i],4))if(i!=j&&taken++<3&&distance<bridge*bridge)out.insert(std::minmax(i,j));}
    return {out.begin(),out.end()};
}
static std::vector<P> centers(const std::vector<P>&v,double size) {
    P lo=v[0];for(P p:v)for(int j=0;j<3;++j)lo[j]=std::min(lo[j],p[j]);std::map<std::array<int,3>,int>cells;
    for(int i=0;i<(int)v.size();++i){std::array<int,3>key{};for(int j=0;j<3;++j)key[j]=(int)floor((v[i][j]-lo[j])/(size*.055));cells.emplace(key,i);}
    std::vector<int>ids;for(auto item:cells)ids.push_back(item.second);std::vector<P>out;int count=std::min(400,(int)ids.size());
    for(int i=0;i<count;++i)out.push_back(v[ids[count==1?0:(size_t)(double(i)*(ids.size()-1)/(count-1))]]);return out;
}
static std::vector<std::vector<int>> clusters(const std::vector<P>&v,double radius) {
    auto c=centers(v,extent(v));auto t=tree(c);std::vector<std::vector<int>>out(c.size());size_t total=0;
    for(int i=0;i<(int)v.size();++i){auto nearest=neighbors(t,v[i],std::min(4,(int)c.size()));
        for(int j=0;j<(int)c.size();++j){bool close=norm2(sub(v[i],c[j]))<=radius*radius;
            for(auto n:nearest)close=close||n.second==j;if(close){out[j].push_back(i);if(++total>8000000)throw std::runtime_error("cluster budget");}}}
    return out;
}
static std::vector<double> geodesic(int n,const int*fixed,const std::vector<std::pair<int,int>>&edges,const std::vector<P>&rest) {
    std::vector<std::vector<Neighbor>>adj(n);std::vector<double>d(n,1e50);
    for(auto [i,j]:edges){double w=sqrt(norm2(sub(rest[i],rest[j])));adj[i].push_back({w,j});adj[j].push_back({w,i});}
    std::priority_queue<Neighbor,std::vector<Neighbor>,std::greater<Neighbor>>q;
    for(int i=0;i<n;++i)if(fixed[i]){d[i]=0;q.push({0,i});}
    while(!q.empty()){auto [value,i]=q.top();q.pop();if(value!=d[i])continue;
        for(auto [w,j]:adj[i])if(value+w<d[j]){d[j]=value+w;q.push({d[j],j});}}
    return d;
}
}

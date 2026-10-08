#pragma once
#include <Eigen/LU>
#include <Eigen/Geometry>
namespace af_stack_vector {
using namespace af_layer;
using V3=Eigen::Vector3d;using Mat=Eigen::MatrixXd;
struct Chart { V3 b[3],v[3],delta[3];V3 low,high;int face; };
struct Match { int face=-1,hits=0;V3 weights=V3::Zero(),normal=V3::Zero(),provider=V3::Zero(),bonus=V3::Zero();double distance=INFINITY,residual=0; };
static V3 eigen(Vec v){return {v.x,v.y,v.z};}
static Vec vector(V3 v){return {v.x(),v.y(),v.z()};}
static V3 weighted3(const V3* v,V3 w){return v[0]*w[0]+v[1]*w[1]+v[2]*w[2];}
static Chart chart(const Side& s,int face,double reach) {
    Chart c;c.face=face;double scale=0;
    for(int j=0;j<3;++j){auto v=s.faces[3*face+j];c.b[j]=eigen(s.base[v]);c.delta[j]=eigen(sub(s.own[v],s.base[v]));scale+=c.delta[j].norm()/3;}
    for(int j=0;j<3;++j)c.v[j]=scale>1e-12?c.delta[j]/scale:eigen(s.direction[s.faces[3*face+j]]);
    c.low=V3::Constant(INFINITY);c.high=V3::Constant(-INFINITY);
    for(int j=0;j<3;++j)for(double sign:{-1.,1.}){V3 p=c.b[j]+sign*reach*c.v[j];c.low=c.low.cwiseMin(p);c.high=c.high.cwiseMax(p);}
    return c;
}
static Eigen::Matrix3d derivative(const Chart& c,const V3& x) {
    Eigen::Matrix3d j;j.col(0)=c.b[1]-c.b[0]+x.z()*(c.v[1]-c.v[0]);
    j.col(1)=c.b[2]-c.b[0]+x.z()*(c.v[2]-c.v[0]);j.col(2)=weighted3(c.v,{1-x.x()-x.y(),x.x(),x.y()});return j;
}
static bool intersection(const Chart& c,V3 point,V3& w,double& distance,double& error) {
    if((point.array()<c.low.array()-1e-8).any()||(point.array()>c.high.array()+1e-8).any())return false;
    V3 x{1./3,1./3,0};auto lu=derivative(c,x).fullPivLu();if(!lu.isInvertible())return false;
    x+=lu.solve(point-weighted3(c.b,{1./3,1./3,1./3}));
    for(int i=0;i<12;++i){w={1-x.x()-x.y(),x.x(),x.y()};V3 r=weighted3(c.b,w)+x.z()*weighted3(c.v,w)-point;
        error=r.norm();if(error<1e-8)break;auto solve=derivative(c,x).fullPivLu();if(!solve.isInvertible())return false;x-=solve.solve(r);}
    w={1-x.x()-x.y(),x.x(),x.y()};distance=x.z();return error<1e-8&&w.minCoeff()>=-1e-8&&w.maxCoeff()<=1+1e-8;
}
static void consider(const Chart& c,V3 point,Match& out) {
    V3 w;double t,error;if(!intersection(c,point,w,t,error))return;
    V3 axis=weighted3(c.v,w);double signed_distance=t*axis.norm();if(axis.norm()<1e-12)return;
    ++out.hits;if(std::abs(signed_distance)>=std::abs(out.distance)-1e-10)return;
    out.face=c.face;out.weights=w;out.distance=signed_distance;out.residual=error;out.normal=axis.normalized();
    out.provider=weighted3(c.b,w)+weighted3(c.delta,w);out.bonus=weighted3(c.delta,w)+std::max(0.,-t)*axis;
}
static TriangleSnapshot chart_index(const std::vector<Chart>& charts) {
    TriangleSnapshot out;for(const auto& c:charts){Bounds b;b.index=c.face;
        for(int j=0;j<3;++j){b.lo[j]=c.low[j]-1e-8;b.hi[j]=c.high[j]+1e-8;}out.faces.push_back(b);}
    if(!out.faces.empty())build_bvh(out,0,int(out.faces.size()));return out;
}
static bool contains(const Bounds& b,V3 point) {
    for(int j=0;j<3;++j)if(point[j]<b.lo[j]||point[j]>b.hi[j])return false;return true;
}
static void query_charts(const TriangleSnapshot& index,const std::vector<Chart>& charts,int node,V3 point,Match& out) {
    const auto& n=index.nodes[node];if(!contains(n.bounds,point))return;
    if(n.left>=0){query_charts(index,charts,n.left,point,out);query_charts(index,charts,n.right,point,out);return;}
    for(int j=n.begin;j<n.end;++j)consider(charts[index.faces[j].index],point,out);
}
static std::vector<Match> correspondence(const Side& under,const Side& cover,double* stats,int workers,std::atomic<bool>& cancel) {
    double start=afs::now_ms(),reach=extent(under,cover)*4;std::vector<Chart> charts;
    for(int i=0;i<int(under.faces.size()/3);++i){require(!cancel,"PAIR_CANCELLED");charts.push_back(chart(under,i,reach));}
    auto index=chart_index(charts);std::vector<Match> result(cover.base.size());
    #pragma omp parallel for num_threads(std::max(1,std::min({4,workers,af_parallel_workers(int(cover.base.size()))}))) if(!omp_in_parallel())
    for(int i=0;i<int(cover.base.size());++i)if(!cancel&&!index.nodes.empty())query_charts(index,charts,0,eigen(cover.base[i]),result[i]);
    require(!cancel,"PAIR_CANCELLED");
    for(auto& m:result){
        if(m.face<0)continue;++stats[0];stats[1]+=m.hits>1;stats[2]=std::max(stats[2],std::max(0.,-m.distance));stats[3]=std::max(stats[3],m.residual);}
    stats[4]=afs::now_ms()-start;return result;
}
struct Correspondence { std::vector<Match> values;double stats[5]{}; };
static std::shared_ptr<Correspondence> cached_correspondence(const Side& under,const Side& cover,const State& state,std::atomic<bool>& cancel,bool& reused) {
    std::string key="vector-charts-v1";append_signature(key,under.base);append_signature(key,under.own);
    append_signature(key,under.direction);append_signature(key,under.faces);append_signature(key,cover.base);
    CacheKey id{1,cover.id,under.id};auto result=state.vector_cache->find<Correspondence>(id,key);reused=bool(result);if(result)return result;
    require(under.faces.size()/3*sizeof(Chart)+cover.base.size()*sizeof(Match)<=state.bases.settings.result_bytes,"STACK_VECTOR_CHART_BUDGET");
    result=std::make_shared<Correspondence>();result->values=correspondence(under,cover,result->stats,state.bases.settings.workers,cancel);
    state.vector_cache->put(id,std::move(key),result,sizeof(Correspondence)+result->values.capacity()*sizeof(Match),state.bases.settings.cache_bytes);return result;
}
static Mat positions(const std::vector<Vec>& points) {
    Mat result(points.size(),3);for(size_t i=0;i<points.size();++i)result.row(i)=eigen(points[i]);return result;
}

}

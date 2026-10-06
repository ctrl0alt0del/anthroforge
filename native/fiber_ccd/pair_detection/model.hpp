#pragma once
#include <memory>
#include <map>
#include <set>
#include <atomic>
namespace af_pair {
using Clock=std::chrono::steady_clock;
struct Settings {
    double search=.05,area=1e-10,epsilon=1e-9;
    int limit=2000000,workers=4;
    uint64_t cache_bytes=256ull<<20,result_bytes=256ull<<20;
};
struct Input {
    uint64_t id;
    const double *base,*own,*direction;
    const int64_t *faces,*parts,*sources;
    int vertices,triangles,family,root,instance,enabled,side;
    double displacement;
};
struct Side {
    uint64_t id=0,revision=1;
    std::vector<Vec> base,own,direction;
    std::vector<int64_t> faces,parts,sources;
    std::unique_ptr<TriangleSnapshot> snapshot;
    Bounds bounds{};
    double displacement=0;
    int family=0,root=0,instance=0,enabled=0,inflation_side=0;
};
struct Fragment {
    int64_t receiver,provider,receiver_face,provider_face,start,count;
    double area,gap_min,gap_max,alignment;
};
struct Point { double receiver[3],provider[3],world_receiver[3],world_provider[3]; };
struct PairRecord { int64_t first,second,start,count,warnings,points; };
struct Result {
    std::vector<Fragment> fragments;
    std::vector<Point> points;
    double profile[5]{},stats[10]{};
    uint64_t allocation_peak=0;
};
struct Budget {
    std::atomic<uint64_t> bytes{0},fragments{0},peak{0};
    std::atomic<bool>* cancelled=nullptr;
    uint64_t max_bytes,max_fragments;
};
struct PairSummary { int64_t fragments=0,points=0;double queries=0,warnings=0; };
struct CachedPair {
    std::shared_ptr<PairSummary> result;
    uint64_t a=0,b=0,used=0;
};
class PairResultCache {
    using Key=std::pair<int,int>;
    std::map<Key,CachedPair> entries;
    uint64_t clock=0;
public:
    void clear(){entries.clear();}
    void retain(const std::set<Key>& live);
    void invalidate(int domain);
    std::shared_ptr<PairSummary> find(Key key,uint64_t a,uint64_t b) const;
    void put(Key key,uint64_t a,uint64_t b,std::shared_ptr<PairSummary> value);
    void evict(uint64_t budget);
    uint64_t bytes() const { return entries.size()*(sizeof(CachedPair)+sizeof(PairSummary)+64); }
};
struct Published {
    std::vector<PairRecord> pairs;
    double stats[16]{};
    double storage[4]{};
    uint64_t generation=0;
};
struct Session {
    Settings settings;
    std::vector<Side> sides;
    std::map<uint64_t,int> indices;
    PairResultCache cache;
    Published published;
    Result result;
};
struct Query {
    const Side& receiver; const Side& provider; const Settings& settings;
    int r,p,rf; Vec triangle[3]; LyFrame frame; Vec origin{};
    bool gate=true; Vec edges[3]{},projected[3]{},own[3]{};
    double denominator=0; Budget* budget=nullptr;
};
static double milliseconds(Clock::time_point start) {
    return std::chrono::duration<double,std::milli>(Clock::now()-start).count();
}
static void require(bool valid,const char* message) {
    if(!valid)throw std::invalid_argument(message);
}
static bool finite(Vec v) {
    return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);
}
static Vec weighted(const Vec* v,Vec w) {
    return add(add(mul(v[0],w.x),mul(v[1],w.y)),mul(v[2],w.z));
}
static void face(const Side& s,int f,Vec* v) {
    for(int i=0;i<3;++i)v[i]=s.base[s.faces[f*3+i]];
}
static uint64_t bytes(const Result& r) {
    return r.fragments.capacity()*sizeof(Fragment)+r.points.capacity()*sizeof(Point);
}
}

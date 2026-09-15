// Exact expanded-roadmap preparation. No collision policy or worker ownership.
#pragma once
namespace af_roadmap {
using I = int64_t;
using Graph = std::vector<std::vector<I>>;
using Item = std::pair<double, I>;

static double distance(const double* p, I a, I b) {
    double x=p[3*a]-p[3*b], y=p[3*a+1]-p[3*b+1], z=p[3*a+2]-p[3*b+2];
    return std::sqrt((x*x+y*y)+z*z);
}

static bool valid(const double* p, I n, I old, I k, const I* offsets, const I* links, I size) {
    if (!p || !offsets || !links || n<2 || old<2 || old>n || k<0 || size<0) return false;
    if (n>std::numeric_limits<I>::max()/3 || offsets[0]!=0 || offsets[old]!=size) return false;
    for (I i=0;i<3*n;++i) if (!std::isfinite(p[i])) return false;
    for (I i=0;i<old;++i) if (offsets[i]<0 || offsets[i]>offsets[i+1]) return false;
    for (I i=0;i<size;++i) if (links[i]<0 || links[i]>=old) return false;
    return true;
}

static void nearest(const double* p, I n, I node, I k, std::vector<Item>& work) {
    work.clear(); work.reserve(n);
    for (I other=0;other<n;++other) if (other!=node) work.emplace_back(distance(p,node,other),other);
    k=std::min(k,n-1);
    if (k<I(work.size())) std::nth_element(work.begin(),work.begin()+k,work.end());
    work.resize(k); std::sort(work.begin(),work.end());
}

static void add_edge(Graph& graph, I a, I b) {
    graph[a].push_back(b); graph[b].push_back(a);
}

static Graph construct(const double* p, I n, I old, I k, const I* offsets, const I* links) {
    Graph graph(n); std::vector<Item> work;
    for (I i=0;i<old;++i) graph[i].assign(links+offsets[i],links+offsets[i+1]);
    for (I i=old;i<n;++i) {
        nearest(p,n,i,k,work); add_edge(graph,i,0); add_edge(graph,i,1);
        for (const auto& item:work) add_edge(graph,i,item.second);
    }
    return graph;
}

static I emit(Graph& graph, I* offsets, I* links, I capacity) {
    I used=0; offsets[0]=0;
    for (I i=0;i<I(graph.size());++i) {
        auto& row=graph[i]; std::sort(row.begin(),row.end());
        row.erase(std::unique(row.begin(),row.end()),row.end());
        if (I(row.size())>capacity-used) return -2;
        std::copy(row.begin(),row.end(),links+used); used+=I(row.size()); offsets[i+1]=used;
    }
    return used;
}
}

AF_EXPORT int64_t af_roadmap_neighbors(const double* p, int64_t n, int64_t old, int64_t k,
    const int64_t* offsets, const int64_t* links, int64_t size,
    int64_t* out_offsets, int64_t* out_links, int64_t capacity) {
    try {
        if (!out_offsets || !out_links || capacity<0 || !af_roadmap::valid(p,n,old,k,offsets,links,size)) return -1;
        auto graph=af_roadmap::construct(p,n,old,k,offsets,links);
        return af_roadmap::emit(graph,out_offsets,out_links,capacity);
    } catch (...) { return -3; }
}

AF_EXPORT int af_roadmap_nearest_batch(const double* p, int64_t n, int64_t first,
    int64_t count, int64_t k, int64_t* output) {
    try {
        if (!p || !output || n<2 || first<0 || count<0 || count>64 || first>n-count || k<0 || k>=n) return -1;
        if (n>std::numeric_limits<int64_t>::max()/3) return -1;
        for (int64_t i=0;i<3*n;++i) if (!std::isfinite(p[i])) return -1;
        std::vector<af_roadmap::Item> work;
        for (int64_t i=0;i<count;++i) {
            af_roadmap::nearest(p,n,first+i,k,work);
            for (int64_t j=0;j<k;++j) output[i*k+j]=work[j].second;
        }
        return 0;
    } catch (...) { return -3; }
}

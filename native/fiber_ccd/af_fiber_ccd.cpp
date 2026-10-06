#include <algorithm>
#include <array>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <cmath>
#include <cstdint>
#include <limits>
#include <mutex>
#include <numeric>
#include <queue>
#include <stdexcept>
#include <unordered_map>
#include <tuple>
#include <thread>
#include <utility>
#include <vector>
#ifdef _OPENMP
#include <omp.h>
#endif

#define AF_EXPORT extern "C" __declspec(dllexport)
#include "af_roadmap_preparation.hpp"

constexpr int AF_V3_CCD_JOB_PAIRS=128;
constexpr int AF_V3_INDEXED_CLEAR_STREAK=4;

struct Vec { double x, y, z; };
struct Sweep { double safe, upper, clearance, minimum; int possible, valid, intervals, reason; };
struct MeshSweep { double safe; int possible, valid, tested, intervals, reason, limiting; };
struct Context { Vec a0, b0, a1, b1, t[3]; double clearance, speed, guard; };
struct Search { std::vector<std::pair<double, double>> stack; double safe, minimum; int intervals; };
struct Bounds { double lo[3], hi[3]; int index; };
struct BvhNode { Bounds bounds; int left, right, begin, end; };
struct TriangleSnapshot {
    std::vector<Vec> vertices; std::vector<int64_t> triangles;
    std::vector<Bounds> faces; std::vector<BvhNode> nodes;
    std::vector<Bounds> indexed_faces;
};

static Vec add(Vec a, Vec b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
static Vec sub(Vec a, Vec b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
static Vec mul(Vec a, double s) { return {a.x * s, a.y * s, a.z * s}; }
static double dot(Vec a, Vec b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static Vec cross(Vec a, Vec b) { return {a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z, a.x*b.y-a.y*b.x}; }
static double norm(Vec a) { return std::sqrt(dot(a, a)); }
static Vec load3(const double* p) { return {p[0], p[1], p[2]}; }
static double eps() { return 128.0 * std::numeric_limits<double>::epsilon(); }

static int af_parallel_limit() {
#ifdef _OPENMP
    return std::max(1,std::min(4,omp_get_num_procs()));
#else
    return 1;
#endif
}

static int af_requested_workers=af_parallel_limit();
static int af_parallel_workers(int count) {
#if defined(_OPENMP) && defined(AF_V3_OPERATION_EXPERIMENT)
    if(omp_in_parallel())return 1;
#endif
    return count<16?1:af_requested_workers;
}
static bool af_parallel_batch(int count) { return af_parallel_workers(count)>1; }
static int af_task_workers(int count) { return std::max(1,std::min(count,af_requested_workers)); }

static int af_v3_ccd_workers(int pairs) {
#ifdef _OPENMP
    if(omp_in_parallel())return 1;
#endif
    if(af_requested_workers<2)return 1;
    return pairs>=AF_V3_CCD_JOB_PAIRS*af_requested_workers?af_requested_workers:1;
}

static int af_parallel_capability() {
#ifdef _OPENMP
    return 8192;
#else
    return 0;
#endif
}

static int af_llvm_openmp_capability() {
#if defined(_OPENMP) && defined(__clang__)
    return 16384;
#else
    return 0;
#endif
}

static int af_v3_session_capability() { return 32768; }
static int af_v3_batch_capability() { return 65536; }
static int af_v3_indexed_ccd_capability() { return 1048576; }
static int af_v3_native_world_capability() { return 2097152; }
static int af_v3_operations_capability() {
#if defined(AF_V3_OPERATION_EXPERIMENT) || defined(AF_V3_NATIVE_CONTROLLER)
    return 131072;
#else
    return 0;
#endif
}

static int af_v3_coordinator_capability() {
#if defined(AF_V3_OPERATION_EXPERIMENT) || defined(AF_V3_NATIVE_CONTROLLER)
    return 262144;
#else
    return 0;
#endif
}

static int af_v3_native_sqp_capability() {
#if defined(AF_V3_OPERATION_EXPERIMENT) || defined(AF_V3_NATIVE_CONTROLLER)
    return 524288;
#else
    return 0;
#endif
}

static int af_v3_resumable_sqp_capability() {
#if defined(AF_V3_OPERATION_EXPERIMENT) || defined(AF_V3_NATIVE_CONTROLLER)
    return 4194304;
#else
    return 0;
#endif
}

static int af_v3_multi_sqp_capability() {
#if defined(AF_V3_OPERATION_EXPERIMENT) || defined(AF_V3_NATIVE_CONTROLLER)
    return 8388608;
#else
    return 0;
#endif
}

static int af_v3_async_sqp_capability() {
#if defined(AF_V3_OPERATION_EXPERIMENT) || defined(AF_V3_NATIVE_CONTROLLER)
    return 16777216;
#else
    return 0;
#endif
}

static int af_attachment_wave_capability() { return 33554432; }
static int af_muscle_numeric_capability() { return 67108864; }

static double point_segment(Vec p, Vec a, Vec b) {
    Vec d = sub(b, a);
    double length = dot(d, d);
    if (length <= eps()) return norm(sub(p, a));
    double f = std::clamp(dot(sub(p, a), d) / length, 0.0, 1.0);
    return norm(sub(p, add(a, mul(d, f))));
}

static bool projection_inside(Vec p, const Vec* t) {
    Vec a = sub(t[1], t[0]), b = sub(t[2], t[0]), o = sub(p, t[0]);
    double aa = dot(a, a), ab = dot(a, b), bb = dot(b, b);
    double ap = dot(o, a), bp = dot(o, b), det = aa * bb - ab * ab;
    if (det <= eps() * std::max(1.0, aa * bb)) return false;
    double u = (bb * ap - ab * bp) / det;
    double v = (aa * bp - ab * ap) / det;
    return u >= -eps() && v >= -eps() && u + v <= 1.0 + eps();
}

static double point_triangle(Vec p, const Vec* t) {
    Vec n = cross(sub(t[1], t[0]), sub(t[2], t[0]));
    double n2 = dot(n, n);
    if (n2 > eps()) {
        double s = dot(sub(p, t[0]), n) / n2;
        Vec projection = sub(p, mul(n, s));
        if (projection_inside(projection, t)) return std::abs(s) * std::sqrt(n2);
    }
    return std::min({point_segment(p,t[0],t[1]), point_segment(p,t[1],t[2]), point_segment(p,t[2],t[0])});
}

static double interior_segments(Vec a0, Vec a1, Vec b0, Vec b1) {
    Vec a = sub(a1, a0), b = sub(b1, b0), o = sub(a0, b0);
    double aa=dot(a,a), ab=dot(a,b), bb=dot(b,b), ao=dot(a,o), bo=dot(b,o);
    double det = aa * bb - ab * ab;
    if (det <= eps() * std::max(1.0, aa * bb)) return INFINITY;
    double s = (ab * bo - bb * ao) / det, t = (aa * bo - ab * ao) / det;
    if (s < 0.0 || s > 1.0 || t < 0.0 || t > 1.0) return INFINITY;
    return norm(sub(add(a0, mul(a, s)), add(b0, mul(b, t))));
}

static double segment_segment(Vec a0, Vec a1, Vec b0, Vec b1) {
    return std::min({interior_segments(a0,a1,b0,b1), point_segment(a0,b0,b1),
                     point_segment(a1,b0,b1), point_segment(b0,a0,a1),
                     point_segment(b1,a0,a1)});
}

static bool segment_hits(Vec a, Vec b, const Vec* t) {
    Vec d=sub(b,a), e0=sub(t[1],t[0]), e1=sub(t[2],t[0]), c=cross(d,e1);
    double det=dot(e0,c), scale=std::max(1.0,norm(d)*norm(e0)*norm(e1));
    if (std::abs(det) <= eps() * scale) return false;
    Vec o=sub(a,t[0]); double inv=1.0/det, u=dot(o,c)*inv;
    Vec co=cross(o,e0); double v=dot(d,co)*inv, f=dot(e1,co)*inv;
    return u>=-eps() && v>=-eps() && u+v<=1.0+eps() && f>=-eps() && f<=1.0+eps();
}

static double segment_triangle(Vec a, Vec b, const Vec* t) {
    if (segment_hits(a, b, t)) return 0.0;
    double result = std::min(point_triangle(a, t), point_triangle(b, t));
    for (int i=0; i<3; ++i) result=std::min(result,segment_segment(a,b,t[i],t[(i+1)%3]));
    return result;
}

static Vec at(Vec start, Vec end, double time) { return add(start, mul(sub(end, start), time)); }
static double distance_at(const Context& c, double time) { return segment_triangle(at(c.a0,c.a1,time),at(c.b0,c.b1,time),c.t); }

static bool bounds_overlap(const Context& c) {
    for (int axis=0; axis<3; ++axis) {
        const double* a=&c.a0.x; const double* b=&c.b0.x; const double* d=&c.a1.x; const double* e=&c.b1.x;
        double lo=std::min({a[axis],b[axis],d[axis],e[axis]})-c.clearance-c.guard;
        double hi=std::max({a[axis],b[axis],d[axis],e[axis]})+c.clearance+c.guard;
        double tl=std::min({(&c.t[0].x)[axis],(&c.t[1].x)[axis],(&c.t[2].x)[axis]});
        double th=std::max({(&c.t[0].x)[axis],(&c.t[1].x)[axis],(&c.t[2].x)[axis]});
        if (hi < tl || th < lo) return false;
    }
    return true;
}

static Sweep result(const Context& c, double safe, double upper, double minimum, int possible, int valid, int intervals, int reason) {
    return {safe, upper, distance_at(c, safe), minimum, possible, valid, intervals, reason};
}

static bool certified(const Context& c, double lo, double hi, double& distance) {
    double mid=0.5*(lo+hi); distance=distance_at(c,mid);
    return distance-c.speed*0.5*(hi-lo)-c.guard > c.clearance;
}

static Sweep subdivide(const Context& c, double start, double tolerance, int budget) {
    Search s{{{0.0,1.0}},0.0,start,0};
    while (!s.stack.empty()) {
        if (s.intervals >= budget) return result(c,s.safe,s.stack.back().second,s.minimum,1,1,s.intervals,4);
        auto [lo,hi]=s.stack.back(); s.stack.pop_back(); double distance=0.0;
        bool clear=certified(c,lo,hi,distance); ++s.intervals; s.minimum=std::min(s.minimum,distance);
        if (clear) { s.safe=std::max(s.safe,hi); continue; }
        if (hi-lo <= tolerance) return result(c,s.safe,hi,s.minimum,1,1,s.intervals,3);
        double mid=0.5*(lo+hi); s.stack.push_back({mid,hi}); s.stack.push_back({lo,mid});
    }
    return result(c,1.0,1.0,s.minimum,0,1,s.intervals,0);
}

static Context context(const double* start, const double* end, const double* triangle, double clearance) {
    Context c{load3(start),load3(start+3),load3(end),load3(end+3),{},clearance,0.0,0.0};
    for (int i=0; i<3; ++i) c.t[i]=load3(triangle+3*i);
    c.speed=std::max(norm(sub(c.a1,c.a0)),norm(sub(c.b1,c.b0)));
    double scale=1.0;
    for (int i=0; i<6; ++i) scale=std::max(scale,std::abs(start[i])),scale=std::max(scale,std::abs(end[i]));
    for (int i=0; i<9; ++i) scale=std::max(scale,std::abs(triangle[i]));
    c.guard=eps()*scale; return c;
}

AF_EXPORT int af_fiber_ccd_version() { return 3; }

AF_EXPORT int af_fiber_ccd_capabilities() {
    return 8191|134217728|268435456|af_parallel_capability()|af_llvm_openmp_capability()|
           af_v3_session_capability()|af_v3_batch_capability()|af_v3_indexed_ccd_capability()|af_v3_native_world_capability()|af_v3_operations_capability()|
           af_v3_coordinator_capability()|af_v3_native_sqp_capability()|af_v3_resumable_sqp_capability()|af_v3_multi_sqp_capability()|af_v3_async_sqp_capability()|af_attachment_wave_capability()|af_muscle_numeric_capability();
}

AF_EXPORT int af_fiber_worker_threads() { return af_requested_workers; }
AF_EXPORT int af_fiber_indexed_ccd_threshold() { return AF_V3_CCD_JOB_PAIRS*af_requested_workers; }
AF_EXPORT int af_fiber_indexed_ccd_parallel(int pairs) { return af_v3_ccd_workers(pairs)>1; }

AF_EXPORT int af_fiber_set_worker_threads(int count) {
    if(count<1)return 1;af_requested_workers=std::min(count,af_parallel_limit());return 0;
}

AF_EXPORT int af_segment_triangle_distances(const double* segments, const double* triangles,
                                             int count, double* distances) {
    if (!segments || !triangles || !distances || count < 0) return 1;
#pragma omp parallel for schedule(static) if(af_parallel_batch(count)) num_threads(af_parallel_workers(count))
    for (int i=0; i<count; ++i) {
        Vec face[3]={load3(triangles+9*i),load3(triangles+9*i+3),load3(triangles+9*i+6)};
        distances[i]=segment_triangle(load3(segments+6*i),load3(segments+6*i+3),face);
    }
    return 0;
}

static bool ray_hits_triangle(Vec point, Vec direction, const Vec* triangle) {
    Vec edge0=sub(triangle[1],triangle[0]),edge1=sub(triangle[2],triangle[0]);
    Vec crossed=cross(direction,edge1); double determinant=dot(edge0,crossed);
    if (std::abs(determinant)<=eps()) return false;
    Vec offset=sub(point,triangle[0]); double inverse=1.0/determinant;
    double u=dot(offset,crossed)*inverse; if (u<-eps() || u>1.0+eps()) return false;
    Vec side=cross(offset,edge0); double v=dot(direction,side)*inverse;
    return v>=-eps() && u+v<=1.0+eps() && dot(edge1,side)*inverse>eps();
}

static bool point_inside_mesh(Vec point, const double* vertices, const int64_t* triangles, int count) {
    Vec directions[3]={{1.0,0.3713906763541037,0.6941734212143177},
                       {0.2191374213412347,1.0,0.5379137453123419},
                       {0.6123419734213147,0.2931742134123471,1.0}};
    int votes=0;
    for (Vec direction: directions) {
        int hits=0;
        for (int f=0; f<count; ++f) {
            Vec face[3]={load3(vertices+3*triangles[3*f]),load3(vertices+3*triangles[3*f+1]),load3(vertices+3*triangles[3*f+2])};
            if (ray_hits_triangle(point,direction,face)) ++hits;
        }
        votes+=hits%2;
    }
    return votes>=2;
}

AF_EXPORT int af_points_inside_closed_mesh(const double* points, int point_count,
                                             const double* vertices, const int64_t* triangles,
                                             int triangle_count, int* inside) {
    if (!points || !vertices || !triangles || !inside || point_count < 0 || triangle_count < 0) return 1;
#pragma omp parallel for schedule(static) if(af_parallel_batch(point_count)) num_threads(af_parallel_workers(point_count))
    for (int p=0; p<point_count; ++p) {
        inside[p]=point_inside_mesh(load3(points+3*p),vertices,triangles,triangle_count) ? 1 : 0;
    }
    return 0;
}

AF_EXPORT int af_swept_segment_triangle(const double* start, const double* end,
                                         const double* triangle, double clearance,
                                         double tolerance, int budget, Sweep* output) {
    if (!start || !end || !triangle || !output || clearance < 0.0 || tolerance <= 0.0 || budget < 1) return 1;
    Context c=context(start,end,triangle,clearance); double initial=distance_at(c,0.0);
    if (initial <= clearance+c.guard) { *output=result(c,0.0,0.0,initial,1,0,0,2); return 0; }
    if (!bounds_overlap(c)) { *output=result(c,1.0,1.0,initial,0,1,0,1); return 0; }
    if (c.speed <= c.guard) { *output=result(c,1.0,1.0,initial,0,1,0,1); return 0; }
    *output=subdivide(c,initial,tolerance,budget); return 0;
}

static Sweep sweep_pair(const double* start, const double* end, const double* triangle,
                        double clearance, double tolerance, int budget) {
    Context c=context(start,end,triangle,clearance); double initial=distance_at(c,0.0);
    if (initial <= clearance+c.guard) return result(c,0.0,0.0,initial,1,0,0,2);
    if (!bounds_overlap(c) || c.speed <= c.guard) return result(c,1.0,1.0,initial,0,1,0,1);
    return subdivide(c,initial,tolerance,budget);
}

static void scaled_end(const double* start, const double* end, double safe, double* output) {
    for (int i=0; i<6; ++i) output[i]=start[i]+safe*(end[i]-start[i]);
}

static bool absorb_mesh(MeshSweep& mesh, const Sweep& pair, int index) {
    ++mesh.tested; mesh.intervals+=pair.intervals;
    mesh.valid=mesh.valid && pair.valid; mesh.possible=mesh.possible || pair.possible;
    if (pair.reason == 4) mesh.reason=4;
    if (pair.safe<1.0) mesh.limiting=index; mesh.safe*=pair.safe;
    return mesh.valid && mesh.safe > 0.0;
}

AF_EXPORT int af_mesh_pair_safe_step(const double* starts, const double* ends,
                                      const double* triangles, int pairs, double clearance,
                                      double tolerance, int budget, MeshSweep* output) {
    if (!starts || !ends || !triangles || !output || pairs < 0 || clearance < 0.0) return 1;
    MeshSweep mesh{1.0,0,1,0,0,0,-1}; double scaled[6];
    for (int i=0; i<pairs; ++i) {
        scaled_end(starts+6*i,ends+6*i,mesh.safe,scaled);
        Sweep pair=sweep_pair(starts+6*i,scaled,triangles+9*i,clearance,tolerance,budget);
        if (!absorb_mesh(mesh,pair,i)) break;
    }
    mesh.reason=!mesh.valid ? 2 : mesh.reason == 4 ? 4 : mesh.possible ? 3 : 0;
    *output=mesh; return 0;
}

static Bounds face_bounds(const double* vertices, const int64_t* triangle, int index) {
    Vec face[3]={load3(vertices+3*triangle[0]),load3(vertices+3*triangle[1]),load3(vertices+3*triangle[2])};
    Bounds bounds{{},{},index}; const double* f[3]={&face[0].x,&face[1].x,&face[2].x};
    for (int axis=0; axis<3; ++axis) {
        bounds.lo[axis]=std::min({f[0][axis],f[1][axis],f[2][axis]});
        bounds.hi[axis]=std::max({f[0][axis],f[1][axis],f[2][axis]});
    }
    return bounds;
}

static Bounds moving_bounds(const double* start, const double* end, const int64_t* edge, double padding) {
    Vec p[4]={load3(start+3*edge[0]),load3(start+3*edge[1]),load3(end+3*edge[0]),load3(end+3*edge[1])};
    Bounds bounds{}; const double* f[4]={&p[0].x,&p[1].x,&p[2].x,&p[3].x};
    for (int axis=0; axis<3; ++axis) {
        bounds.lo[axis]=std::min({f[0][axis],f[1][axis],f[2][axis],f[3][axis]})-padding;
        bounds.hi[axis]=std::max({f[0][axis],f[1][axis],f[2][axis],f[3][axis]})+padding;
    }
    return bounds;
}

static bool bounds_overlap(const Bounds& moving, const Bounds& face) {
    for (int axis=0; axis<3; ++axis)
        if (moving.hi[axis] < face.lo[axis] || face.hi[axis] < moving.lo[axis]) return false;
    return true;
}

static Bounds empty_bounds() {
    Bounds value{};
    for (int a=0; a<3; ++a) value.lo[a]=INFINITY,value.hi[a]=-INFINITY;
    return value;
}

static Bounds merge_bounds(Bounds value, const Bounds& other) {
    for (int a=0; a<3; ++a) value.lo[a]=std::min(value.lo[a],other.lo[a]),value.hi[a]=std::max(value.hi[a],other.hi[a]);
    return value;
}

static int longest_axis(const Bounds& value) {
    double x=value.hi[0]-value.lo[0],y=value.hi[1]-value.lo[1],z=value.hi[2]-value.lo[2];
    return x>=y && x>=z ? 0 : y>=z ? 1 : 2;
}

static int build_bvh(TriangleSnapshot& snapshot, int begin, int end) {
    Bounds bounds=empty_bounds(); for (int i=begin; i<end; ++i) bounds=merge_bounds(bounds,snapshot.faces[i]);
    int node=int(snapshot.nodes.size()); snapshot.nodes.push_back({bounds,-1,-1,begin,end});
    if (end-begin<=8) return node;
    int axis=longest_axis(bounds),middle=(begin+end)/2;
    std::stable_sort(snapshot.faces.begin()+begin,snapshot.faces.begin()+end,[axis](const Bounds& a,const Bounds& b){
        double ca=a.lo[axis]+a.hi[axis],cb=b.lo[axis]+b.hi[axis]; return ca==cb ? a.index<b.index : ca<cb; });
    snapshot.nodes[node].left=build_bvh(snapshot,begin,middle); snapshot.nodes[node].right=build_bvh(snapshot,middle,end);
    return node;
}

static Bounds refit_bvh(TriangleSnapshot& snapshot,int index) {
    auto& node=snapshot.nodes[index];Bounds value=empty_bounds();
    if(node.left>=0)value=merge_bounds(refit_bvh(snapshot,node.left),refit_bvh(snapshot,node.right));
    else for(int row=node.begin;row<node.end;++row)value=merge_bounds(value,snapshot.faces[row]);
    node.bounds=value;return value;
}

static bool update_snapshot(TriangleSnapshot& snapshot,const double* vertices,int count) {
    if(!vertices||count!=int(snapshot.vertices.size()))return false;
    for(int i=0;i<3*count;++i)if(!std::isfinite(vertices[i]))return false;
    for(int i=0;i<count;++i)snapshot.vertices[i]=load3(vertices+3*i);
    for(auto& face:snapshot.faces){face=face_bounds(vertices,snapshot.triangles.data()+3*face.index,face.index);
        snapshot.indexed_faces[size_t(face.index)]=face;}
    if(!snapshot.nodes.empty())refit_bvh(snapshot,0);return true;
}

static void collect_candidates(const TriangleSnapshot& snapshot, int node, const Bounds& moving, std::vector<int>& hits) {
    const BvhNode& value=snapshot.nodes[node]; if (!bounds_overlap(moving,value.bounds)) return;
    if (value.left>=0) { collect_candidates(snapshot,value.left,moving,hits); collect_candidates(snapshot,value.right,moving,hits); return; }
    for (int i=value.begin; i<value.end; ++i) if (bounds_overlap(moving,snapshot.faces[i])) hits.push_back(snapshot.faces[i].index);
}

static int emit_candidates(const TriangleSnapshot& snapshot, const Bounds& moving, int edge, int64_t* output, int count) {
    std::vector<int> hits; if (!snapshot.nodes.empty()) collect_candidates(snapshot,0,moving,hits);
    std::sort(hits.begin(),hits.end());
    for (int face: hits) { if (output) output[2*count]=edge,output[2*count+1]=face; ++count; }
    return count;
}

static TriangleSnapshot* create_snapshot(const double* vertices, const int64_t* triangles, int count) {
    auto* snapshot=new TriangleSnapshot(); int maximum=-1;
    snapshot->triangles.assign(triangles,triangles+3*count);
    for (int i=0; i<3*count; ++i) maximum=std::max(maximum,int(triangles[i]));
    snapshot->vertices.reserve(maximum+1); for (int i=0; i<=maximum; ++i) snapshot->vertices.push_back(load3(vertices+3*i));
    snapshot->faces.reserve(count); for (int i=0; i<count; ++i) snapshot->faces.push_back(face_bounds(vertices,triangles+3*i,i));
    snapshot->indexed_faces=snapshot->faces;
    if (count) build_bvh(*snapshot,0,count); return snapshot;
}

AF_EXPORT void* af_triangle_snapshot_create(const double* vertices, const int64_t* triangles,
                                             int triangle_count) {
    if (!vertices || !triangles || triangle_count < 0) return nullptr;
    return create_snapshot(vertices,triangles,triangle_count);
}

AF_EXPORT void af_triangle_snapshot_destroy(void* handle) {
    delete static_cast<TriangleSnapshot*>(handle);
}

static void snapshot_face(const TriangleSnapshot& snapshot, int index, Vec* face) {
    for (int i=0; i<3; ++i) face[i]=snapshot.vertices[size_t(snapshot.triangles[size_t(3*index+i)])];
}

static bool snapshot_faces_valid(const TriangleSnapshot& snapshot,const int64_t* faces,int count) {
    for(int i=0;i<count;++i)if(faces[i]<0||faces[i]*3+2>=int64_t(snapshot.triangles.size()))return false;
    return true;
}

AF_EXPORT int af_snapshot_segment_triangle_distances(void* handle, const double* segments,
                                                       const int64_t* faces, int count, double* distances) {
    if (!handle || !segments || !faces || !distances || count < 0) return 1;
    const auto& snapshot=*static_cast<TriangleSnapshot*>(handle);
    if(!snapshot_faces_valid(snapshot,faces,count))return 1;
#pragma omp parallel for schedule(static) if(af_parallel_batch(count)) num_threads(af_parallel_workers(count))
    for (int i=0; i<count; ++i) {
        int face_index=int(faces[i]);
        Vec face[3]; snapshot_face(snapshot,face_index,face);
        distances[i]=segment_triangle(load3(segments+6*i),load3(segments+6*i+3),face);
    }
    return 0;
}

static bool ray_hits_bounds(Vec point, Vec direction, const Bounds& bounds) {
    double low=0.0,high=INFINITY; const double* p=&point.x; const double* d=&direction.x;
    for (int axis=0; axis<3; ++axis) {
        double first=(bounds.lo[axis]-p[axis])/d[axis],last=(bounds.hi[axis]-p[axis])/d[axis];
        if (first>last) std::swap(first,last); low=std::max(low,first); high=std::min(high,last);
        if (high<low) return false;
    }
    return high>eps();
}

static int snapshot_ray_hits(const TriangleSnapshot& snapshot, Vec point, Vec direction, int first, int count) {
    std::vector<int> stack{0}; int hits=0,limit=first+count;
    while (!stack.empty()) {
        int index=stack.back(); stack.pop_back(); const auto& node=snapshot.nodes[index];
        if (!ray_hits_bounds(point,direction,node.bounds)) continue;
        if (node.left>=0) { stack.push_back(node.left); stack.push_back(node.right); continue; }
        for (int i=node.begin; i<node.end; ++i) if (snapshot.faces[i].index>=first && snapshot.faces[i].index<limit) {
            Vec face[3]; snapshot_face(snapshot,snapshot.faces[i].index,face); hits+=ray_hits_triangle(point,direction,face); }
    }
    return hits;
}

static bool snapshot_inside(const TriangleSnapshot& snapshot, Vec point, int first, int count) {
    Vec directions[3]={{1.0,0.3713906763541037,0.6941734212143177},
                       {0.2191374213412347,1.0,0.5379137453123419},
                       {0.6123419734213147,0.2931742134123471,1.0}};
    int votes=0; for (Vec direction: directions) votes+=snapshot_ray_hits(snapshot,point,direction,first,count)%2;
    return votes>=2;
}

AF_EXPORT int af_snapshot_points_inside_range(void* handle, const double* points, int point_count,
                                                int face_start, int face_count, int* inside) {
    if (!handle || !points || !inside || point_count<0 || face_start<0 || face_count<0) return 1;
    const auto& snapshot=*static_cast<TriangleSnapshot*>(handle);
    if (face_start+face_count>int(snapshot.triangles.size()/3)) return 1;
#pragma omp parallel for schedule(static) if(af_parallel_batch(point_count)) num_threads(af_parallel_workers(point_count))
    for (int i=0; i<point_count; ++i) inside[i]=snapshot_inside(snapshot,load3(points+3*i),face_start,face_count);
    return 0;
}

AF_EXPORT int af_snapshot_candidate_pairs(void* handle, const double* start, const double* end,
                                           const int64_t* edges, int edge_count, double padding,
                                           int64_t* output) {
    if (!handle || !start || !end || !edges || edge_count < 0 || padding < 0.0) return -1;
    const auto& snapshot=*static_cast<TriangleSnapshot*>(handle); int count=0;
    for (int e=0; e<edge_count; ++e)
        count=emit_candidates(snapshot,moving_bounds(start,end,edges+2*e,padding),e,output,count);
    return count;
}

AF_EXPORT int af_candidate_pairs(const double* start, const double* end, const int64_t* edges,
                                  int edge_count, const double* vertices, const int64_t* triangles,
                                  int triangle_count, double padding, int64_t* output) {
    if (!vertices || !triangles || triangle_count < 0) return -1;
    TriangleSnapshot* snapshot=create_snapshot(vertices,triangles,triangle_count); int count=0;
    for (int e=0; e<edge_count; ++e) count=emit_candidates(*snapshot,moving_bounds(start,end,edges+2*e,padding),e,output,count);
    delete snapshot;
    return count;
}

#include "af_fiber_planner43.hpp"
#include "af_fiber_contact3.hpp"
#include "af_warning_async.hpp"
#include "af_fiber_v3_session.hpp"
#include "af_fiber_v3_batch.hpp"
#include "af_attachment_wave.hpp"
#include "af_muscle_numeric.hpp"
#include "af_muscle_envelope_profile.hpp"
#include "af_muscle_envelope_compose.hpp"
#include "pair_detection/api.hpp"
#include "layer_stacking/api.hpp"
#include "layer_stacking/relationship_api.hpp"
#include "af_base_spline.hpp"
#include "af_base_partition.hpp"
#include "af_transfer_shape.hpp"
#include "af_transfer_constraints_report.hpp"
#include "af_attachment_graft.hpp"
#if defined(AF_V3_OPERATION_EXPERIMENT) || defined(AF_V3_NATIVE_CONTROLLER)
#include "af_fiber_v3_operations.hpp"
#include "af_fiber_v3_coordinator.hpp"
#include "af_fiber_v3_native_sqp.hpp"
#endif

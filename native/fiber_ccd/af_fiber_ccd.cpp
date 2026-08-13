#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <utility>
#include <vector>

#define AF_EXPORT extern "C" __declspec(dllexport)

struct Vec { double x, y, z; };
struct Sweep { double safe, upper, clearance, minimum; int possible, valid, intervals, reason; };
struct MeshSweep { double safe; int possible, valid, tested, intervals, reason; };
struct Context { Vec a0, b0, a1, b1, t[3]; double clearance, speed, guard; };
struct Search { std::vector<std::pair<double, double>> stack; double safe, minimum; int intervals; };
struct Bounds { double lo[3], hi[3]; int index; };

static Vec add(Vec a, Vec b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
static Vec sub(Vec a, Vec b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
static Vec mul(Vec a, double s) { return {a.x * s, a.y * s, a.z * s}; }
static double dot(Vec a, Vec b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static Vec cross(Vec a, Vec b) { return {a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z, a.x*b.y-a.y*b.x}; }
static double norm(Vec a) { return std::sqrt(dot(a, a)); }
static Vec load3(const double* p) { return {p[0], p[1], p[2]}; }
static double eps() { return 128.0 * std::numeric_limits<double>::epsilon(); }

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

AF_EXPORT int af_fiber_ccd_version() { return 1; }

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

static bool absorb_mesh(MeshSweep& mesh, const Sweep& pair) {
    ++mesh.tested; mesh.intervals+=pair.intervals;
    mesh.valid=mesh.valid && pair.valid; mesh.possible=mesh.possible || pair.possible;
    mesh.safe*=pair.safe;
    return mesh.valid && mesh.safe > 0.0;
}

AF_EXPORT int af_mesh_pair_safe_step(const double* starts, const double* ends,
                                      const double* triangles, int pairs, double clearance,
                                      double tolerance, int budget, MeshSweep* output) {
    if (!starts || !ends || !triangles || !output || pairs < 0 || clearance < 0.0) return 1;
    MeshSweep mesh{1.0,0,1,0,0,0}; double scaled[6];
    for (int i=0; i<pairs; ++i) {
        scaled_end(starts+6*i,ends+6*i,mesh.safe,scaled);
        Sweep pair=sweep_pair(starts+6*i,scaled,triangles+9*i,clearance,tolerance,budget);
        if (!absorb_mesh(mesh,pair)) break;
    }
    mesh.reason=!mesh.valid ? 2 : mesh.possible ? 3 : 0; *output=mesh; return 0;
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

static std::vector<Bounds> sorted_faces(const double* vertices, const int64_t* triangles, int count) {
    std::vector<Bounds> faces; faces.reserve(count);
    for (int i=0; i<count; ++i) faces.push_back(face_bounds(vertices,triangles+3*i,i));
    std::sort(faces.begin(),faces.end(),[](const Bounds& a,const Bounds& b){return a.lo[0]<b.lo[0];});
    return faces;
}

static int emit_candidates(const Bounds& moving, const std::vector<Bounds>& faces, int edge, int64_t* output, int count) {
    for (const Bounds& face: faces) {
        if (face.lo[0] > moving.hi[0]) break;
        if (!bounds_overlap(moving,face)) continue;
        if (output) output[2*count]=edge,output[2*count+1]=face.index; ++count;
    }
    return count;
}

AF_EXPORT int af_candidate_pairs(const double* start, const double* end, const int64_t* edges,
                                  int edge_count, const double* vertices, const int64_t* triangles,
                                  int triangle_count, double padding, int64_t* output) {
    int count=0;
    std::vector<Bounds> faces=sorted_faces(vertices,triangles,triangle_count);
    for (int e=0; e<edge_count; ++e) {
        Bounds moving=moving_bounds(start,end,edges+2*e,padding);
        count=emit_candidates(moving,faces,e,output,count);
    }
    return count;
}

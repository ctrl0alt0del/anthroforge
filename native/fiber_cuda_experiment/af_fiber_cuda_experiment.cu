#include <cuda_runtime.h>
#include <algorithm>
#include <cfloat>
#include <cstdint>
#include <limits>

#define AF_EXPORT extern "C" __declspec(dllexport)

struct Vec { double x, y, z; };
struct Timers { cudaEvent_t begin, uploaded, solved, downloaded; };
struct World {
    double *triangles, *segments, *distances;
    int32_t *segment_ids, *triangle_ids;
    int triangle_count, segment_capacity, pair_capacity, cached_pairs;
    Timers timers;
};

__host__ __device__ static Vec add(Vec a, Vec b) { return {a.x+b.x,a.y+b.y,a.z+b.z}; }
__host__ __device__ static Vec sub(Vec a, Vec b) { return {a.x-b.x,a.y-b.y,a.z-b.z}; }
__host__ __device__ static Vec mul(Vec a, double s) { return {a.x*s,a.y*s,a.z*s}; }
__host__ __device__ static double dot(Vec a, Vec b) { return a.x*b.x+a.y*b.y+a.z*b.z; }
__host__ __device__ static Vec cross(Vec a, Vec b) { return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x}; }
__host__ __device__ static double norm(Vec a) { return sqrt(dot(a,a)); }
__host__ __device__ static Vec load3(const double* p) { return {p[0],p[1],p[2]}; }
__host__ __device__ static double epsilon() { return 2.8421709430404007e-14; }

__device__ static double point_segment(Vec p, Vec a, Vec b) {
    Vec d=sub(b,a); double length=dot(d,d);
    if(length<=epsilon())return norm(sub(p,a));
    double f=fmin(1.0,fmax(0.0,dot(sub(p,a),d)/length));
    return norm(sub(p,add(a,mul(d,f))));
}

__device__ static bool projection_inside(Vec p, const Vec* t) {
    Vec a=sub(t[1],t[0]),b=sub(t[2],t[0]),o=sub(p,t[0]);
    double aa=dot(a,a),ab=dot(a,b),bb=dot(b,b),ap=dot(o,a),bp=dot(o,b);
    double det=aa*bb-ab*ab;
    if(det<=epsilon()*fmax(1.0,aa*bb))return false;
    double u=(bb*ap-ab*bp)/det,v=(aa*bp-ab*ap)/det;
    return u>=-epsilon()&&v>=-epsilon()&&u+v<=1.0+epsilon();
}

__device__ static double point_triangle(Vec p, const Vec* t) {
    Vec n=cross(sub(t[1],t[0]),sub(t[2],t[0])); double n2=dot(n,n);
    if(n2>epsilon()){
        double s=dot(sub(p,t[0]),n)/n2; Vec q=sub(p,mul(n,s));
        if(projection_inside(q,t))return fabs(s)*sqrt(n2);
    }
    return fmin(point_segment(p,t[0],t[1]),fmin(point_segment(p,t[1],t[2]),point_segment(p,t[2],t[0])));
}

__device__ static double interior_segments(Vec a0, Vec a1, Vec b0, Vec b1) {
    Vec a=sub(a1,a0),b=sub(b1,b0),o=sub(a0,b0);
    double aa=dot(a,a),ab=dot(a,b),bb=dot(b,b),ao=dot(a,o),bo=dot(b,o);
    double det=aa*bb-ab*ab;
    if(det<=epsilon()*fmax(1.0,aa*bb))return DBL_MAX;
    double s=(ab*bo-bb*ao)/det,t=(aa*bo-ab*ao)/det;
    if(s<0.0||s>1.0||t<0.0||t>1.0)return DBL_MAX;
    return norm(sub(add(a0,mul(a,s)),add(b0,mul(b,t))));
}

__device__ static double segment_segment(Vec a0, Vec a1, Vec b0, Vec b1) {
    double d=interior_segments(a0,a1,b0,b1);
    d=fmin(d,point_segment(a0,b0,b1)); d=fmin(d,point_segment(a1,b0,b1));
    d=fmin(d,point_segment(b0,a0,a1)); return fmin(d,point_segment(b1,a0,a1));
}

__device__ static bool segment_hits(Vec a, Vec b, const Vec* t) {
    Vec d=sub(b,a),e0=sub(t[1],t[0]),e1=sub(t[2],t[0]),c=cross(d,e1);
    double det=dot(e0,c),scale=fmax(1.0,norm(d)*norm(e0)*norm(e1));
    if(fabs(det)<=epsilon()*scale)return false;
    Vec o=sub(a,t[0]); double inv=1.0/det,u=dot(o,c)*inv;
    Vec co=cross(o,e0); double v=dot(d,co)*inv,f=dot(e1,co)*inv;
    return u>=-epsilon()&&v>=-epsilon()&&u+v<=1.0+epsilon()&&f>=-epsilon()&&f<=1.0+epsilon();
}

__device__ static double segment_triangle(Vec a, Vec b, const Vec* t) {
    if(segment_hits(a,b,t))return 0.0;
    double result=fmin(point_triangle(a,t),point_triangle(b,t));
    result=fmin(result,segment_segment(a,b,t[0],t[1]));
    result=fmin(result,segment_segment(a,b,t[1],t[2]));
    return fmin(result,segment_segment(a,b,t[2],t[0]));
}

__global__ static void indexed_distances(const double* segments,const double* triangles,
                                         const int32_t* segment_ids,const int32_t* triangle_ids,
                                         int count,double* distances) {
    int i=blockIdx.x*blockDim.x+threadIdx.x; if(i>=count)return;
    const double* s=segments+6*segment_ids[i],*p=triangles+9*triangle_ids[i];
    Vec face[3]={load3(p),load3(p+3),load3(p+6)};
    distances[i]=segment_triangle(load3(s),load3(s+3),face);
}

static int checked(cudaError_t status) { return status==cudaSuccess?0:static_cast<int>(status); }

static int create_timers(Timers& timers) {
    if(checked(cudaEventCreate(&timers.begin)))return 1;
    if(checked(cudaEventCreate(&timers.uploaded)))return 1;
    if(checked(cudaEventCreate(&timers.solved)))return 1;
    return checked(cudaEventCreate(&timers.downloaded));
}

static void destroy_timers(Timers& timers) {
    cudaEventDestroy(timers.begin); cudaEventDestroy(timers.uploaded);
    cudaEventDestroy(timers.solved); cudaEventDestroy(timers.downloaded);
}

static int allocate_world(World* world) {
    size_t triangles=sizeof(double)*9*world->triangle_count;
    size_t segments=sizeof(double)*6*world->segment_capacity;
    size_t pairs=sizeof(int32_t)*world->pair_capacity;
    if(checked(cudaMalloc(&world->triangles,triangles)))return 1;
    if(checked(cudaMalloc(&world->segments,segments)))return 1;
    if(checked(cudaMalloc(&world->segment_ids,pairs)))return 1;
    if(checked(cudaMalloc(&world->triangle_ids,pairs)))return 1;
    return checked(cudaMalloc(&world->distances,sizeof(double)*world->pair_capacity));
}

static void free_world(World* world) {
    cudaFree(world->triangles); cudaFree(world->segments);
    cudaFree(world->segment_ids); cudaFree(world->triangle_ids);
    cudaFree(world->distances); destroy_timers(world->timers);
}

static int upload_world(World* world,const double* triangles) {
    size_t bytes=sizeof(double)*9*world->triangle_count;
    return checked(cudaMemcpy(world->triangles,triangles,bytes,cudaMemcpyHostToDevice));
}

static int upload_segments(World* world,const double* segments,int count) {
    size_t bytes=sizeof(double)*6*count;
    return checked(cudaMemcpyAsync(world->segments,segments,bytes,cudaMemcpyHostToDevice));
}

static int upload_pairs(World* world,const int32_t* segment_ids,const int32_t* triangle_ids,int count) {
    size_t bytes=sizeof(int32_t)*count;
    if(checked(cudaMemcpyAsync(world->segment_ids,segment_ids,bytes,cudaMemcpyHostToDevice)))return 1;
    return checked(cudaMemcpyAsync(world->triangle_ids,triangle_ids,bytes,cudaMemcpyHostToDevice));
}

static int record_timings(World* world,float* times) {
    if(checked(cudaEventSynchronize(world->timers.downloaded)))return 1;
    cudaEventElapsedTime(times,world->timers.begin,world->timers.uploaded);
    cudaEventElapsedTime(times+1,world->timers.uploaded,world->timers.solved);
    cudaEventElapsedTime(times+2,world->timers.solved,world->timers.downloaded);
    return checked(cudaEventElapsedTime(times+3,world->timers.begin,world->timers.downloaded));
}

static int run_query(World* world,int count,double* distances,float* times) {
    int blocks=(count+255)/256;
    if(checked(cudaEventRecord(world->timers.uploaded)))return 1;
    indexed_distances<<<blocks,256>>>(world->segments,world->triangles,world->segment_ids,world->triangle_ids,count,world->distances);
    if(checked(cudaEventRecord(world->timers.solved)))return 1;
    if(checked(cudaMemcpyAsync(distances,world->distances,sizeof(double)*count,cudaMemcpyDeviceToHost)))return 1;
    if(checked(cudaEventRecord(world->timers.downloaded)))return 1;
    return record_timings(world,times);
}

AF_EXPORT int af_cuda_device_count() {
    int count=0; return checked(cudaGetDeviceCount(&count))?0:count;
}

AF_EXPORT const char* af_cuda_error_name(int code) { return cudaGetErrorName(static_cast<cudaError_t>(code)); }

AF_EXPORT int af_cuda_world_create(const double* triangles,int triangle_count,
                                   int segment_capacity,int pair_capacity,void** handle) {
    if(!triangles||!handle||triangle_count<1||segment_capacity<1||pair_capacity<1)return -1;
    World* world=new World{}; world->triangle_count=triangle_count;
    world->segment_capacity=segment_capacity; world->pair_capacity=pair_capacity;
    if(allocate_world(world)||create_timers(world->timers)||upload_world(world,triangles)){free_world(world);delete world;return -2;}
    *handle=world; return 0;
}

AF_EXPORT int af_cuda_world_destroy(void* handle) {
    if(!handle)return 0; World* world=static_cast<World*>(handle);
    free_world(world); delete world; return 0;
}

AF_EXPORT int af_cuda_upload_pairs(void* handle,const int32_t* segment_ids,
                                   const int32_t* triangle_ids,int count) {
    World* world=static_cast<World*>(handle);
    if(!world||!segment_ids||!triangle_ids||count<1||count>world->pair_capacity)return -1;
    if(upload_pairs(world,segment_ids,triangle_ids,count))return -2;
    world->cached_pairs=count; return checked(cudaDeviceSynchronize());
}

AF_EXPORT int af_cuda_distances(void* handle,const double* segments,int segment_count,
                                const int32_t* segment_ids,const int32_t* triangle_ids,
                                int pair_count,double* distances,float* times) {
    World* world=static_cast<World*>(handle);
    if(!world||!segments||!segment_ids||!triangle_ids||!distances||!times)return -1;
    if(segment_count<1||segment_count>world->segment_capacity||pair_count<1||pair_count>world->pair_capacity)return -1;
    if(checked(cudaEventRecord(world->timers.begin)))return -2;
    if(upload_segments(world,segments,segment_count)||upload_pairs(world,segment_ids,triangle_ids,pair_count))return -2;
    return run_query(world,pair_count,distances,times);
}

AF_EXPORT int af_cuda_distances_cached(void* handle,const double* segments,int segment_count,
                                       double* distances,float* times) {
    World* world=static_cast<World*>(handle);
    if(!world||!segments||!distances||!times||world->cached_pairs<1)return -1;
    if(segment_count<1||segment_count>world->segment_capacity)return -1;
    if(checked(cudaEventRecord(world->timers.begin)))return -2;
    if(upload_segments(world,segments,segment_count))return -2;
    return run_query(world,world->cached_pairs,distances,times);
}

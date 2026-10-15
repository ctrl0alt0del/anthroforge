#pragma once
#include <deque>
#include "af_skin_tile_storage.hpp"
namespace af_skin {
struct TileCoordinate { int x,y,z; };
struct SkinTiles {
    GapScene* scene; WrapGrid grid; std::vector<float> coarse; SkinTileValues values;
    std::array<int,3> coarse_shape; std::array<double,4> coarse_transform;
    int nx,ny,nz; uint64_t budget,peak_bytes=0,initial_tiles=0,propagation_tiles=0; double reach,offset; bool finalized=false;
    std::vector<int> lookup,surface_tiles; std::vector<TileCoordinate> coordinates;
    std::vector<unsigned char> flags,target_xy; Separators separators; std::vector<Vec> corridor_checks;
};
inline void wrap_skin_tiles(SkinTiles& t);
inline void apply_gap_corridors(SkinTiles& t);
inline bool exterior_gap(const SkinTiles& t,const double* sample);
inline std::string tile_budget_error(const SkinTiles& t,const char* reason) {
    return std::string("Unresolved gap precision: ")+reason+" exceeds the worker memory budget ("+
        std::to_string(t.budget/(1024*1024))+" MiB; voxel "+std::to_string(t.grid.h)+
        "; lattice "+std::to_string(t.grid.nx)+" x "+std::to_string(t.grid.ny)+" x "+std::to_string(t.grid.nz)+"). Previous output retained.";
}
inline void tile_cancelled(const SkinTiles& t) {
    if(t.scene->cancelled)throw std::runtime_error("Draft skin generation was cancelled.");
    if(t.values.exhausted)throw std::runtime_error(tile_budget_error(t,"varying field storage"));
}
inline uint64_t tile_auxiliary_bytes(const SkinTiles& t) {
    return t.coarse.capacity()*sizeof(float)+t.lookup.capacity()*sizeof(int)+t.coordinates.capacity()*sizeof(TileCoordinate)+
        t.flags.capacity()+t.target_xy.capacity()+t.separators.items.capacity()*sizeof(Separator)+
        t.separators.nodes.capacity()*sizeof(SeparatorNode)+t.corridor_checks.capacity()*sizeof(Vec)+t.surface_tiles.capacity()*sizeof(int);
}
inline void tile_memory_stage(SkinTiles& t,uint64_t scratch=0) {
    uint64_t fixed=tile_auxiliary_bytes(t)+scratch+t.values.blocks.capacity()*sizeof(void*)+t.values.constants.capacity()*sizeof(float);
    if(fixed+t.values.resident>t.budget)throw std::runtime_error(tile_budget_error(t,"native skin storage"));
    t.values.limit=t.budget-fixed; t.peak_bytes=std::max(t.peak_bytes,fixed+t.values.peak.load());
}
inline void tile_stage(SkinTiles& t,int stage,int total) {
    tile_cancelled(t); tile_memory_stage(t); t.scene->done=0; t.scene->total=total; t.scene->stage=stage;
}
inline size_t tile_slot(const SkinTiles& t,int x,int y,int z) {
    return (size_t(x)*t.ny+y)*t.nz+z;
}
inline int64_t tile_cell(const SkinTiles& t,int x,int y,int z) {
    if(x<0 || y<0 || z<0 || x>=t.nx*SKIN_TILE || y>=t.ny*SKIN_TILE || z>=t.nz*SKIN_TILE)return -1;
    int block=t.lookup[tile_slot(t,x/SKIN_TILE,y/SKIN_TILE,z/SKIN_TILE)]; if(block<0)return -1;
    return int64_t(block)*SKIN_CELLS+((x%SKIN_TILE)*SKIN_TILE+y%SKIN_TILE)*SKIN_TILE+z%SKIN_TILE;
}
inline TileCoordinate cell_coordinate(const SkinTiles& t,size_t cell) {
    const auto& b=t.coordinates[cell/SKIN_CELLS]; int local=int(cell%SKIN_CELLS);
    return {b.x*SKIN_TILE+local/(SKIN_TILE*SKIN_TILE),b.y*SKIN_TILE+(local/SKIN_TILE)%SKIN_TILE,
            b.z*SKIN_TILE+local%SKIN_TILE};
}
inline Vec tile_point(const SkinTiles& t,TileCoordinate c) { return t.grid.point(c.x,c.y,c.z); }
inline float skin_cell_value(const SkinTiles& t,size_t i) {
    float value=t.values[i];
    return t.finalized && value==1.e20f?std::min(float(std::sqrt(double(value))),coarse_value(t.grid,tile_point(t,cell_coordinate(t,i)))):value;
}
inline void materialize_final_tile(SkinTiles& t,size_t b) {
    if(t.values.blocks[b] || t.values.constants[b]!=1.e20f)return;
    if(!t.values.materialize(b))return;
    for(int j=0;j<SKIN_CELLS;++j) {
        size_t i=b*SKIN_CELLS+j; t.values.set(i,skin_cell_value(t,i));
    }
}
inline float tile_value(const SkinTiles& t,int x,int y,int z) {
    int64_t index=tile_cell(t,x,y,z);
    return index<0?-float(t.grid.h):skin_cell_value(t,size_t(index));
}
inline double interpolate_skin(const SkinTiles& t,Vec p) {
    Vec q=mul(sub(p,t.grid.origin),1/t.grid.h); int a[3]; double w[3];
    for(int k=0;k<3;++k) { a[k]=int(std::floor((&q.x)[k])); w[k]=(&q.x)[k]-a[k]; }
    double value=0;
    for(int i=0;i<8;++i) { int x=i&1,y=(i>>1)&1,z=(i>>2)&1;
        value+=tile_value(t,a[0]+x,a[1]+y,a[2]+z)*(x?w[0]:1-w[0])*(y?w[1]:1-w[1])*(z?w[2]:1-w[2]); }
    return value;
}
inline bool tile_has_skin(const SkinTiles& t,int x,int y,int z) {
    Vec a=t.grid.point(x*SKIN_TILE,y*SKIN_TILE,z*SKIN_TILE);
    Vec b=t.grid.point((x+1)*SKIN_TILE,(y+1)*SKIN_TILE,(z+1)*SKIN_TILE);
    a=mul(sub(a,load3(t.grid.transform)),1/t.grid.transform[3]);
    b=mul(sub(b,load3(t.grid.transform)),1/t.grid.transform[3]); int low[3],high[3];
    for(int k=0;k<3;++k) { low[k]=std::clamp(int(std::floor((&a.x)[k])),0,t.grid.shape[k]-1);
        high[k]=std::clamp(int(std::ceil((&b.x)[k])),0,t.grid.shape[k]-1); }
    for(int i=low[0];i<=high[0];++i)for(int j=low[1];j<=high[1];++j)for(int k=low[2];k<=high[2];++k)
        if(t.coarse[(size_t(i)*t.grid.shape[1]+j)*t.grid.shape[2]+k]>=-2*t.grid.h)return true;
    return false;
}
inline void allocate_skin_tiles(SkinTiles& t) {
    t.lookup.assign(size_t(t.nx)*t.ny*t.nz,-1);
    for(int x=0;x<t.nx;++x)for(int y=0;y<t.ny;++y)for(int z=0;z<t.nz;++z) {
        if(!tile_has_skin(t,x,y,z))continue;
        t.lookup[tile_slot(t,x,y,z)]=int(t.coordinates.size()); t.coordinates.push_back({x,y,z});
    }
    uint64_t cells=uint64_t(t.coordinates.size())*SKIN_CELLS;
    if(cells>t.budget || cells>UINT32_MAX)throw std::runtime_error("Unresolved gap precision: active tile flags exceed the worker memory budget.");
    t.values.resize(size_t(cells)); t.flags.resize(size_t(cells));
    t.initial_tiles=t.coordinates.size(); t.target_xy.resize(size_t(t.nx)*t.ny);
    for(auto c:t.coordinates)t.target_xy[size_t(c.x)*t.ny+c.y]=1; tile_memory_stage(t);
}
inline void sample_skin_cell(SkinTiles& t,size_t i) {
    Vec p=tile_point(t,cell_coordinate(t,i)); double old=coarse_value(t.grid,p);
    if(old<-2*t.grid.h) { t.flags[i]=8; return; }
    double s[13]; sample(*t.scene,p,t.reach,s);
    if(s[0]<=.8*t.grid.h)return;
    t.flags[i]=old<0?8:1;
    bool gap=s[1]>0 && s[0]>=s[1]*.4 && (s[1]>s[2] || s[3]<1) &&
        resolve_gap_center(*t.scene,s,t.reach) && exterior_gap(t,s);
    if(gap)t.flags[i]|=16;
    double radius=gap?empty_radius(s,t.offset,t.grid.h):old<0?std::max(0.,s[0]-std::max(t.offset,.8*t.grid.h)):0;
    if(radius>0)t.values.set(i,-float(radius*radius));
}
inline void sample_skin_tiles(SkinTiles& t) {
    tile_stage(t,1,int(t.coordinates.size()));
#pragma omp parallel for schedule(dynamic) num_threads(af_parallel_workers(int(t.coordinates.size())))
    for(int b=0;b<int(t.coordinates.size());++b) {
        if(t.scene->cancelled || t.values.exhausted)continue;
        for(int i=0;i<SKIN_CELLS;++i)sample_skin_cell(t,size_t(b)*SKIN_CELLS+i); ++t.scene->done;
    }
    tile_cancelled(t);
}
inline void visit_skin_cell(SkinTiles& t,std::deque<uint32_t>& queue,int x,int y,int z) {
    int64_t i=tile_cell(t,x,y,z); if(i<0 || (t.flags[size_t(i)]&15)!=1)return;
    t.flags[size_t(i)]=static_cast<unsigned char>((t.flags[size_t(i)]&16)|2); queue.push_back(uint32_t(i));
}
inline void flood_skin_neighbors(SkinTiles& t,std::deque<uint32_t>& queue,size_t i) {
    auto c=cell_coordinate(t,i);
    visit_skin_cell(t,queue,c.x-1,c.y,c.z); visit_skin_cell(t,queue,c.x+1,c.y,c.z);
    visit_skin_cell(t,queue,c.x,c.y-1,c.z); visit_skin_cell(t,queue,c.x,c.y+1,c.z);
    visit_skin_cell(t,queue,c.x,c.y,c.z-1); visit_skin_cell(t,queue,c.x,c.y,c.z+1);
}
inline void flood_skin_tiles(SkinTiles& t) {
    tile_stage(t,2,int(t.flags.size())); std::deque<uint32_t> queue; size_t head=0;
    for(size_t i=0;i<t.flags.size();++i)if((t.flags[i]&15)==8)flood_skin_neighbors(t,queue,i);
    while(!queue.empty()) {
        if((head&65535)==0) { tile_cancelled(t); t.scene->done=int(head);
            if(t.values.bytes()+tile_auxiliary_bytes(t)+queue.size()*4>t.budget)throw std::runtime_error("Exterior flood exceeds the worker memory budget."); }
        size_t cell=queue.front(); queue.pop_front(); flood_skin_neighbors(t,queue,cell); ++head;
    }
}
inline void add_skin_separator(SkinTiles& t,size_t i) {
    unsigned char flag=t.flags[i]; if(!(flag&16) || (flag&15)<2)return;
    double s[13]; sample(*t.scene,tile_point(t,cell_coordinate(t,i)),t.reach,s);
    if(!resolve_gap_center(*t.scene,s,t.reach) || !exterior_gap(t,s))return;
    Vec center=load3(s+6); double half=std::max(1.8*t.grid.h,s[1]*.5-t.offset);
    double radius=std::max(t.offset*2,coarse_value(t.grid,center)+t.offset);
    double strength=s[1]>s[2] || s[2]<=0?0:s[3];
    t.separators.items.push_back({center,load3(s+9),half,radius,strength,s[1],s[2],int(s[4]),int(s[5])});
}
inline void build_skin_separators(SkinTiles& t) {
    tile_stage(t,3,int(t.coordinates.size()));
    for(int b=0;b<int(t.coordinates.size());++b) {
        tile_cancelled(t); for(int i=0;i<SKIN_CELLS;++i)add_skin_separator(t,size_t(b)*SKIN_CELLS+i);
        ++t.scene->done; tile_memory_stage(t);
    }
    tile_memory_stage(t,t.separators.items.size()*(sizeof(int)+sizeof(SeparatorNode)));
    std::vector<int> order(t.separators.items.size()); std::iota(order.begin(),order.end(),0);
    t.separators.nodes.reserve(order.size());
    build_separators(t.separators,order,0,int(order.size()),0);
}
inline void classify_skin_void(SkinTiles& t) {
    t.flags.resize(t.values.size());
    tile_memory_stage(t);
    for(size_t i=0;i<t.flags.size();++i) {
        auto c=cell_coordinate(t,i); bool boundary=c.x==0||c.y==0||c.z==0||c.x==t.nx*SKIN_TILE-1||
            c.y==t.ny*SKIN_TILE-1||c.z==t.nz*SKIN_TILE-1;
        t.flags[i]=skin_cell_value(t,i)>=0?0:(boundary||coarse_value(t.grid,tile_point(t,c))<-2*t.grid.h?8:1);
    }
    flood_skin_tiles(t);
}
inline void close_skin_block(SkinTiles& t,size_t b) {
    materialize_final_tile(t,b);
    for(size_t i=b*SKIN_CELLS;i<(b+1)*SKIN_CELLS;++i) {
        float value=t.flags[i]==1?float(t.grid.h):std::clamp(t.values[i],-float(t.grid.h),float(t.grid.h));
        if(std::abs(value)<t.grid.h*.01)value=float(std::copysign(t.grid.h*.01,value));
        t.values.set(i,value);
    }
    t.values.compact(b);
}
inline void close_skin_cavities(SkinTiles& t) {
    classify_skin_void(t);
    for(size_t b=0;b<t.coordinates.size();++b) { tile_cancelled(t); close_skin_block(t,b); }
    t.flags.clear(); t.flags.shrink_to_fit();
}
inline void select_skin_surfaces(SkinTiles& t) {
    for(int b=0;b<int(t.coordinates.size());++b) {
        auto c=t.coordinates[b]; float low=INFINITY,high=-INFINITY;
        for(int x=0;x<=SKIN_TILE;++x)for(int y=0;y<=SKIN_TILE;++y)for(int z=0;z<=SKIN_TILE;++z) {
            float f=tile_value(t,c.x*SKIN_TILE+x,c.y*SKIN_TILE+y,c.z*SKIN_TILE+z);
            low=std::min(low,f); high=std::max(high,f); }
        if(low<0 && high>0)t.surface_tiles.push_back(b);
    }
    uint64_t storage=t.values.bytes()+tile_auxiliary_bytes(t);
    if(storage+uint64_t(32)*SKIN_SAMPLES*4>t.budget)
        throw std::runtime_error("Unresolved gap precision: surface tiles exceed the worker memory budget.");
}
inline void init_skin_tiles(SkinTiles& t,GapScene* scene,const float* coarse,const int* cshape,const double* ctransform,
                            const int* shape,const double* transform,double reach,double offset,uint64_t budget) {
    t.scene=scene; t.budget=budget; t.reach=reach; t.offset=offset;
    std::copy(cshape,cshape+3,t.coarse_shape.begin()); std::copy(ctransform,ctransform+4,t.coarse_transform.begin());
    t.coarse.assign(coarse,coarse+size_t(cshape[0])*cshape[1]*cshape[2]);
    t.grid={shape[0],shape[1],shape[2],transform[3],load3(transform),nullptr,t.coarse.data(),
            t.coarse_shape.data(),t.coarse_transform.data(),{}};
    t.nx=(shape[0]+31)/32; t.ny=(shape[1]+31)/32; t.nz=(shape[2]+31)/32;
    allocate_skin_tiles(t); sample_skin_tiles(t); flood_skin_tiles(t); build_skin_separators(t);
    wrap_skin_tiles(t); close_skin_cavities(t); select_skin_surfaces(t); tile_cancelled(t);
}
inline void copy_skin_tile(const SkinTiles& t,int input,int output,int* starts,float* values) {
    auto c=t.coordinates[t.surface_tiles[input]]; int* start=starts+3*output;
    start[0]=c.x*SKIN_TILE; start[1]=c.y*SKIN_TILE; start[2]=c.z*SKIN_TILE;
    float* field=values+size_t(output)*SKIN_SAMPLES;
    for(int x=0;x<=SKIN_TILE;++x)for(int y=0;y<=SKIN_TILE;++y)for(int z=0;z<=SKIN_TILE;++z)
        field[(x*33+y)*33+z]=tile_value(t,start[0]+x,start[1]+y,start[2]+z);
}
}
AF_EXPORT void* af_skin_tiles_create(void* scene,const float* coarse,const int* cshape,const double* ctransform,
                                     const int* shape,const double* transform,double reach,double offset,uint64_t budget) {
    if(!scene || !coarse || !cshape || !ctransform || !shape || !transform)return nullptr;
    auto& s=*static_cast<af_skin::GapScene*>(scene);
    if(!af_skin::valid_skin_grid(shape,transform,budget) || !af_skin::valid_skin_grid(cshape,ctransform,budget) ||
       !std::isfinite(reach) || reach<=0 || !std::isfinite(offset) || offset<0) { s.error="Invalid draft-skin field input or memory budget."; return nullptr; }
    try {
        auto t=std::make_unique<af_skin::SkinTiles>();
        af_skin::init_skin_tiles(*t,&s,coarse,cshape,ctransform,shape,transform,reach,offset,budget); return t.release();
    } catch(const std::exception& error) { s.error=error.what(); return nullptr; }
}
AF_EXPORT void af_skin_tiles_destroy(void* tiles) { delete static_cast<af_skin::SkinTiles*>(tiles); }
AF_EXPORT int af_skin_tiles_count(void* tiles) { return tiles?int(static_cast<af_skin::SkinTiles*>(tiles)->surface_tiles.size()):0; }
AF_EXPORT int af_skin_tiles_copy(void* tiles,int* starts,float* values) {
    if(!tiles || !starts || !values)return 1; const auto& t=*static_cast<af_skin::SkinTiles*>(tiles);
#pragma omp parallel for schedule(static) num_threads(af_parallel_workers(int(t.surface_tiles.size())))
    for(int i=0;i<int(t.surface_tiles.size());++i)af_skin::copy_skin_tile(t,i,i,starts,values);
    return 0;
}
AF_EXPORT int af_skin_tiles_copy_range(void* tiles,int first,int count,int* starts,float* values) {
    if(!tiles || !starts || !values || first<0 || count<0)return 1;
    const auto& t=*static_cast<af_skin::SkinTiles*>(tiles);
    if(size_t(first)+size_t(count)>t.surface_tiles.size())return 1;
#pragma omp parallel for schedule(static) num_threads(af_parallel_workers(count))
    for(int i=0;i<count;++i)af_skin::copy_skin_tile(t,first+i,i,starts,values);
    return 0;
}
AF_EXPORT void af_skin_tiles_release_field(void* tiles) {
    if(!tiles)return; auto& t=*static_cast<af_skin::SkinTiles*>(tiles);
    t.values.resize(0); t.flags.clear(); t.flags.shrink_to_fit(); t.coarse.clear(); t.coarse.shrink_to_fit();
}
AF_EXPORT int af_skin_tiles_sample(void* tiles,const double* points,int count,double* values) {
    if(!tiles || !points || !values || count<0)return 1; const auto& t=*static_cast<af_skin::SkinTiles*>(tiles);
#pragma omp parallel for schedule(static) num_threads(af_parallel_workers(count))
    for(int i=0;i<count;++i)values[i]=af_skin::interpolate_skin(t,load3(points+3*i)); return 0;
}

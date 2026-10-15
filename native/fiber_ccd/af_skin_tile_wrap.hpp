#pragma once
namespace af_skin {
inline void extend_skin_block(SkinTiles& t,TileCoordinate c,int axis,double radius) {
    int position=(&c.x)[axis],limits[3]={t.nx,t.ny,t.nz};
    int spread=int(std::ceil((radius+2*t.grid.h)/(SKIN_TILE*t.grid.h)));
    for(int k=std::max(0,position-spread);k<=std::min(limits[axis]-1,position+spread);++k) {
        (&c.x)[axis]=k; size_t slot=tile_slot(t,c.x,c.y,c.z); if(t.lookup[slot]>=0)continue;
        if(axis==1 && !t.target_xy[size_t(c.x)*t.ny+c.y])continue;
        t.lookup[slot]=int(t.coordinates.size()); t.coordinates.push_back(c);
    }
}
inline void extend_skin_axis(SkinTiles& t,int axis,int slab) {
    int blocks=int(t.coordinates.size());
    for(int b=0;b<blocks;++b) {
        if(t.coordinates[b].z!=slab)continue;
        float minimum=t.values.minimum(size_t(b));
        if(minimum<0)extend_skin_block(t,t.coordinates[b],axis,std::sqrt(-double(minimum)));
    }
    uint64_t cells=uint64_t(t.coordinates.size())*SKIN_CELLS;
    if(cells>UINT32_MAX)throw std::runtime_error("Unresolved gap precision: sphere propagation exceeds supported indexing.");
    t.values.resize(size_t(cells),1.e20f);
    t.propagation_tiles=std::max(t.propagation_tiles,uint64_t(t.coordinates.size()));
    tile_memory_stage(t);
}
inline int64_t axis_skin_cell(const SkinTiles& t,int axis,int line,int q) {
    int ny=t.ny*SKIN_TILE,nz=t.nz*SKIN_TILE;
    if(axis==0)return tile_cell(t,q,line/nz,line%nz);
    if(axis==1)return tile_cell(t,line/nz,q,line%nz);
    return tile_cell(t,line/ny,line%ny,q);
}
inline void distance_skin_line(SkinTiles& t,int axis,int line,int count) {
    std::vector<float> row(count,1.e20f); bool active=false;
    for(int q=0;q<count;++q) { int64_t i=axis_skin_cell(t,axis,line,q);
        if(i>=0) { row[q]=t.values[size_t(i)]; active=active||row[q]<0; } }
    if(!active)return;
    distance_line(row,t.grid.h*t.grid.h);
    // Positive distances also affect the pre-clamp corridor interpolation; retain them exactly.
    for(int q=0;q<count;++q) { int64_t i=axis_skin_cell(t,axis,line,q);
        if(i>=0 && (axis!=2 || size_t(i)/SKIN_CELLS<t.initial_tiles))
            t.values.set(size_t(i),row[q]); }
}
inline void distance_skin_column(SkinTiles& t,int axis,int column,int count) {
    int second=axis==2?t.ny:t.nz,first=column/second,last=column%second;
    // One worker owns every row of a tile column, including lazy allocations.
    for(int i=0;i<SKIN_TILE;++i)for(int j=0;j<SKIN_TILE;++j) {
        if(t.scene->cancelled || t.values.exhausted)return;
        distance_skin_line(t,axis,(first*SKIN_TILE+i)*second*SKIN_TILE+last*SKIN_TILE+j,count);
    }
}
inline void distance_skin_axis(SkinTiles& t,int axis,int slab=-1) {
    if(axis<2)extend_skin_axis(t,axis,slab);
    int dimensions[3]={t.nx*SKIN_TILE,t.ny*SKIN_TILE,t.nz*SKIN_TILE},count=dimensions[axis];
    int columns=axis==0?t.ny:(axis==1?t.nx:t.nx*t.ny); tile_stage(t,4,columns);
    tile_memory_stage(t,uint64_t(af_parallel_workers(columns))*count*24);
#pragma omp parallel for schedule(dynamic) num_threads(af_parallel_workers(columns))
    for(int column=0;column<columns;++column) {
        if(t.scene->cancelled || (axis==2 && !t.target_xy[column]))continue;
        distance_skin_column(t,axis,axis==2?column:column*t.nz+slab,count); ++t.scene->done;
    }
    tile_cancelled(t);
}
inline void compact_skin_slab(SkinTiles& t,int slab) {
    for(size_t b=0;b<t.coordinates.size();++b) {
        auto c=t.coordinates[b]; if(c.z!=slab)continue;
        if(!t.target_xy[size_t(c.x)*t.ny+c.y]) {
            if(t.values.blocks[b]) { t.values.blocks[b].reset(); t.values.resident-=SKIN_CELLS*sizeof(float); }
            t.values.constants[b]=1.e20f;
        } else t.values.compact(b);
    }
}
inline void retain_skin_targets(SkinTiles& t) {
    // Excluded tiles have a coarse-field upper bound below -2h and cannot contain skin.
    for(size_t b=t.initial_tiles;b<t.coordinates.size();++b) {
        auto c=t.coordinates[b]; t.lookup[tile_slot(t,c.x,c.y,c.z)]=-1;
    }
    t.values.resize(t.initial_tiles*SKIN_CELLS); t.coordinates.resize(t.initial_tiles); tile_memory_stage(t);
}
inline void finish_wrapped_skin(SkinTiles& t) {
    int blocks=int(t.coordinates.size()); tile_stage(t,4,blocks);
#pragma omp parallel for schedule(dynamic) num_threads(af_parallel_workers(blocks))
    for(int b=0;b<blocks;++b) {
        if(t.scene->cancelled)continue;
        if(!t.values.blocks[b] && t.values.constants[b]==1.e20f) { ++t.scene->done; continue; }
        for(int j=0;j<SKIN_CELLS;++j) { size_t i=size_t(b)*SKIN_CELLS+j; double value=t.values[i];
            value=std::copysign(std::sqrt(std::abs(value)),value);
            t.values.set(i,float(std::min(value,double(coarse_value(t.grid,tile_point(t,cell_coordinate(t,i))))))); }
        ++t.scene->done;
    }
    t.finalized=true;
    tile_cancelled(t);
}
inline double gap_clearance(const SkinTiles& t,Vec p,double offset) {
    if(t.separators.items.empty())return offset;
    CloseSeparators close; nearby_separators(t.separators,p,0,close); double result=offset;
    for(int i=0;i<close.count;++i) { const auto& s=t.separators.items[close.ids[i]];
        Vec delta=sub(p,s.center); double normal=dot(delta,s.normal);
        double radial=std::sqrt(std::max(0.,dot(delta,delta)-normal*normal));
        if(std::abs(normal)>s.width*.5 || radial>s.radius)continue;
        double local=std::max(.8*t.grid.h,std::min(offset,(s.width-3.6*t.grid.h)*.5));
        result=std::min(result,local*(1-s.strength)+offset*s.strength);
    }
    return result;
}
inline void extend_gap_spheres(SkinTiles& t) {
    int blocks=int(t.coordinates.size()); tile_stage(t,4,blocks);
#pragma omp parallel for schedule(dynamic) num_threads(af_parallel_workers(blocks))
    for(int b=0;b<blocks;++b) {
        if(t.scene->cancelled)continue;
        for(int j=0;j<SKIN_CELLS;++j) { size_t i=size_t(b)*SKIN_CELLS+j; if((t.flags[i]&15)<2)continue;
            Vec p=tile_point(t,cell_coordinate(t,i)); double clearance=gap_clearance(t,p,t.offset);
            if(clearance>=t.offset)continue;
            double radius=std::max(0.,nearest(*t.scene,p,t.reach).distance-clearance);
            if(radius>0)t.values.set(i,std::min(t.values[i],-float(radius*radius))); }
        ++t.scene->done;
    }
    tile_cancelled(t);
}
inline void wrap_skin_tiles(SkinTiles& t) {
    extend_gap_spheres(t);
    for(size_t i=0;i<t.values.size();++i)if((t.flags[i]&15)<2)t.values.set(i,1.e20f);
    t.flags.clear(); t.flags.shrink_to_fit();
    // X/Y transforms are independent between Z slabs. Z runs after every slab is complete.
    for(int slab=0;slab<t.nz;++slab) {
        distance_skin_axis(t,0,slab); distance_skin_axis(t,1,slab); compact_skin_slab(t,slab);
    }
    distance_skin_axis(t,2); retain_skin_targets(t);
    finish_wrapped_skin(t); apply_gap_corridors(t); t.flags.resize(t.values.size());
}
}

#pragma once
namespace af_skin {
inline bool exterior_ray_clear(const SkinTiles& t,Vec center,Vec direction,double width) {
    double step=std::min(t.grid.transform[3]*.25,width*.1),distance=0;
    double limit=t.grid.h*norm({double(t.grid.nx),double(t.grid.ny),double(t.grid.nz)});
    if(step<=0)return false;
    while(distance<=limit && coarse_value(t.grid,add(center,mul(direction,distance)))>=0)distance+=step;
    if(distance>limit)return false; Hit hit; hit.distance=distance+1.e-9;
    ray_node(*t.scene->mesh,center,direction,0,-1,hit); return hit.face<0;
}
inline bool exterior_gap_cone(const SkinTiles& t,Vec p,Vec a,Vec b,double angle,double width) {
    for(int side=-1;side<=1;++side) {
        double theta=angle+side*3.141592653589793/6;
        Vec direction=add(mul(a,std::cos(theta)),mul(b,std::sin(theta)));
        if(!exterior_ray_clear(t,p,direction,width) || !exterior_ray_clear(t,p,mul(direction,-1),width))return false;
    }
    return true;
}
inline bool exterior_gap(const SkinTiles& t,const double* sample) {
    Vec p=load3(sample+6),axis=load3(sample+9),reference=std::abs(axis.x)<.8?Vec{1,0,0}:Vec{0,1,0};
    Vec a=unit(cross(axis,reference)),b=unit(cross(axis,a));
    for(int angle=0;angle<8;++angle)
        if(exterior_gap_cone(t,p,a,b,angle*3.141592653589793/8,sample[1]))return true;
    return false;
}
inline bool gap_already_open(const SkinTiles& t,Vec center) {
    Vec q=mul(sub(center,t.grid.origin),1/t.grid.h);
    int64_t i=tile_cell(t,int(std::floor(q.x)),int(std::floor(q.y)),int(std::floor(q.z)));
    if(i>=0 && t.flags[size_t(i)]<2)return false;
    for(int x=-1;x<=1;++x)for(int y=-1;y<=1;++y)for(int z=-1;z<=1;++z) {
        Vec direction=unit({double(x),double(y),double(z)});
        if(interpolate_skin(t,add(center,mul(direction,1.7*t.grid.h)))>=0)return false;
    }
    return true;
}
inline bool corridor_path(const SkinTiles& t,Vec center,Vec direction,std::vector<Vec>& path) {
    path.clear(); double step=t.grid.h*.5,required=t.grid.h*2.65;
    double reach=t.grid.h*norm({double(t.grid.nx),double(t.grid.ny),double(t.grid.nz)});
    for(double distance=0;distance<=reach;distance+=step) {
        tile_cancelled(t);
        Vec p=add(center,mul(direction,distance));
        if(nearest(*t.scene,p).distance<required)return false;
        path.push_back(p); if(coarse_value(t.grid,p)<0)return true;
    }
    return false;
}
inline bool find_gap_corridor(const SkinTiles& t,const Separator& s,std::vector<Vec>& path) {
    Vec reference=std::abs(s.normal.x)<.8?Vec{1,0,0}:Vec{0,1,0};
    Vec a=unit(cross(s.normal,reference)),b=unit(cross(s.normal,a));
    for(int angle=0;angle<16;++angle) {
        double theta=angle*3.141592653589793/8;
        Vec direction=add(mul(a,std::cos(theta)),mul(b,std::sin(theta)));
        if(corridor_path(t,s.center,direction,path))return true;
    }
    return false;
}
inline void carve_empty_sphere(SkinTiles& t,Vec center) {
    Vec q=mul(sub(center,t.grid.origin),1/t.grid.h); int base[3];
    for(int a=0;a<3;++a)base[a]=int(std::floor((&q.x)[a]));
    double radius=2.25*t.grid.h;
    for(int x=base[0]-4;x<=base[0]+4;++x)for(int y=base[1]-4;y<=base[1]+4;++y)for(int z=base[2]-4;z<=base[2]+4;++z) {
        int64_t cell=tile_cell(t,x,y,z); if(cell<0)continue;
        double value=norm(sub(t.grid.point(x,y,z),center))-radius;
        if(value>=skin_cell_value(t,size_t(cell)))continue;
        materialize_final_tile(t,size_t(cell)/SKIN_CELLS);
        t.values.set(size_t(cell),std::min(t.values[size_t(cell)],float(value)));
    }
}
inline std::string gap_route_error(const SkinTiles& t,const Separator& s) {
    return "Unresolved gap precision: no source-safe exterior route at ("+std::to_string(s.center.x)+", "+
        std::to_string(s.center.y)+", "+std::to_string(s.center.z)+"). Width "+std::to_string(s.width)+
        ", voxel "+std::to_string(t.grid.h)+", source clearance "+std::to_string(nearest(*t.scene,s.center).distance)+
        ", source triangles "+std::to_string(s.first)+" / "+std::to_string(s.second)+".";
}
inline void preserve_corridor(SkinTiles& t,const std::vector<Vec>& path) {
    uint64_t bytes=t.values.bytes()+tile_auxiliary_bytes(t)+(t.corridor_checks.size()+path.size())*sizeof(Vec)*2;
    bytes+=t.separators.items.size()*sizeof(Separator)*2;
    if(bytes>t.budget)throw std::runtime_error("Gap route validation exceeds the worker memory budget.");
    t.corridor_checks.insert(t.corridor_checks.end(),path.begin(),path.end());
    for(Vec p:path)carve_empty_sphere(t,p);
}
inline void apply_gap_corridors(SkinTiles& t) {
    classify_skin_void(t);
    tile_stage(t,4,int(t.separators.items.size())); std::vector<Vec> path;
    for(const auto& s:t.separators.items) {
        tile_cancelled(t); ++t.scene->done; if(s.strength>0 || gap_already_open(t,s.center))continue;
        if(!find_gap_corridor(t,s,path))
            throw std::runtime_error(gap_route_error(t,s));
        preserve_corridor(t,path);
    }
}
}

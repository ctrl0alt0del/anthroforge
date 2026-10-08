namespace af_tissue {
struct PointState {
    Points rest, points;
    std::vector<std::vector<int>> neighbors;
    std::unique_ptr<TriangleSnapshot> host;
    const double* matrix;
    const double* inverse;
    Vec control, gravity;
    double sag, limit, alpha;
};
inline Vec nearest_local(const TriangleSnapshot& host, Vec point) {
    Vec best{}; double distance=INFINITY; std::vector<int> queue{0};
    while(!queue.empty()) {
        int index=queue.back(); queue.pop_back(); const auto& node=host.nodes[index];
        if(af_bounds_distance(point,node.bounds)>=distance)continue;
        if(node.left>=0) { queue.push_back(node.left); queue.push_back(node.right); continue; }
        for(int i=node.begin;i<node.end;++i) {
            Vec face[3]; snapshot_face(host,host.faces[i].index,face); Vec closest=af_closest_triangle(point,face);
            double candidate=norm(sub(point,closest)); if(candidate<distance) { best=closest; distance=candidate; }
        }
    }
    return best;
}
inline double segment_triangle_parameter(Vec p,Vec direction,const Vec* face) {
    Vec ab=sub(face[1],face[0]), ac=sub(face[2],face[0]), h=cross(direction,ac);
    double det=dot(ab,h); if(std::abs(det)<=1.e-14)return INFINITY;
    Vec offset=sub(p,face[0]); double u=dot(offset,h)/det;
    if(u<0 || u>1)return INFINITY;
    Vec q=cross(offset,ab); double v=dot(direction,q)/det;
    if(v<0 || u+v>1)return INFINITY;
    double t=dot(ac,q)/det; return t>=0 && t<1 ? t : INFINITY;
}
inline Vec clamp_segment(const PointState& s,Vec point) {
    Vec p=af_transform(s.inverse,point), q=af_transform(s.inverse,s.control), direction=sub(q,p);
    if(norm(direction)<=1.e-10)return point;
    double best=INFINITY; std::vector<int> queue{0};
    while(!queue.empty()) {
        int index=queue.back(); queue.pop_back(); const auto& node=s.host->nodes[index];
        if(!ray_hits_bounds(p,direction,node.bounds))continue;
        if(node.left>=0) { queue.push_back(node.left); queue.push_back(node.right); continue; }
        for(int i=node.begin;i<node.end;++i) {
            Vec face[3]; snapshot_face(*s.host,s.host->faces[i].index,face);
            best=std::min(best,segment_triangle_parameter(p,direction,face));
        }
    }
    return std::isfinite(best) ? af_transform(s.matrix,add(p,mul(direction,best))) : point;
}
inline void point_gravity(PointState& s) {
    for(auto& point:s.points) {
        Vec local=af_transform(s.inverse,point), closest=nearest_local(*s.host,local);
        double distance=norm(sub(point,af_transform(s.matrix,closest)));
        double step=.002*s.sag+.02*s.sag*distance;
        if(s.limit>0)step=std::min(step,s.limit*.25);
        point=add(point,mul(s.gravity,step));
    }
}
inline void viscosity(PointState& s) {
    Points next=s.points;
    for(size_t i=0;i<s.points.size();++i) {
        const auto& neighbors=s.neighbors[i]; if(neighbors.empty())continue;
        Vec sum{}; for(int j:neighbors)sum=add(sum,s.points[j]);
        next[i]=add(mul(s.points[i],1.-s.alpha),mul(sum,s.alpha/neighbors.size()));
    }
    s.points=std::move(next);
}
inline void point_projection(PointState& s) {
    for(size_t i=0;i<s.points.size();++i) {
        s.points[i]=clamp_segment(s,s.points[i]);
        double drop=dot(sub(s.points[i],s.rest[i]),s.gravity);
        if(s.limit>0 && drop>s.limit)s.points[i]=sub(s.points[i],mul(s.gravity,drop-s.limit));
    }
}
inline PointState point_state(const double* p,int n,const int* edges,int ne,const double* host,const int64_t* triangles,int nt,const double* cfg) {
    PointState s;
    for(int i=0;i<n;++i)s.rest.push_back(load3(p+3*i));
    s.points=s.rest; s.neighbors.resize(n); s.host.reset(create_snapshot(host,triangles,nt));
    for(int i=0;i<ne;++i) { int a=edges[2*i],b=edges[2*i+1]; s.neighbors[a].push_back(b); s.neighbors[b].push_back(a); }
    s.matrix=cfg+10; s.inverse=cfg+26; s.control=load3(cfg+7); s.gravity=unit(load3(cfg+4));
    if(norm(s.gravity)<=1.e-10)s.gravity={0,0,-1};
    s.sag=std::max(0.,cfg[1]); s.limit=std::max(0.,cfg[2]); s.alpha=(1.-std::clamp(cfg[3],0.,1.))*.18;
    return s;
}
inline int point_iterations(PointState& s,int iterations,double& last) {
    for(int i=0;i<iterations;++i) {
        Points previous=s.points;
        point_gravity(s); viscosity(s); point_projection(s); last=change(s.points,previous);
        if(last<1.e-6)return i+1;
    }
    return iterations;
}
inline void point_output(const PointState& s,int iterations,double last,double* out,double* report) {
    report[0]=last<1.e-6 ? 1 : 2; report[1]=iterations; report[2]=last; report[3]=change(s.points,s.rest);
    for(size_t i=0;i<s.points.size();++i) {
        out[3*i]=s.points[i].x; out[3*i+1]=s.points[i].y; out[3*i+2]=s.points[i].z;
    }
}
} // namespace af_tissue
AF_EXPORT int af_soft_tissue_point(const double* p,int n,const int* edges,int ne,const double* host,
    const int64_t* triangles,int nt,const double* cfg,double* out,double* report) {
    auto start=std::chrono::steady_clock::now();
    try {
        if(n<1 || nt<1 || ne<0 || cfg[0]<1)return 3;
        auto s=af_tissue::point_state(p,n,edges,ne,host,triangles,nt,cfg); double last=0;
        int iterations=af_tissue::point_iterations(s,int(cfg[0]),last);
        af_tissue::point_output(s,iterations,last,out,report);
        report[6]=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        return 0;
    } catch(...) { return 4; }
}

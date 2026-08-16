#pragma once

struct AfBatchResult { int candidates, tested, rejected, contained; double minimum; };
struct AfSearchResult {
    int path_count, status, searches, expansions, validated, rejected, candidates, tested;
    double search_ms, collision_ms;
};
struct AfInstance {
    TriangleSnapshot* mesh; int owner, collider, closed; double matrix[16], inverse[16]; Bounds bounds;
};
struct AfWorld { std::vector<AfInstance> items; std::vector<Bounds> order; std::vector<BvhNode> nodes; };

static Vec af_transform(const double* m, Vec p) {
    return {m[0]*p.x+m[1]*p.y+m[2]*p.z+m[3],
            m[4]*p.x+m[5]*p.y+m[6]*p.z+m[7],
            m[8]*p.x+m[9]*p.y+m[10]*p.z+m[11]};
}

static Bounds af_transform_bounds(const double* m, const Bounds& source, int index) {
    Bounds out=empty_bounds(); out.index=index;
    for (int bits=0; bits<8; ++bits) {
        Vec p{source.lo[0],source.lo[1],source.lo[2]}; double* v=&p.x;
        for (int a=0; a<3; ++a) if (bits&(1<<a)) v[a]=source.hi[a];
        Vec q=af_transform(m,p); for (int a=0; a<3; ++a) out.lo[a]=std::min(out.lo[a],(&q.x)[a]),out.hi[a]=std::max(out.hi[a],(&q.x)[a]);
    }
    return out;
}

static Bounds af_segment_bounds(Vec a, Vec b, double pad) {
    Bounds out{}; const double* x=&a.x; const double* y=&b.x;
    for (int axis=0; axis<3; ++axis) out.lo[axis]=std::min(x[axis],y[axis])-pad,out.hi[axis]=std::max(x[axis],y[axis])+pad;
    return out;
}

static int af_build_world_bvh(AfWorld& world, int begin, int end) {
    Bounds bounds=empty_bounds(); for (int i=begin; i<end; ++i) bounds=merge_bounds(bounds,world.order[i]);
    int node=int(world.nodes.size()); world.nodes.push_back({bounds,-1,-1,begin,end});
    if (end-begin<=4) return node; int axis=longest_axis(bounds),middle=(begin+end)/2;
    std::stable_sort(world.order.begin()+begin,world.order.begin()+end,[axis](const Bounds& a,const Bounds& b){
        double ca=a.lo[axis]+a.hi[axis],cb=b.lo[axis]+b.hi[axis]; return ca==cb ? a.index<b.index : ca<cb; });
    world.nodes[node].left=af_build_world_bvh(world,begin,middle); world.nodes[node].right=af_build_world_bvh(world,middle,end);
    return node;
}

static Bounds af_refit_world(AfWorld& world, int node) {
    auto& value=world.nodes[node]; Bounds result=empty_bounds();
    if (value.left>=0) result=merge_bounds(af_refit_world(world,value.left),af_refit_world(world,value.right));
    else for (int i=value.begin; i<value.end; ++i) result=merge_bounds(result,world.items[world.order[i].index].bounds);
    value.bounds=result; return result;
}

static void af_collect_world(const AfWorld& world, int node, const Bounds& query, std::vector<int>& hits) {
    const auto& value=world.nodes[node]; if (!bounds_overlap(query,value.bounds)) return;
    if (value.left>=0) { af_collect_world(world,value.left,query,hits); af_collect_world(world,value.right,query,hits); return; }
    for (int i=value.begin; i<value.end; ++i) { int index=world.order[i].index; if (bounds_overlap(query,world.items[index].bounds)) hits.push_back(index); }
}

static double af_inverse_padding(const AfInstance& item, double threshold) {
    double maximum=0.0;
    for (int row=0; row<3; ++row) maximum=std::max(maximum,std::sqrt(item.inverse[4*row]*item.inverse[4*row]+item.inverse[4*row+1]*item.inverse[4*row+1]+item.inverse[4*row+2]*item.inverse[4*row+2]));
    return threshold*maximum;
}

static std::pair<double,double> af_test_range(Vec a, Vec b, const AfInstance& item, int first, int second, double span) {
    double fraction=std::min(1.0,span/std::max(norm(sub(b,a)),1.0e-12)),low=0.0,high=1.0;
    if (first==item.owner) low=fraction; if (second==item.owner) high=1.0-fraction;
    return {low,high};
}

static void af_world_face(const AfInstance& item, int index, Vec* face) {
    snapshot_face(*item.mesh,index,face);
    for (int i=0; i<3; ++i) face[i]=af_transform(item.matrix,face[i]);
}

static bool af_bounds_contains(const Bounds& bounds, Vec point) {
    const double* p=&point.x;
    for (int axis=0; axis<3; ++axis) if (p[axis]<bounds.lo[axis] || p[axis]>bounds.hi[axis]) return false;
    return true;
}

static bool af_inside_instance(const AfInstance& item, Vec point) {
    if (!item.closed || !af_bounds_contains(item.bounds,point)) return false;
    Vec local=af_transform(item.inverse,point);
    return snapshot_inside(*item.mesh,local,0,int(item.mesh->triangles.size()/3));
}

static bool af_instance_clear(const AfInstance& item, Vec a, Vec b, int first, int second,
                              double span, double threshold, AfBatchResult& result) {
    auto range=af_test_range(a,b,item,first,second,span); if (range.first>=range.second) return true;
    Vec la=af_transform(item.inverse,a),lb=af_transform(item.inverse,b); std::vector<int> faces;
    Bounds query=af_segment_bounds(la,lb,af_inverse_padding(item,threshold));
    if (!item.mesh->nodes.empty()) collect_candidates(*item.mesh,0,query,faces); result.candidates+=int(faces.size());
    Vec ta=add(a,mul(sub(b,a),range.first)),tb=add(a,mul(sub(b,a),range.second)); bool clear=true;
    for (int index: faces) { Vec face[3]; af_world_face(item,index,face); double d=segment_triangle(ta,tb,face); ++result.tested; result.minimum=std::min(result.minimum,d); clear=clear && d>=threshold; }
    return clear;
}

static bool af_edge_contained(const AfWorld& world, Vec a, Vec b, int first, int second,
                              int& blocker, AfBatchResult& result) {
    for (const auto& item: world.items) for (int endpoint=0; endpoint<2; ++endpoint) {
        int owner=endpoint ? second:first; if (owner==item.owner) continue; Vec point=endpoint ? b:a;
        if (af_inside_instance(item,point)) { blocker=item.collider; ++result.contained; return true; }
    }
    return false;
}

static bool af_validate_edge(const AfWorld& world, Vec a, Vec b, int first, int second,
                             double span, double threshold, int& blocker, AfBatchResult& result) {
    std::vector<int> hits; if (!world.nodes.empty()) af_collect_world(world,0,af_segment_bounds(a,b,threshold),hits);
    for (int index: hits) if (!af_instance_clear(world.items[index],a,b,first,second,span,threshold,result)) {
        blocker=world.items[index].collider; return false;
    }
    return !af_edge_contained(world,a,b,first,second,blocker,result);
}

static int af_validate_world(const AfWorld& world, const double* points, const int64_t* edges,
                             const int* first, const int* second, int count, double span,
                             double threshold, int* clear, int* blockers, double* minima, AfBatchResult& result) {
    result={0,0,0,0,INFINITY};
    for (int i=0; i<count; ++i) { Vec a=load3(points+3*edges[2*i]),b=load3(points+3*edges[2*i+1]); int blocker=-1;
        int tested=result.tested; bool valid=af_validate_edge(world,a,b,first[i],second[i],span,threshold,blocker,result);
        clear[i]=valid; blockers[i]=blocker; minima[i]=result.tested==tested ? INFINITY:result.minimum; result.rejected+=!valid; }
    return 0;
}

static bool af_validate_one(const AfInstance& item, Vec a, Vec b, int first, int second,
                            double span, double threshold, int& blocker, AfBatchResult& result) {
    bool clear=af_instance_clear(item,a,b,first,second,span,threshold,result);
    if (clear && first!=item.owner && af_inside_instance(item,a)) clear=false,++result.contained;
    if (clear && second!=item.owner && af_inside_instance(item,b)) clear=false,++result.contained;
    if (!clear) blocker=item.collider; return clear;
}

static int af_validate_instance(const AfInstance& item, const double* points, const int64_t* edges,
                                const int* first, const int* second, int count, double span,
                                double threshold, int* clear, int* blockers, double* minima, AfBatchResult& result) {
    result={0,0,0,0,INFINITY};
    for (int i=0; i<count; ++i) { Vec a=load3(points+3*edges[2*i]),b=load3(points+3*edges[2*i+1]); int blocker=-1;
        int tested=result.tested; bool valid=af_validate_one(item,a,b,first[i],second[i],span,threshold,blocker,result);
        clear[i]=valid; blockers[i]=blocker; minima[i]=result.tested==tested ? INFINITY:result.minimum; result.rejected+=!valid; }
    return 0;
}

AF_EXPORT void* af_world_create() { return new AfWorld(); }

AF_EXPORT void af_world_destroy(void* handle) {
    auto* world=static_cast<AfWorld*>(handle); if (!world) return;
    for (auto& item: world->items) delete item.mesh; delete world;
}

AF_EXPORT int af_world_add_collider(void* handle, const double* vertices, const int64_t* triangles,
                                    int count, int owner, int collider, int closed,
                                    const double* matrix, const double* inverse) {
    if (!handle || !vertices || !triangles || !matrix || !inverse || count<0) return -1;
    auto* world=static_cast<AfWorld*>(handle); AfInstance item{create_snapshot(vertices,triangles,count),owner,collider,closed,{},{},{}};
    std::copy(matrix,matrix+16,item.matrix); std::copy(inverse,inverse+16,item.inverse);
    item.bounds=af_transform_bounds(item.matrix,item.mesh->nodes[0].bounds,int(world->items.size()));
    world->items.push_back(item); return int(world->items.size()-1);
}

AF_EXPORT int af_world_commit(void* handle) {
    if (!handle) return 1; auto& world=*static_cast<AfWorld*>(handle); world.order.clear(); world.nodes.clear();
    for (int i=0; i<int(world.items.size()); ++i) { world.items[i].bounds.index=i; world.order.push_back(world.items[i].bounds); }
    if (!world.order.empty()) af_build_world_bvh(world,0,int(world.order.size())); return 0;
}

AF_EXPORT int af_world_update_transform(void* handle, int index, const double* matrix, const double* inverse) {
    if (!handle || !matrix || !inverse) return 1; auto& world=*static_cast<AfWorld*>(handle);
    if (index<0 || index>=int(world.items.size())) return 1; auto& item=world.items[index];
    std::copy(matrix,matrix+16,item.matrix); std::copy(inverse,inverse+16,item.inverse);
    item.bounds=af_transform_bounds(item.matrix,item.mesh->nodes[0].bounds,index); if (!world.nodes.empty()) af_refit_world(world,0); return 0;
}

AF_EXPORT int af_world_validate_edges(void* handle, const double* points, const int64_t* edges,
                                      const int* first, const int* second, int count, double span,
                                      double threshold, int* clear, int* blockers, double* minima,
                                      AfBatchResult* output) {
    if (!handle || !points || !edges || !first || !second || !clear || !blockers || !minima || !output || count<0) return 1;
    return af_validate_world(*static_cast<AfWorld*>(handle),points,edges,first,second,count,span,threshold,clear,blockers,minima,*output);
}

AF_EXPORT int af_world_validate_instance(void* handle, int instance, const double* points,
                                         const int64_t* edges, const int* first, const int* second,
                                         int count, double span, double threshold, int* clear,
                                         int* blockers, double* minima, AfBatchResult* output) {
    if (!handle || !points || !edges || !first || !second || !clear || !blockers || !minima || !output || count<0) return 1;
    const auto& world=*static_cast<AfWorld*>(handle); if (instance<0 || instance>=int(world.items.size())) return 1;
    return af_validate_instance(world.items[instance],points,edges,first,second,count,span,threshold,clear,blockers,minima,*output);
}

static Vec af_closest_triangle(Vec p, const Vec* t) {
    Vec ab=sub(t[1],t[0]),ac=sub(t[2],t[0]),ap=sub(p,t[0]); double d1=dot(ab,ap),d2=dot(ac,ap); if(d1<=0&&d2<=0)return t[0];
    Vec bp=sub(p,t[1]); double d3=dot(ab,bp),d4=dot(ac,bp); if(d3>=0&&d4<=d3)return t[1]; double vc=d1*d4-d3*d2;
    if(vc<=0&&d1>=0&&d3<=0)return add(t[0],mul(ab,d1/(d1-d3))); Vec cp=sub(p,t[2]); double d5=dot(ab,cp),d6=dot(ac,cp);
    if(d6>=0&&d5<=d6)return t[2]; double vb=d5*d2-d1*d6; if(vb<=0&&d2>=0&&d6<=0)return add(t[0],mul(ac,d2/(d2-d6)));
    double va=d3*d6-d5*d4; if(va<=0&&(d4-d3)>=0&&(d5-d6)>=0)return add(t[1],mul(sub(t[2],t[1]),(d4-d3)/((d4-d3)+(d5-d6))));
    double inverse=1.0/(va+vb+vc); return add(t[0],add(mul(ab,vb*inverse),mul(ac,vc*inverse)));
}

struct AfNearest { Vec point, face_normal; double distance; int instance; };

static void af_nearest_item(const AfInstance& item, int instance, Vec point, AfNearest& best) {
    int count=int(item.mesh->triangles.size()/3);
    for(int face_index=0;face_index<count;++face_index){Vec face[3];af_world_face(item,face_index,face);Vec closest=af_closest_triangle(point,face);
        double distance=norm(sub(point,closest));if(distance<best.distance)best={closest,cross(sub(face[1],face[0]),sub(face[2],face[0])),distance,instance};}
}

static Vec af_unit(Vec value) {
    double length=norm(value); return length>eps()?mul(value,1.0/length):Vec{0.0,0.0,0.0};
}

static double af_bounds_distance(Vec point,const Bounds& bounds){
    double squared=0.0;const double* p=&point.x;
    for(int axis=0;axis<3;++axis){double delta=p[axis]<bounds.lo[axis]?bounds.lo[axis]-p[axis]:p[axis]>bounds.hi[axis]?p[axis]-bounds.hi[axis]:0.0;squared+=delta*delta;}
    return std::sqrt(squared);
}

static AfNearest af_nearest_world(const AfWorld& world, Vec point) {
    AfNearest best{{0,0,0},{0,0,0},INFINITY,-1};std::vector<std::pair<double,int>> order;
    for(int index=0;index<int(world.items.size());++index)order.push_back({af_bounds_distance(point,world.items[index].bounds),index});
    std::stable_sort(order.begin(),order.end());
    for(auto [lower,index]:order){if(lower>=best.distance)break;af_nearest_item(world.items[index],index,point,best);}
    return best;
}

AF_EXPORT int af_world_nearest_points(void* handle,const double* points,int count,double* closest,
                                      double* normals,double* distances,int* blockers,int* contained){
    if(!handle||!points||!closest||!normals||!distances||!blockers||!contained||count<0)return 1;const auto& world=*static_cast<AfWorld*>(handle);
    for(int i=0;i<count;++i){Vec point=load3(points+3*i);AfNearest best=af_nearest_world(world,point);bool inside=best.instance>=0&&af_inside_instance(world.items[best.instance],point);
        Vec direction=inside?sub(best.point,point):sub(point,best.point);Vec normal=af_unit(direction);if(norm(normal)<=eps())normal=af_unit(best.face_normal);
        double* q=closest+3*i;double* n=normals+3*i;q[0]=best.point.x;q[1]=best.point.y;q[2]=best.point.z;n[0]=normal.x;n[1]=normal.y;n[2]=normal.z;
        distances[i]=best.distance;blockers[i]=best.instance<0?-1:world.items[best.instance].collider;contained[i]=inside;}
    return 0;
}

struct AfGraph { int count, goal; const double* points; const int64_t* offsets; const int64_t* neighbors; std::vector<double> metric; std::vector<int8_t> state; };

static size_t af_edge_slot(const AfGraph& graph, int a, int b) { return size_t(a)*graph.count+b; }

static void af_build_metric(AfGraph& graph) {
    graph.metric.resize(size_t(graph.count)*graph.count); graph.state.assign(graph.metric.size(),0);
    for (int a=0; a<graph.count; ++a) for (int b=0; b<graph.count; ++b)
        graph.metric[af_edge_slot(graph,a,b)]=norm(sub(load3(graph.points+3*a),load3(graph.points+3*b)));
}

static void af_expand_graph(const AfGraph& graph, int node, std::vector<double>& distance,
                            std::vector<int>& came, std::priority_queue<std::pair<double,int>,
                            std::vector<std::pair<double,int>>,std::greater<std::pair<double,int>>>& heap) {
    for (int64_t i=graph.offsets[node]; i<graph.offsets[node+1]; ++i) { int next=int(graph.neighbors[i]);
        if (graph.state[af_edge_slot(graph,node,next)]<0) continue; double cost=distance[node]+graph.metric[af_edge_slot(graph,node,next)];
        if (cost<distance[next]) { distance[next]=cost; came[next]=node; heap.push({cost+graph.metric[af_edge_slot(graph,next,graph.goal)],next}); } }
}

static std::vector<int> af_astar(const AfGraph& graph, int start, int& expansions) {
    using Pair=std::pair<double,int>; std::priority_queue<Pair,std::vector<Pair>,std::greater<Pair>> heap; heap.push({0.0,start});
    std::vector<double> distance(graph.count,INFINITY); std::vector<int> came(graph.count,-1),seen(graph.count,0); distance[start]=0.0;
    while (!heap.empty()) { int node=heap.top().second; heap.pop(); if (node==graph.goal) { std::vector<int> path{graph.goal};
            while (came[path.back()]>=0) path.push_back(came[path.back()]); std::reverse(path.begin(),path.end()); return path; }
        if (seen[node]) continue; seen[node]=1; ++expansions; af_expand_graph(graph,node,distance,came,heap); }
    return {};
}

static bool af_path_known(const AfGraph& graph, const std::vector<int>& path) {
    for (size_t i=1; i<path.size(); ++i) if (graph.state[af_edge_slot(graph,path[i-1],path[i])]<=0) return false;
    return true;
}

static void af_mark_edges(AfGraph& graph, const std::vector<std::array<int,2>>& edges,
                          const std::vector<int>& clear, AfSearchResult& output) {
    for (size_t i=0; i<edges.size(); ++i) { int a=edges[i][0],b=edges[i][1],value=clear[i] ? 1:-1;
        graph.state[af_edge_slot(graph,a,b)]=value; graph.state[af_edge_slot(graph,b,a)]=value;
        output.validated+=clear[i]; output.rejected+=!clear[i]; }
}

static void af_validate_path(AfWorld& world, AfGraph& graph, const std::vector<int>& path,
                             int start_owner, int end_owner, double span, double threshold,
                             AfSearchResult& output) {
    std::vector<std::array<int,2>> rows; for (size_t i=1; i<path.size(); ++i) {
        int a=path[i-1],b=path[i]; if (!graph.state[af_edge_slot(graph,a,b)]) rows.push_back({a,b}); }
    if (rows.empty()) return; std::vector<int64_t> edges; std::vector<int> first,second,clear(rows.size()),block(rows.size()); std::vector<double> minimum(rows.size());
    for (auto row: rows) { edges.insert(edges.end(),{row[0],row[1]}); first.push_back(row[0]==0?start_owner:row[0]==1?end_owner:0); second.push_back(row[1]==0?start_owner:row[1]==1?end_owner:0); }
    AfBatchResult batch{}; af_validate_world(world,graph.points,edges.data(),first.data(),second.data(),int(rows.size()),span,threshold,clear.data(),block.data(),minimum.data(),batch);
    output.candidates+=batch.candidates; output.tested+=batch.tested; af_mark_edges(graph,rows,clear,output);
}

AF_EXPORT int af_world_lazy_path(void* handle, const double* points, int count,
                                 const int64_t* offsets, const int64_t* neighbors,
                                 int start_owner, int end_owner, double span, double threshold,
                                 int attempts, int64_t* path, int capacity, AfSearchResult* output) {
    if (!handle || !points || !offsets || !neighbors || !path || !output || count<2 || capacity<count) return 1;
    auto& world=*static_cast<AfWorld*>(handle); AfGraph graph{count,1,points,offsets,neighbors,{},{}}; af_build_metric(graph);
    AfSearchResult result{}; auto start=std::chrono::steady_clock::now(); std::vector<int> route;
    for (int attempt=0; attempt<attempts; ++attempt) { ++result.searches; route=af_astar(graph,0,result.expansions); if (route.empty()) { result.status=1; break; }
        if (af_path_known(graph,route)) break; auto collision=std::chrono::steady_clock::now(); af_validate_path(world,graph,route,start_owner,end_owner,span,threshold,result);
        result.collision_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-collision).count(); if (af_path_known(graph,route)) break; }
    result.path_count=int(route.size()); if (result.searches>=attempts && !af_path_known(graph,route)) result.status=2;
    for (int i=0; i<result.path_count; ++i) path[i]=route[i]; result.search_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()-result.collision_ms; *output=result; return 0;
}

struct AfSparseGraph { int count, goal; const double* points; const int64_t* offsets; const int64_t* neighbors; };

static void af_expand_sparse(const AfSparseGraph& graph, int node, std::vector<double>& distance,
                             std::vector<int>& came, std::priority_queue<std::pair<double,int>,
                             std::vector<std::pair<double,int>>,std::greater<std::pair<double,int>>>& heap) {
    Vec point=load3(graph.points+3*node),goal=load3(graph.points+3*graph.goal);
    for (int64_t i=graph.offsets[node]; i<graph.offsets[node+1]; ++i) { int next=int(graph.neighbors[i]); Vec target=load3(graph.points+3*next);
        double cost=distance[node]+norm(sub(target,point)); if (cost<distance[next]) { distance[next]=cost; came[next]=node; heap.push({cost+norm(sub(target,goal)),next}); } }
}

static std::vector<int> af_sparse_astar(const AfSparseGraph& graph, int start, int& expansions) {
    using Pair=std::pair<double,int>; std::priority_queue<Pair,std::vector<Pair>,std::greater<Pair>> heap; heap.push({0.0,start});
    std::vector<double> distance(graph.count,INFINITY); std::vector<int> came(graph.count,-1),seen(graph.count,0); distance[start]=0.0;
    while (!heap.empty()) { int node=heap.top().second; heap.pop(); if (node==graph.goal) { std::vector<int> path{graph.goal};
            while (came[path.back()]>=0) path.push_back(came[path.back()]); std::reverse(path.begin(),path.end()); return path; }
        if (seen[node]) continue; seen[node]=1; ++expansions; af_expand_sparse(graph,node,distance,came,heap); }
    return {};
}

AF_EXPORT int af_graph_shortest_path(const double* points, int count, const int64_t* offsets,
                                     const int64_t* neighbors, int start, int goal,
                                     int64_t* path, int capacity, AfSearchResult* output) {
    if (!points || !offsets || !neighbors || !path || !output || count<1 || start<0 || goal<0 || start>=count || goal>=count || capacity<count) return 1;
    AfSparseGraph graph{count,goal,points,offsets,neighbors}; AfSearchResult result{};
    auto before=std::chrono::steady_clock::now(); std::vector<int> route=af_sparse_astar(graph,start,result.expansions);
    result.status=route.empty(); result.path_count=int(route.size());
    for (int i=0; i<result.path_count; ++i) path[i]=route[i]; result.searches=1; result.search_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-before).count(); *output=result; return 0;
}

static void af_add_mesh_face(std::vector<std::vector<int>>& rows, const int64_t* face) {
    for (int i=0; i<3; ++i) { int a=int(face[i]),b=int(face[(i+1)%3]); rows[a].push_back(b); rows[b].push_back(a); }
}

static void af_flatten_mesh_graph(std::vector<std::vector<int>>& rows, std::vector<int64_t>& offsets,
                                  std::vector<int64_t>& neighbors) {
    offsets.push_back(0);
    for (auto& row: rows) { std::sort(row.begin(),row.end()); row.erase(std::unique(row.begin(),row.end()),row.end());
        neighbors.insert(neighbors.end(),row.begin(),row.end()); offsets.push_back(int64_t(neighbors.size())); }
}

AF_EXPORT int af_mesh_shortest_path(const double* points, int count, const int64_t* triangles,
                                    int face_count, int start, int goal, int64_t* path,
                                    int capacity, AfSearchResult* output) {
    if (!points || !triangles || !path || !output || count<1 || face_count<0 || start<0 || goal<0 || start>=count || goal>=count || capacity<count) return 1;
    std::vector<std::vector<int>> rows(count); for (int i=0; i<face_count; ++i) af_add_mesh_face(rows,triangles+3*i);
    std::vector<int64_t> offsets,neighbors; af_flatten_mesh_graph(rows,offsets,neighbors);
    AfSparseGraph graph{count,goal,points,offsets.data(),neighbors.data()}; AfSearchResult result{}; auto before=std::chrono::steady_clock::now();
    std::vector<int> route=af_sparse_astar(graph,start,result.expansions); result.status=route.empty(); result.path_count=int(route.size());
    for (int i=0; i<result.path_count; ++i) path[i]=route[i]; result.searches=1; result.search_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-before).count(); *output=result; return 0;
}

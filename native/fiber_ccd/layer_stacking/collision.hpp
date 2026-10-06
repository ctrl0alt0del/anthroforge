#pragma once
namespace af_layer {
static double box_distance(Vec p,const Bounds& box) {
    double result=0;for(int j=0;j<3;++j){double d=std::max({box.lo[j]-(&p.x)[j],0.,(&p.x)[j]-box.hi[j]});result+=d*d;}return result;
}
static double nearest_distance(const TriangleSnapshot& mesh,Vec point) {
    double best=INFINITY;std::vector<int> stack{0};
    while(!stack.empty()){int index=stack.back();stack.pop_back();const auto& node=mesh.nodes[index];
        if(box_distance(point,node.bounds)>best*best)continue;
        if(node.left>=0){stack.push_back(node.left);stack.push_back(node.right);continue;}
        for(int j=node.begin;j<node.end;++j){Vec f[3];snapshot_face(mesh,mesh.faces[j].index,f);best=std::min(best,point_triangle(point,f));}}
    return best;
}
static double penetration(const Side& bone,Vec point) {
    if(!bone.enabled||box_distance(point,bone.snapshot->nodes[0].bounds)>0)return 0;
    return snapshot_inside(*bone.snapshot,point,0,int(bone.faces.size()/3))?nearest_distance(*bone.snapshot,point):0;
}
static void bone_samples(const Side& own,const std::vector<Vec>& final,const Side& bone,std::atomic<bool>& cancel) {
    for(size_t i=0;i<final.size();++i){require(!cancel,"PAIR_CANCELLED");if(norm(sub(final[i],own.own[i]))<1e-12)continue;
        require(penetration(bone,final[i])<=penetration(bone,own.own[i])+2e-7,"STACK_WORSENED_BONE_PENETRATION");}
    for(size_t f=0;f<own.faces.size();f+=3){Vec a{},b{};for(int j=0;j<3;++j){auto id=own.faces[f+j];a=add(a,own.own[id]);b=add(b,final[id]);}
        require(penetration(bone,mul(b,1./3))<=penetration(bone,mul(a,1./3))+2e-7,"STACK_WORSENED_BONE_PENETRATION");}
}
static Side surface_copy(const Side& side,const std::vector<Vec>& points) {
    auto value=base_copy(side);value.base=points;value.own=points;prepare_snapshot(value,nullptr);return value;
}
static bool shared_vertex(const Side& a,int first,int second) {
    for(int i=0;i<3;++i)for(int j=0;j<3;++j)if(a.faces[3*first+i]==a.faces[3*second+j])return true;return false;
}
static std::set<std::pair<int,int>> intersections(const Side& a,const Side& b,bool self,std::atomic<bool>& cancel) {
    std::set<std::pair<int,int>> out;auto ea=edge_counts(a),eb=edge_counts(b);std::vector<int> stack;
    for(int f=0;f<int(a.faces.size()/3);++f){require(!cancel,"PAIR_CANCELLED");Vec p[3];face(a,f,p);auto bounds=triangle_box(p);stack={0};
        while(!stack.empty()){int index=stack.back();stack.pop_back();const auto& node=b.snapshot->nodes[index];if(!bounds_overlap(bounds,node.bounds))continue;
            if(node.left>=0){stack.push_back(node.left);stack.push_back(node.right);continue;}
            for(int j=node.begin;j<node.end;++j){int other=b.snapshot->faces[j].index;if(self&&(other<=f||shared_vertex(a,f,other)))continue;
                if(bounds_overlap(bounds,b.snapshot->faces[j])&&transverse(a,f,b,other,ea,eb))out.emplace(f,other);}}}
    return out;
}
static void no_new_crossings(const Side& own,const Side& final,const Side& provider_own,const Side& provider_final,bool self,std::atomic<bool>& cancel) {
    auto after=intersections(final,provider_final,self,cancel);if(after.empty())return;
    auto before=intersections(own,provider_own,self,cancel);
    for(auto hit:after)require(before.count(hit)!=0,self?"STACK_NEW_SELF_INTERSECTION":"STACK_NEW_SURFACE_INTERSECTION");
}
static void baseline_diagnostics(const Side& side,const State& state,Output& output,std::atomic<bool>& cancel) {
    auto own=surface_copy(side,side.own);output.baseline_self=intersections(own,own,true,cancel).size();
    for(const auto& bone:state.obstacles){output.baseline_bone_crossings+=intersections(own,bone,false,cancel).size();
        output.open_obstacles+=!bone.enabled;
        for(Vec point:side.own)output.baseline_penetration=std::max(output.baseline_penetration,penetration(bone,point));}
}
static void validate_collisions(const Side& side,const std::vector<Vec>& points,const State& state,std::atomic<bool>& cancel) {
    auto own=surface_copy(side,side.own),final=surface_copy(side,points);
    no_new_crossings(own,final,own,final,true,cancel);
    for(const auto& bone:state.obstacles){bone_samples(side,points,bone,cancel);no_new_crossings(own,final,bone,bone,false,cancel);}
}
}

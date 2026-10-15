#pragma once
namespace af_skin {
struct Separator { Vec center,normal; double half,radius,strength,width=0,limit=0; int first=-1,second=-1; };
struct SeparatorNode { int item,left=-1,right=-1,axis; Bounds bounds; };
struct Separators { std::vector<Separator> items; std::vector<SeparatorNode> nodes; };
struct CloseSeparators {
    std::array<double,16> distances; std::array<int,16> ids; int count=0,worst=0;
    double limit() const { return count<16?INFINITY:distances[worst]; }
};
inline void add_close_separator(CloseSeparators& close,int item,double distance) {
    if(distance>=close.limit())return;
    int index=close.count<16?close.count++:close.worst; close.ids[index]=item; close.distances[index]=distance;
    close.worst=0; for(int i=1;i<close.count;++i)if(close.distances[i]>close.distances[close.worst])close.worst=i;
}
inline void nearby_separators(const Separators& tree,Vec p,int index,CloseSeparators& close) {
    if(index<0)return; const auto& node=tree.nodes[index];
    double bound=af_bounds_distance(p,node.bounds); if(bound*bound>close.limit())return;
    Vec delta=sub(p,tree.items[node.item].center); add_close_separator(close,node.item,dot(delta,delta));
    double side=(&delta.x)[node.axis];
    nearby_separators(tree,p,side<0?node.left:node.right,close);
    nearby_separators(tree,p,side<0?node.right:node.left,close);
}
inline Bounds separator_bounds(const Separators& tree,const std::vector<int>& order,int first,int last) {
    Bounds box{{INFINITY,INFINITY,INFINITY},{-INFINITY,-INFINITY,-INFINITY},-1};
    for(int i=first;i<last;++i)for(int a=0;a<3;++a) {
        double p=(&tree.items[order[i]].center.x)[a]; box.lo[a]=std::min(box.lo[a],p); box.hi[a]=std::max(box.hi[a],p); }
    return box;
}
inline int build_separators(Separators& tree,std::vector<int>& order,int first,int last,int axis) {
    if(first==last)return -1; int middle=(first+last)/2;
    std::nth_element(order.begin()+first,order.begin()+middle,order.begin()+last,[&](int a,int b) {
        return (&tree.items[a].center.x)[axis]<(&tree.items[b].center.x)[axis]; });
    int node=int(tree.nodes.size()); tree.nodes.push_back({order[middle],-1,-1,axis,separator_bounds(tree,order,first,last)});
    int left=build_separators(tree,order,first,middle,(axis+1)%3);
    int right=build_separators(tree,order,middle+1,last,(axis+1)%3);
    tree.nodes[node].left=left; tree.nodes[node].right=right; return node;
}
}

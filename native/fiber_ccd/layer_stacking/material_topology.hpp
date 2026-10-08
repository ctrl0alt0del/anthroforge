#pragma once
namespace af_layer {
static int representative(std::vector<int>& parents,int v) {
    while(parents[v]!=v){parents[v]=parents[parents[v]];v=parents[v];}return v;
}
static std::vector<int> collapsed_edges(const afs::Mesh& mesh,double threshold) {
    std::vector<int> parents(mesh.vertices.rows());std::iota(parents.begin(),parents.end(),0);
    for(int f=0;f<mesh.faces.rows();++f)for(int j=0;j<3;++j){int a=mesh.faces(f,j),b=mesh.faces(f,(j+1)%3);
        if((mesh.vertices.row(a)-mesh.vertices.row(b)).norm()<=threshold)parents[representative(parents,b)]=representative(parents,a);}
    for(int& v:parents)v=representative(parents,v);return parents;
}
static std::vector<std::array<int,3>> usable_faces(const afs::Mesh& mesh,const std::vector<int>& parents,double threshold) {
    std::vector<std::array<int,3>> result;std::set<std::array<int,3>> unique;
    for(int f=0;f<mesh.faces.rows();++f){std::array<int,3> ids{parents[mesh.faces(f,0)],parents[mesh.faces(f,1)],parents[mesh.faces(f,2)]};
        Vec v[3];for(int j=0;j<3;++j)v[j]={mesh.vertices(ids[j],0),mesh.vertices(ids[j],1),mesh.vertices(ids[j],2)};
        if(norm(cross(sub(v[1],v[0]),sub(v[2],v[0])))<=threshold)continue;
        auto sorted=ids;std::sort(sorted.begin(),sorted.end());if(unique.insert(sorted).second)result.push_back(ids);}
    return result;
}
static void compact_material(Material& material,const std::vector<int>& parents,const std::vector<std::array<int,3>>& faces) {
    std::map<int,int> ids;for(const auto& face:faces)for(int v:face)ids.emplace(v,0);
    afs::Mesh mesh;mesh.vertices.resize(ids.size(),3);mesh.faces.resize(faces.size(),3);int next=0;
    for(auto& item:ids){item.second=next;mesh.vertices.row(next++)=material.mesh.vertices.row(item.first);}
    for(int i=0;i<int(faces.size());++i)for(int j=0;j<3;++j)mesh.faces(i,j)=ids.at(faces[i][j]);
    for(size_t i=0;i<material.interpolation.size();++i){auto it=ids.find(parents[material.interpolation[i]]);
        require(it!=ids.end()||std::abs(material.weights[i])<1e-15,"STACK_ISOLATED_MATERIAL_SAMPLE");material.interpolation[i]=it==ids.end()?0:it->second;}
    std::set<int64_t> pins;for(auto pin:material.fixed)if(ids.count(parents[pin])){
        int mapped=ids.at(parents[pin]);pins.insert(mapped);material.original_pins.emplace(mapped,pin);}
    material.fixed.assign(pins.begin(),pins.end());material.mesh=std::move(mesh);
    for(auto& row:material.constraints)for(auto& term:row.terms){
        require(ids.count(parents[term.first]),"STACK_ISOLATED_ATTACHMENT");term.first=ids.at(parents[term.first]);}
}
static void normalize_material(Material& material) {
    double scale=(material.mesh.vertices.colwise().maxCoeff()-material.mesh.vertices.colwise().minCoeff()).norm();
    auto parents=collapsed_edges(material.mesh,scale*1e-12);auto faces=usable_faces(material.mesh,parents,scale*scale*1e-12);
    compact_material(material,parents,faces);afs::validate_mesh(material.mesh);
}
}

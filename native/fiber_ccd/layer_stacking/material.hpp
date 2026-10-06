#pragma once
namespace af_layer {
static Material capture_material(const ConstraintInput& in,const Side& side) {
    require(in.valid!=0,"STACK_STALE_INTRINSIC_INPUT");
    require(in.vertices>=3&&in.triangles>0&&in.samples==int(side.base.size())&&in.width>=1&&in.width<=4,"STACK_MATERIAL_SIZE");
    require(in.material&&in.faces&&in.interpolation&&in.weights&&(in.pins==0||in.fixed),"STACK_MATERIAL_MISSING");
    Material out;out.width=in.width;out.mesh.vertices.resize(in.vertices,3);out.mesh.faces.resize(in.triangles,3);
    for(int i=0;i<in.vertices;++i)for(int j=0;j<3;++j){double x=in.material[i*3+j];require(std::isfinite(x),"STACK_MATERIAL_COORDINATES");out.mesh.vertices(i,j)=x;}
    for(int i=0;i<in.triangles;++i)for(int j=0;j<3;++j){auto index=in.faces[i*3+j];require(index>=0&&index<in.vertices,"STACK_MATERIAL_FACE");out.mesh.faces(i,j)=int(index);}
    out.interpolation.assign(in.interpolation,in.interpolation+size_t(in.samples)*in.width);
    out.weights.assign(in.weights,in.weights+size_t(in.samples)*in.width);
    for(size_t i=0;i<out.weights.size();++i)require(out.interpolation[i]>=0&&out.interpolation[i]<in.vertices&&std::isfinite(out.weights[i]),"STACK_INTERPOLATION");
    for(int i=0;i<in.pins;++i){require(in.fixed[i]>=0&&in.fixed[i]<in.vertices,"STACK_PIN_INDEX");out.fixed.push_back(in.fixed[i]);}
    for(int i=0;i<in.samples;++i){double sum=0;for(int j=0;j<in.width;++j)sum+=out.weights[i*in.width+j];require(std::abs(sum-1)<1e-9,"STACK_INTERPOLATION_SUM");}
    return out;
}
static double sample(const Material& material,const afs::Vector& field,int index) {
    double value=0;for(int j=0;j<material.width;++j){size_t k=size_t(index)*material.width+j;value+=material.weights[k]*field[material.interpolation[k]];}return value;
}
static std::vector<Vec> displaced(const Side& side,const Material& material,const afs::Vector& field) {
    std::vector<Vec> out=side.own;for(size_t i=0;i<out.size();++i)out[i]=add(out[i],mul(side.direction[i],sample(material,field,int(i))));return out;
}
static afs::Field bonus_field(const Material& material,const Settings& settings) {
    int size=int(material.mesh.vertices.rows());afs::Field field;
    field.target=afs::Vector::Zero(size);field.lower=field.target;field.upper=afs::Vector::Constant(size,settings.maximum);
    for(auto pin:material.fixed)field.upper[pin]=0;
    field.radius=settings.radius;field.strength=settings.strength;return field;
}
static void interpolate_terms(std::map<int,double>& terms,const Material& material,int vertex,double coefficient) {
    for(int j=0;j<material.width;++j){size_t k=size_t(vertex)*material.width+j;terms[int(material.interpolation[k])]+=coefficient*material.weights[k];}
}
}

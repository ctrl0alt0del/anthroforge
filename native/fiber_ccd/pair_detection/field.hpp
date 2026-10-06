#pragma once
namespace af_pair {
struct FieldInput {
    const Vec *base,*outer,*reference,*limiting;
    const int64_t *faces,*sources,*reference_faces;
    int vertices,triangles,reference_vertices,reference_count,reference_width;
};
static std::vector<Vec> limiting(const std::vector<Vec>& base,int rows,int cols,int mode,int direction,int sign,Vec control,double depth) {
    std::vector<double> areas;
    if(mode==2){auto result=af_env_directions(af_env_frames(base,rows,cols,areas),areas,rows,cols,direction);
        for(auto& value:result)value=mul(af_env_unit(value),sign);return result;}
    auto result=af_muscle_normals(base,rows,cols,mode==1);
    Vec n0=result[af_muscle_closest(base,control)],center=sub(control,mul(n0,depth*sign));
    for(size_t i=0;i<result.size();++i){Vec d=mode==1?mul(result[i],sign):sub(base[i],center);
        result[i]=af_env_unit(norm(d)>1e-12?d:mul(n0,sign));}
    return result;
}
static Vec barycentric(Vec p,const Vec* t) {
    Vec a=sub(t[1],t[0]),b=sub(t[2],t[0]),c=sub(p,t[0]);
    double aa=dot(a,a),ab=dot(a,b),bb=dot(b,b),ca=dot(c,a),cb=dot(c,b),den=aa*bb-ab*ab;
    require(std::abs(den)>1e-28,"PAIR_LIMITING_FRAME_DEGENERATE");
    double v=(bb*ca-ab*cb)/den,w=(aa*cb-ab*ca)/den;return {1-v-w,v,w};
}
static Vec interpolate(const FieldInput& in,int source,Vec point) {
    require(source>=0&&source<in.reference_count,"PAIR_SOURCE_FACE_INVALID");
    const auto* ids=in.reference_faces+source*in.reference_width;double distance=INFINITY;Vec best{};
    for(int k=0;k<in.reference_width;++k)if(ids[k]>=0&&ids[k]<in.reference_vertices&&
        norm(sub(point,in.reference[ids[k]]))<=1e-12&&norm(in.limiting[ids[k]])>1e-12)return af_env_unit(in.limiting[ids[k]]);
    for(int j=1;j<in.reference_width-1;++j){int64_t selected[]={ids[0],ids[j],ids[j+1]};Vec t[3],d[3];
        for(int k=0;k<3;++k){require(selected[k]>=0&&selected[k]<in.reference_vertices,"PAIR_REFERENCE_INDEX");
            t[k]=in.reference[selected[k]];d[k]=in.limiting[selected[k]];}
        if(norm(cross(sub(t[1],t[0]),sub(t[2],t[0])))<=1e-14)continue;
        Vec closest=af_closest_triangle(point,t);double gap=norm(sub(point,closest));
        if(gap<distance){distance=gap;Vec b=barycentric(closest,t);best=add(mul(d[0],b.x),add(mul(d[1],b.y),mul(d[2],b.z)));}}
    require(std::isfinite(distance)&&norm(best)>1e-12,"PAIR_LIMITING_FRAME_DEGENERATE");return af_env_unit(best);
}
static void build_field(const FieldInput& in,Vec* output) {
    require(in.vertices>=0&&in.triangles>=0&&(in.reference_width==3||in.reference_width==4),"PAIR_FIELD_SHAPE");
    std::vector<int> source(in.vertices,-1);
    for(int i=0;i<in.triangles;++i)for(int k=0;k<3;++k){auto v=in.faces[3*i+k];
        require(v>=0&&v<in.vertices,"PAIR_FIELD_INDEX");if(source[v]<0)source[v]=int(in.sources[i]);}
    for(int i=0;i<in.vertices;++i){Vec d=sub(in.outer[i],in.base[i]);
        require(finite(in.base[i])&&finite(in.outer[i]),"PAIR_NONFINITE");
        output[i]=norm(d)>1e-12?af_env_unit(d):interpolate(in,source[i],in.base[i]);}
}
}
AF_EXPORT int af_pair_limiting(const double* points,int rows,int cols,int mode,int direction,int sign,const double* control,double depth,double* output) {
    if(!points||!output||!control||rows<2||cols<2||int64_t(rows)*cols>20000000||mode<0||mode>2||direction<0||direction>2||(sign!=1&&sign!=-1))return 1;
    try {auto* first=reinterpret_cast<const Vec*>(points);std::vector<Vec> base(first,first+size_t(rows)*cols);
        for(auto p:base)af_pair::require(af_pair::finite(p),"PAIR_NONFINITE");
        auto values=af_pair::limiting(base,rows,cols,mode,direction,sign,af_vec(control),depth);
        std::memcpy(output,values.data(),values.size()*sizeof(Vec));return 0;
    }catch(...){return 2;}
}
AF_EXPORT int af_pair_build_field(const af_pair::FieldInput* input,double* output) {
    if(!input||!output||!input->base||!input->outer||!input->reference||!input->limiting||!input->faces||!input->sources||!input->reference_faces)return 1;
    try{af_pair::build_field(*input,reinterpret_cast<Vec*>(output));return 0;}catch(...){return 2;}
}
AF_EXPORT int af_pair_blend_directions(const double* first,const double* second,int count,double* output) {
    if(!first||!second||!output||count<0)return 1;
    for(int i=0;i<count;++i){Vec a=load3(first+3*i),b=load3(second+3*i),d=mul(add(a,b),.5);
        output[3*i]=d.x;output[3*i+1]=d.y;output[3*i+2]=d.z;}
    return 0;
}
AF_EXPORT int af_pair_orientation(const double* points,const double* directions,const int64_t* faces,int count) {
    if(!points||!directions||!faces||count<=0)return 0;
    try{std::vector<double> signs;signs.reserve(count);
        for(int i=0;i<count;++i){Vec p[3],d{};
            for(int k=0;k<3;++k){auto v=faces[3*i+k];p[k]=load3(points+3*v);d=add(d,load3(directions+3*v));}
            signs.push_back(dot(cross(sub(p[1],p[0]),sub(p[2],p[0])),d));}
        auto middle=signs.begin()+signs.size()/2;std::nth_element(signs.begin(),middle,signs.end());double median=*middle;
        if(signs.size()%2==0)median=(median+*std::max_element(signs.begin(),middle))*.5;
        return median<0?-1:1;
    }catch(...){return 0;}
}

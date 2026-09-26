#pragma once
#include <map>

static bool af_env_equal(Vec a,Vec b) { return a.x==b.x&&a.y==b.y&&a.z==b.z; }

static std::vector<bool> af_env_boundary(const int64_t* faces,int count,int width,int vertices) {
    std::map<std::pair<int64_t,int64_t>,int> edges;std::vector<bool> boundary(vertices,false);
    for(int i=0;i<count;++i)for(int j=0;j<width;++j){auto a=faces[i*width+j],b=faces[i*width+(j+1)%width];
        if(a<0||a>=vertices||b<0||b>=vertices)throw std::runtime_error("invalid envelope face");
        edges[std::minmax(a,b)]++;}
    for(auto& item:edges)if(item.second==1)boundary[item.first.first]=boundary[item.first.second]=true;
    return boundary;
}

static int af_env_vertices(const Vec* a,const Vec* b,int count,const std::vector<bool>& boundary,Vec* out,std::vector<int64_t>& map) {
    std::copy(a,a+count,out);int used=count;map.resize(count);
    for(int i=0;i<count;++i){if(boundary[i]&&af_env_equal(a[i],b[i]))map[i]=i;
        else {map[i]=used;out[used++]=b[i];}}
    return used;
}

static bool af_env_shared(const Vec* a,const Vec* b,const int64_t* face,int width) {
    for(int j=0;j<width;++j)if(!af_env_equal(a[face[j]],b[face[j]]))return false;
    return true;
}

static int af_env_faces(const Vec* a,const Vec* b,const int64_t* faces,int count,int width,const std::vector<int64_t>& map,
                       int flip,int64_t* out,int64_t* sources,int64_t* sides) {
    int used=0;for(int i=0;i<count;++i){const auto* face=faces+i*width;bool shared=af_env_shared(a,b,face,width);
        for(int j=0;j<width;++j)out[used*width+j]=face[flip?width-1-j:j];sources[used]=i;sides[used++]=shared?0:1;
        if(shared)continue;
        for(int j=0;j<width;++j)out[used*width+j]=map[face[flip?j:width-1-j]];sources[used]=i;sides[used++]=2;}
    return used;
}

static int af_env_compact(double* vertices,int count,int64_t* faces,int indices) {
    std::vector<int64_t> mapping(count,-1);for(int i=0;i<indices;++i)mapping[faces[i]]=0;
    auto* points=reinterpret_cast<Vec*>(vertices);int used=0;
    for(int i=0;i<count;++i)if(mapping[i]==0){mapping[i]=used;points[used++]=points[i];}
    for(int i=0;i<indices;++i)faces[i]=mapping[faces[i]];
    return used;
}

AF_EXPORT int af_muscle_envelope_compose(const double* a,const double* b,int count,const int64_t* faces,int face_count,int width,int flip,
    double* vertices,int64_t* output_faces,int64_t* sources,int64_t* sides,int* sizes) {
    if(!a||!b||!faces||!vertices||!output_faces||!sources||!sides||!sizes||count<0||face_count<0||(width!=3&&width!=4))return 1;
    try {auto* first=reinterpret_cast<const Vec*>(a);auto* second=reinterpret_cast<const Vec*>(b);
        auto boundary=af_env_boundary(faces,face_count,width,count);std::vector<int64_t> mapping;
        sizes[0]=af_env_vertices(first,second,count,boundary,reinterpret_cast<Vec*>(vertices),mapping);
        sizes[1]=af_env_faces(first,second,faces,face_count,width,mapping,flip,output_faces,sources,sides);
        sizes[0]=af_env_compact(vertices,sizes[0],output_faces,sizes[1]*width);return 0;
    } catch(...) {return 2;}
}

AF_EXPORT int af_muscle_envelope_diagnostics(const double* points,int count,const int64_t* faces,int face_count,int width,double* stats) {
    if(!points||!faces||!stats||count<0||face_count<0||(width!=3&&width!=4))return 1;
    try {std::fill(stats,stats+4,0.);std::map<std::pair<int64_t,int64_t>,int> edges;auto* v=reinterpret_cast<const Vec*>(points);
        for(int i=0;i<face_count;++i){const auto* f=faces+i*width;double area=0.;
            for(int j=0;j<width;++j){auto a=f[j],b=f[(j+1)%width];if(a<0||b<0||a>=count||b>=count)return 1;edges[std::minmax(a,b)]++;}
            for(int j=1;j<width-1;++j)area+=.5*norm(cross(sub(v[f[j]],v[f[0]]),sub(v[f[j+1]],v[f[0]])));
            stats[0]+=area;if(area==0)stats[3]++;}
        for(auto& e:edges){if(e.second==1)stats[1]++;if(e.second>2)stats[2]++;}return 0;
    } catch(...) {return 2;}
}

static std::vector<Vec> af_env_normals(const Vec* base,int count,const int64_t* faces,int face_count,int width) {
    std::vector<Vec> normals(count,Vec{0,0,0});
    for(int i=0;i<face_count;++i){const auto* f=faces+i*width;
        for(int j=0;j<width;++j)if(f[j]<0||f[j]>=count)throw std::runtime_error("invalid envelope face");
        Vec n=cross(sub(base[f[1]],base[f[0]]),sub(base[f[2]],base[f[0]]));
        for(int j=0;j<width;++j)normals[f[j]]=add(normals[f[j]],n);}
    return normals;
}

AF_EXPORT int af_muscle_envelope_side_diagnostics(const double* base,const double* side,int count,const int64_t* faces,
    int face_count,int width,int sign,double* stats) {
    if(!base||!side||!faces||!stats||count<0||face_count<0||(width!=3&&width!=4)||(sign!=1&&sign!=-1))return 1;
    try{auto* b=reinterpret_cast<const Vec*>(base);auto* s=reinterpret_cast<const Vec*>(side);
        auto normals=af_env_normals(b,count,faces,face_count,width);std::fill(stats,stats+5,0.);
        for(int i=0;i<count;++i){double length=norm(normals[i]);if(length<1e-20){stats[4]++;continue;}
            double d=sign*dot(sub(s[i],b[i]),normals[i])/length;
            stats[0]=std::min(stats[0],d);stats[1]=std::max(stats[1],d);if(d<-1e-9)stats[2]++;}
        for(int i=0;i<face_count;++i){const auto* f=faces+i*width;
            auto original=cross(sub(b[f[1]],b[f[0]]),sub(b[f[2]],b[f[0]]));
            auto displaced=cross(sub(s[f[1]],s[f[0]]),sub(s[f[2]],s[f[0]]));
            if(dot(original,displaced)<0)stats[3]++;}return 0;
    }catch(...){return 2;}
}

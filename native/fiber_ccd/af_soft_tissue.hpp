// Batched static tissue evaluation. All iterations and projections stay native.
#include <set>
#include <chrono>
namespace af_tissue {
constexpr double epsilon = 1.e-12;
using Points = std::vector<Vec>;
using Tri = std::array<int, 3>;
struct Settings {
    int iterations, passes, front;
    double step, shape, volume, seed, growth, velocity, slack, limit, tolerance;
    Vec gravity;
};
struct State {
    Points rest, points, velocity, normals, goals;
    std::vector<Tri> triangles, surface;
    std::vector<std::array<int, 2>> edges;
    std::vector<double> lengths, mass, load;
    double start, target;
};
inline Vec unit(Vec value) { return mul(value, 1.0 / std::max(norm(value), epsilon)); }
inline Settings settings(const double* p) {
    return {int(p[0]), int(p[1]), int(p[2]), p[3], p[4], p[5], p[6], p[7],
            p[8], p[9], p[10], p[11], {p[12], p[13], p[14]}};
}
inline Vec center(const Points& points) {
    Vec value{};
    for (auto p : points) value = add(value, p);
    return mul(value, 1.0 / std::max(size_t(1), points.size()));
}
inline double volume(const Points& points, const std::vector<Tri>& triangles) {
    const Vec origin = center(points);
    double result = 0;
    for (auto t : triangles)
        result += dot(sub(points[t[0]], origin), cross(sub(points[t[1]], origin), sub(points[t[2]], origin))) / 6.;
    return result;
}
inline double change(const Points& a, const Points& b) {
    double result = 0;
    for (size_t i = 0; i < a.size(); ++i) result = std::max(result, norm(sub(a[i], b[i])));
    return result;
}
inline void pin(State& s) {
    for (size_t i = 0; i < s.points.size(); ++i) if (!s.mass[i]) s.points[i] = s.goals[i];
}
inline void topology(State& s, const int* triangles, int count, int front) {
    std::set<std::array<int, 2>> edges;
    for (int i = 0; i < count; ++i) {
        Tri t{triangles[3*i], triangles[3*i+1], triangles[3*i+2]}; s.triangles.push_back(t);
        if (front && (t[0] >= front || t[1] >= front || t[2] >= front)) continue;
        s.surface.push_back(t);
        for (int j = 0; j < 3; ++j) edges.insert({std::min(t[j], t[(j+1)%3]), std::max(t[j], t[(j+1)%3])});
    }
    for (auto edge : edges) {
        s.edges.push_back(edge); s.lengths.push_back(norm(sub(s.rest[edge[0]], s.rest[edge[1]])));
    }
}
inline void seed(State& s, const Settings& c) {
    s.normals.resize(c.front);
    for (int i = 0; i < c.front; ++i) {
        Vec delta = sub(s.rest[i], s.rest[c.front+i]); s.normals[i] = unit(delta);
        if (s.mass[i]) s.points[i] = add(s.rest[c.front+i], mul(delta, c.seed));
    }
}
inline double load_scale(const State& s, int count) {
    Vec low = s.rest[count], high = low; double thickness = 0;
    for (int i = 0; i < count; ++i) {
        Vec p = s.rest[count+i];
        low = {std::min(low.x,p.x), std::min(low.y,p.y), std::min(low.z,p.z)};
        high = {std::max(high.x,p.x), std::max(high.y,p.y), std::max(high.z,p.z)};
        thickness = std::max(thickness, norm(sub(s.rest[i],p)));
    }
    return std::clamp(2.*thickness/std::max(norm(sub(high,low)),epsilon), .5, 4.);
}
inline void column_load(State& s, int count) {
    for (auto t : s.surface) {
        Vec a=s.rest[count+t[0]], b=s.rest[count+t[1]], c=s.rest[count+t[2]];
        double thickness=0;
        for (int i : t) thickness += norm(sub(s.rest[i],s.rest[count+i]))/3.;
        double load=.5*norm(cross(sub(b,a),sub(c,a)))*thickness/3.;
        for (int i : t) s.load[i] += load;
    }
    double total=0, active=0;
    for (size_t i=0;i<s.mass.size();++i) if(s.mass[i]) { total+=s.load[i]; active+=1; }
    double mean=std::max(active ? total/active : 1.,epsilon), scale=load_scale(s,count);
    for (size_t i=0;i<s.load.size();++i) s.load[i]=s.mass[i] ? scale*std::clamp(s.load[i]/mean,.2,5.) : s.load[i]/mean;
}
inline State create(const double* points, int n, const int* triangles, int m, const double* mass, const double* goals, const Settings& c) {
    State s;
    for(int i=0;i<n;++i) { s.rest.push_back(load3(points+3*i)); s.goals.push_back(load3(goals+3*i)); }
    s.points=s.rest; s.velocity.resize(n); s.load.resize(n,0); s.mass.assign(mass,mass+n);
    if(c.front) for(int i=c.front;i<n;++i) s.mass[i]=0;
    topology(s,triangles,m,c.front);
    if(c.front) { seed(s,c); column_load(s,c.front); }
    pin(s); s.start=volume(s.points,s.triangles); s.target=volume(s.rest,s.triangles);
    return s;
}
inline void project_volume(State& s, double target, double retention) {
    Points gradients(s.points.size()); Vec origin=center(s.points);
    for(auto t:s.triangles) for(int j=0;j<3;++j) {
        Vec value=cross(sub(s.points[t[(j+1)%3]],origin),sub(s.points[t[(j+2)%3]],origin));
        gradients[t[j]]=add(gradients[t[j]],mul(value,1./6.));
    }
    double denominator=0;
    for(size_t i=0;i<gradients.size();++i) denominator+=s.mass[i]*dot(gradients[i],gradients[i]);
    if(denominator<=epsilon)return;
    double scale=retention*(volume(s.points,s.triangles)-target)/denominator;
    for(size_t i=0;i<s.points.size();++i) s.points[i]=sub(s.points[i],mul(gradients[i],scale*s.mass[i]));
}
inline double edge_strength(double strain, const Settings& c) {
    if(!c.front)return c.shape;
    double total=strain>0 ? .08+.30*c.shape : .005*c.shape;
    return 1.-std::pow(1.-total,1./c.passes);
}
inline Vec edge_correction(const State& s, const Settings& c, size_t i) {
    int a=s.edges[i][0], b=s.edges[i][1]; Vec delta=sub(s.points[b],s.points[a]);
    double length=std::max(norm(delta),epsilon), strain=length-s.lengths[i];
    if(c.front && strain>0) strain=std::max(0.,length-s.lengths[i]*(1.+.25*c.slack));
    double scale=edge_strength(strain,c)*strain/(length*std::max(s.mass[a]+s.mass[b],epsilon));
    return mul(delta,scale);
}
inline void project_edges(State& s, const Settings& c) {
    Points updates(s.points.size()); std::vector<double> degree(s.points.size(),0);
    for(size_t i=0;i<s.edges.size();++i) {
        int a=s.edges[i][0],b=s.edges[i][1]; Vec correction=edge_correction(s,c,i);
        updates[a]=add(updates[a],mul(correction,s.mass[a])); updates[b]=sub(updates[b],mul(correction,s.mass[b]));
        degree[a]+=s.mass[a]; degree[b]+=s.mass[b];
    }
    for(size_t i=0;i<s.points.size();++i) s.points[i]=add(s.points[i],mul(updates[i],1./std::max(1.,degree[i])));
}
inline void tension(State& s, const Settings& c) {
    Points gradients(s.points.size()); std::vector<double> counts(s.points.size(),0);
    for(auto t:s.surface) {
        Vec normal=unit(cross(sub(s.points[t[1]],s.points[t[0]]),sub(s.points[t[2]],s.points[t[0]])));
        for(int j=0;j<3;++j) {
            Vec value=mul(cross(normal,sub(s.points[t[(j+2)%3]],s.points[t[(j+1)%3]])),.5);
            gradients[t[j]]=add(gradients[t[j]],value); counts[t[j]]+=1.;
        }
    }
    double strength=1.-std::pow(1.-(.1+.4*c.shape)*(1.-.5*c.slack),1./c.passes);
    for(size_t i=0;i<s.points.size();++i) if(s.mass[i]) s.points[i]=sub(s.points[i],mul(gradients[i],strength/std::max(1.,counts[i])));
}
inline void tethers(State& s, const Settings& c, const double* rows, int count) {
    for(int i=0;i<count;++i) {
        const double* row=rows+6*i; int index=int(row[0]);
        if(!s.mass[index])continue;
        Vec delta=sub(s.points[index],load3(row+1)); double length=std::max(norm(delta),epsilon);
        double strength=1.-std::pow(1.-row[5],1./(c.iterations*c.passes));
        s.points[index]=sub(s.points[index],mul(delta,strength*(length-row[4])/length));
    }
}
inline void support(State& s, const Settings& c) {
    Vec gravity=unit(c.gravity);
    for(int i=0;i<c.front;++i) if(s.mass[i]) {
        double depth=dot(sub(s.points[i],s.rest[c.front+i]),s.normals[i]);
        s.points[i]=add(s.points[i],mul(s.normals[i],std::max(0.,-depth)));
        double rise=-dot(sub(s.points[i],s.rest[i]),gravity);
        if(std::abs(dot(s.normals[i],gravity))<.5 && rise>0) s.points[i]=add(s.points[i],mul(gravity,rise));
    }
}
inline void sag_limit(State& s, double limit) {
    if(limit<=0)return;
    for(size_t i=0;i<s.points.size();++i) if(s.mass[i]) {
        Vec delta=sub(s.points[i],s.rest[i]); double length=norm(delta);
        if(length>limit) s.points[i]=add(s.rest[i],mul(delta,limit/length));
    }
}
inline void predict(State& s, const Settings& c) {
    Vec gravity=c.front ? unit(c.gravity) : c.gravity;
    for(size_t i=0;i<s.points.size();++i) if(s.mass[i]) {
        if(c.front) { s.velocity[i]=add(s.velocity[i],mul(gravity,c.step*s.load[i])); s.points[i]=add(s.points[i],s.velocity[i]); }
        else s.points[i]=add(s.points[i],mul(gravity,c.step));
    }
    pin(s);
}
inline void passes(State& s, const Settings& c, double target, const double* rows, int count) {
    for(int pass=0;pass<c.passes;++pass) {
        if(c.front && pass%2) project_volume(s,target,c.volume);
        project_edges(s,c);
        if(c.front)tension(s,c);
        tethers(s,c,rows,count);
        if(!c.front || !(pass%2))project_volume(s,target,c.volume);
        if(c.front)support(s,c); else sag_limit(s,c.limit);
        pin(s);
    }
}
inline double relative_volume(const State& s) { return std::abs(volume(s.points,s.triangles)-s.target)/std::max(std::abs(s.target),epsilon); }
inline bool volume_satisfied(const State& s,const Settings& c) { return c.volume<=0 || relative_volume(s)<=1.e-5; }
inline void finalize(State& s, const Settings& c) {
    int count=c.front ? std::max(12,c.passes*8) : c.passes;
    for(int i=0;i<count;++i) {
        project_volume(s,s.target,c.volume);
        if(c.front)support(s,c); else sag_limit(s,c.limit);
        pin(s);
        if(c.front && relative_volume(s)<=1.e-7)return;
    }
}
inline double growth(const State& s, int iteration, int count) {
    double value=std::clamp(double(iteration+1)/std::max(1,count),0.,1.);
    return s.start+value*value*(3.-2.*value)*(s.target-s.start);
}
inline int iterate(State& s, const Settings& c, const double* rows, int count, double& last) {
    int settle=std::max(1,int(std::nearbyint(c.iterations*c.growth)));
    double tolerance=c.step>0 ? std::min(c.tolerance,c.step*.01) : c.tolerance;
    for(int i=0;i<c.iterations;++i) {
        Points before=s.points; predict(s,c);
        passes(s,c,c.front ? growth(s,i,settle) : s.target,rows,count);
        for(size_t j=0;j<s.points.size();++j) s.velocity[j]=mul(sub(s.points[j],before[j]),c.velocity*s.mass[j]);
        last=change(s.points,before);
        if((!c.front || i>=settle) && last<=tolerance && volume_satisfied(s,c))return i+1;
    }
    return c.iterations;
}
inline bool valid(const double* p,int n,const int* t,int m,const double* mass,const double* goals,const double* rows,int count,const Settings& c) {
    if(n<4 || m<1 || c.iterations<1 || c.passes<1 || c.front<0 || (c.front && c.front*2!=n))return false;
    if(c.step<0 || c.tolerance<=0 || c.shape<0 || c.shape>1 || c.volume<0 || c.volume>1)return false;
    for(int i=0;i<n*3;++i)if(!std::isfinite(p[i]) || !std::isfinite(goals[i]))return false;
    for(int i=0;i<m*3;++i)if(t[i]<0 || t[i]>=n)return false;
    for(int i=0;i<n;++i)if(mass[i]!=0 && mass[i]!=1)return false;
    for(int i=0;i<count;++i) {
        const double* r=rows+6*i;
        if(r[0]<0 || r[0]>=n || r[4]<0 || r[5]<0 || r[5]>1)return false;
        for(int j=0;j<6;++j)if(!std::isfinite(r[j]))return false;
    }
    return true;
}
inline int solve(State& s,const Settings& c,const double* rows,int count,double* output,double* report) {
    double last=0; int iterations=iterate(s,c,rows,count,last); Points before=s.points; finalize(s,c);
    last=std::max(last,change(s.points,before));
    double threshold=c.step>0 ? std::min(c.tolerance,c.step*.01) : c.tolerance;
    report[0]=last<=threshold && volume_satisfied(s,c) ? 1 : 2; report[1]=iterations; report[2]=last;
    report[3]=change(s.points,s.rest); report[4]=relative_volume(s); report[5]=0;
    for(size_t i=0;i<s.points.size();++i) {
        Vec p=s.points[i]; if(!std::isfinite(p.x)||!std::isfinite(p.y)||!std::isfinite(p.z))return 4;
        output[3*i]=p.x; output[3*i+1]=p.y; output[3*i+2]=p.z;
        if(!s.mass[i]) report[5]=std::max(report[5],norm(sub(p,s.goals[i])));
    }
    return 0;
}
} // namespace af_tissue
AF_EXPORT int af_soft_tissue_version() { return 1; }
AF_EXPORT int af_soft_tissue_solve(const double* points,int n,const int* triangles,int m,const double* mass,
    const double* goals,const double* rows,int count,const double* parameters,double* output,double* report) {
    auto start=std::chrono::steady_clock::now();
    try {
        auto c=af_tissue::settings(parameters);
        if(!af_tissue::valid(points,n,triangles,m,mass,goals,rows,count,c))return 3;
        auto s=af_tissue::create(points,n,triangles,m,mass,goals,c);
        int code=af_tissue::solve(s,c,rows,count,output,report);
        report[6]=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        return code;
    } catch(...) { return 4; }
}

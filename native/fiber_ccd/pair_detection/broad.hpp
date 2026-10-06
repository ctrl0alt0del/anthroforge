#pragma once
namespace af_pair {
static Bounds empty_bounds() {
    Bounds b{};for(int j=0;j<3;++j){b.lo[j]=INFINITY;b.hi[j]=-INFINITY;}return b;
}
static void extend(Bounds& b,Vec v) {
    for(int j=0;j<3;++j){b.lo[j]=std::min(b.lo[j],(&v.x)[j]);b.hi[j]=std::max(b.hi[j],(&v.x)[j]);}
}
static void expand(Bounds& b,double amount) {
    for(int j=0;j<3;++j){b.lo[j]-=amount;b.hi[j]+=amount;}
}
static bool intersects(const Bounds& a,const Bounds& b) {
    for(int j=0;j<3;++j)if(a.lo[j]>b.hi[j]||b.lo[j]>a.hi[j])return false;return true;
}
static void projected_bounds(const Side& s,Bounds& b) {
    for(size_t f=0;f<s.faces.size()/3;++f){Vec direction{0,0,0};
        for(int i=0;i<3;++i)direction=add(direction,s.direction[s.faces[3*f+i]]);
        if(norm(direction)<1e-12)continue;direction=af_env_unit(direction);
        for(int i=0;i<3;++i){auto id=s.faces[3*f+i];double h=dot(sub(s.own[id],s.base[id]),direction);
            extend(b,add(s.base[id],mul(direction,std::max(0.,h))));}}
}
static Bounds swept_bounds(const Side& s,double padding) {
    auto b=empty_bounds();
    for(size_t i=0;i<s.base.size();++i){extend(b,s.base[i]);extend(b,s.own[i]);
        extend(b,add(s.base[i],mul(s.direction[i],s.displacement)));
        extend(b,add(s.own[i],mul(s.direction[i],s.displacement)));}
    projected_bounds(s,b);expand(b,padding+s.displacement);return b;
}
static bool eligible(const Side& a,const Side& b) {
    return a.enabled&&b.enabled&&a.family!=b.family&&a.root==b.root&&a.instance==b.instance;
}
static std::vector<std::pair<int,int>> candidates(Session& s,bool exhaustive) {
    auto start=Clock::now();std::vector<std::pair<int,int>> pairs;
    for(size_t i=0;i<s.sides.size();++i)for(size_t j=i+1;j<s.sides.size();++j){
        if(!eligible(s.sides[i],s.sides[j]))continue;++s.result.stats[0];
        if(exhaustive||intersects(s.sides[i].bounds,s.sides[j].bounds)){
            require(pairs.size()<s.settings.result_bytes/128,"PAIR_RESULT_BUDGET");pairs.emplace_back(int(i),int(j));}}
    s.result.stats[1]=pairs.size();s.result.stats[5]=milliseconds(start);return pairs;
}
static Bounds query_bounds(const Query& q) {
    auto b=empty_bounds();double low=-q.settings.search-q.provider.displacement;
    double high=q.settings.search+q.receiver.displacement+q.provider.displacement;
    for(int i=0;i<3;++i){Vec origin=add(q.triangle[i],q.origin);
        double h=dot(sub(q.receiver.own[q.receiver.faces[q.rf*3+i]],origin),q.frame.d);
        extend(b,add(origin,mul(q.frame.d,low)));extend(b,add(origin,mul(q.frame.d,high+std::max(0.,h))));}
    expand(b,q.settings.epsilon);return b;
}
}

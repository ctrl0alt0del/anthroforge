#pragma once
namespace af_pair {
static void validate_settings(const Settings& s) {
    require(std::isfinite(s.search)&&s.search>=0&&std::isfinite(s.area)&&s.area>=0,"PAIR_SETTINGS");
    require(std::isfinite(s.epsilon)&&s.epsilon>0&&s.limit>0&&s.workers>=1&&s.workers<=4,"PAIR_SETTINGS");
    require(s.result_bytes>0,"PAIR_RESULT_BUDGET");
}
static void copy_points(Side& s,const Input& in) {
    s.base.reserve(in.vertices);s.own.reserve(in.vertices);s.direction.reserve(in.vertices);
    for(int i=0;i<in.vertices;++i){
        Vec b=load3(in.base+3*i),x=load3(in.own+3*i),d=load3(in.direction+3*i);
        require(finite(b)&&finite(x)&&finite(d)&&std::abs(norm(d)-1)<1e-6,"PAIR_COORDINATES");
        s.base.push_back(b);s.own.push_back(x);s.direction.push_back(d);
    }
}
static Side capture(const Input& in) {
    require(in.id&&in.vertices>=3&&in.triangles>0&&in.vertices<=10000000&&in.triangles<=20000000,"PAIR_INPUT_SIZE");
    require(in.base&&in.own&&in.direction&&in.faces,"PAIR_INPUT_MISSING");
    require(std::isfinite(in.displacement)&&in.displacement>=0&&(in.side==0||in.side==1),"PAIR_INPUT_SETTINGS");
    Side s;s.id=in.id;s.family=in.family;s.root=in.root;s.instance=in.instance;
    s.enabled=in.enabled;s.inflation_side=in.side;s.displacement=in.displacement;copy_points(s,in);
    s.faces.assign(in.faces,in.faces+size_t(in.triangles)*3);
    for(int64_t f:s.faces)require(f>=0&&f<in.vertices,"PAIR_TRIANGLE_INDEX");
    for(int i=0;i<in.triangles;++i){s.parts.push_back(in.parts?in.parts[i]:0);s.sources.push_back(in.sources?in.sources[i]:i);}
    return s;
}
template<class T> static bool same(const std::vector<T>& a,const std::vector<T>& b) {
    return a.size()==b.size()&&(a.empty()||std::memcmp(a.data(),b.data(),sizeof(T)*a.size())==0);
}
static bool unchanged(const Side& a,const Side& b) {
    return a.family==b.family&&a.root==b.root&&a.instance==b.instance&&a.enabled==b.enabled&&
        a.inflation_side==b.inflation_side&&a.displacement==b.displacement&&same(a.base,b.base)&&
        same(a.own,b.own)&&same(a.direction,b.direction)&&same(a.faces,b.faces)&&same(a.parts,b.parts)&&same(a.sources,b.sources);
}
static void prepare_snapshot(Side& next,Side* old) {
    if(old&&same(old->faces,next.faces)&&old->own.size()==next.own.size()){
        next.snapshot=std::move(old->snapshot);
        require(update_snapshot(*next.snapshot,reinterpret_cast<const double*>(next.own.data()),int(next.own.size())),"PAIR_REFIT_FAILED");
    }else next.snapshot.reset(create_snapshot(reinterpret_cast<const double*>(next.own.data()),next.faces.data(),int(next.faces.size()/3)));
}
static void upsert(Session& s,Side next) {
    auto it=s.indices.find(next.id);
    if(it!=s.indices.end()){
        auto& old=s.sides[it->second];if(unchanged(old,next))return;
        next.revision=old.revision+1;prepare_snapshot(next,&old);old=std::move(next);
        old.bounds=swept_bounds(old,s.settings.search+s.settings.epsilon);return;
    }
    prepare_snapshot(next,nullptr);next.bounds=swept_bounds(next,s.settings.search+s.settings.epsilon);
    auto free=std::find_if(s.sides.begin(),s.sides.end(),[](const Side& side){return side.id==0;});
    s.indices[next.id]=int(free-s.sides.begin());
    if(free==s.sides.end())s.sides.push_back(std::move(next));else *free=std::move(next);
}
static void remove_missing(Session& s,const std::set<uint64_t>& live) {
    for(auto it=s.indices.begin();it!=s.indices.end();){
        if(live.count(it->first)){++it;continue;}
        int index=it->second;s.sides[index]=Side{};it=s.indices.erase(it);
        s.cache.invalidate(index);
    }
}
static void synchronize(Session& s,std::vector<Side>& incoming,const Settings& settings) {
    bool changed=s.settings.search!=settings.search||s.settings.area!=settings.area||s.settings.epsilon!=settings.epsilon;
    s.settings=settings;if(changed)s.cache.clear();std::set<uint64_t> live;
    for(auto& side:incoming){live.insert(side.id);upsert(s,std::move(side));}
    remove_missing(s,live);
    if(changed)for(auto& side:s.sides)if(side.id)side.bounds=swept_bounds(side,settings.search+settings.epsilon);
}
}

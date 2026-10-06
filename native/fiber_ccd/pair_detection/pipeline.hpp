#pragma once
namespace af_pair {
struct Job { int a,b;bool dirty;std::shared_ptr<PairSummary> value;std::string error; };
static std::vector<Job> jobs(Session& s,bool exhaustive,Budget& budget) {
    auto pairs=candidates(s,exhaustive);std::set<std::pair<int,int>> live(pairs.begin(),pairs.end());std::vector<Job> out;
    claim_bytes(budget,pairs.size()*(sizeof(Job)+sizeof(PairSummary)+sizeof(PairRecord)));out.reserve(pairs.size());
    s.cache.retain(live);
    for(auto pair:pairs){int a=pair.first,b=pair.second;
        auto previous=exhaustive?nullptr:s.cache.find(pair,s.sides[a].revision,s.sides[b].revision);
        if(previous)budget.fragments+=previous->fragments;
        out.push_back({a,b,!previous,previous?previous:std::make_shared<PairSummary>(),{}});}
    require(budget.fragments<=budget.max_fragments,"PAIR_FRAGMENT_BUDGET");return out;
}
static void execute_job(const Session& s,Job& job,Budget& budget,bool exhaustive) {
    if(!job.dirty)return;
    try{Scratch scratch(budget);auto& r=scratch.value;
        map_direction(s,job.a,job.b,r,budget,exhaustive);map_direction(s,job.b,job.a,r,budget,exhaustive);
        *job.value={int64_t(r.fragments.size()),int64_t(r.points.size()),r.stats[3],r.stats[4]};}
    catch(const std::exception& error){job.error=error.what();}
    catch(...){job.error="PAIR_NATIVE_FAILURE";}
}
static void execute_jobs(const Session& s,std::vector<Job>& work,Budget& budget,bool exhaustive) {
    int workers=std::max(1,std::min({s.settings.workers,int(work.size()),af_parallel_limit()}));
    #pragma omp parallel for schedule(dynamic,1) num_threads(workers) if(workers>1)
    for(int i=0;i<int(work.size());++i)execute_job(s,work[i],budget,exhaustive);
}
static void append(Session& s,Published& out,const Job& job) {
    const auto& r=*job.value;auto start=int64_t(out.stats[8]);
    out.pairs.push_back({int64_t(s.sides[job.a].id),int64_t(s.sides[job.b].id),start,r.fragments,int64_t(r.warnings),r.points});
    out.stats[2]+=r.fragments>0;out.stats[3]+=job.dirty?r.queries:0;
    out.stats[4]+=r.warnings;out.stats[8]+=r.fragments;out.stats[9]+=r.points;
    out.stats[10]+=job.dirty;out.stats[11]+=!job.dirty;
    s.cache.put({job.a,job.b},s.sides[job.a].revision,s.sides[job.b].revision,job.value);
}
static Published detect(Session& s,uint64_t generation,std::atomic<bool>& cancelled,bool exhaustive) {
    auto start=Clock::now();s.result=Result{};Budget budget;
    budget.max_bytes=s.settings.result_bytes;budget.max_fragments=s.settings.limit;budget.cancelled=&cancelled;
    auto work=jobs(s,exhaustive,budget);auto narrow=Clock::now();execute_jobs(s,work,budget,exhaustive);
    for(const auto& job:work)require(job.error.empty(),job.error.c_str());check_cancel(budget);
    Published result;result.generation=generation;result.pairs.reserve(work.size());std::copy(s.result.stats,s.result.stats+10,result.stats);
    result.stats[6]=milliseconds(narrow);auto assembly=Clock::now();for(const auto& job:work)append(s,result,job);
    s.cache.evict(s.settings.cache_bytes);result.stats[14]=milliseconds(assembly);result.stats[7]=milliseconds(start);
    result.stats[15]=result.pairs.capacity()*sizeof(PairRecord);result.storage[0]=double(budget.peak);
    result.storage[1]=double(s.cache.bytes());result.storage[2]=result.stats[8]*sizeof(Fragment)+result.stats[9]*sizeof(Point);
    return result;
}
static Result pair_geometry(const Session& s,int index,std::atomic<bool>& cancel,bool exhaustive) {
    require(index>=0&&index<int(s.published.pairs.size()),"PAIR_NOT_FOUND");const auto& pair=s.published.pairs[index];
    Budget budget;budget.cancelled=&cancel;budget.max_bytes=s.settings.result_bytes;budget.max_fragments=s.settings.limit;Result out;
    int a=s.indices.at(pair.first),b=s.indices.at(pair.second);
    map_direction(s,a,b,out,budget,exhaustive);map_direction(s,b,a,out,budget,exhaustive);
    require(out.fragments.size()==size_t(pair.count)&&out.points.size()==size_t(pair.points),"PAIR_FOOTPRINT_MISMATCH");return out;
}
static int export_geometry(const Session& s,const Result& value,Fragment* rows,int nf,Point* points,int np) {
    if(nf<int(value.fragments.size())||np<int(value.points.size())||(!rows&&nf)||(!points&&np))return 2;
    for(size_t i=0;i<value.fragments.size();++i){auto f=value.fragments[i];f.receiver=s.sides[f.receiver].id;f.provider=s.sides[f.provider].id;rows[i]=f;}
    std::copy(value.points.begin(),value.points.end(),points);return 0;
}
}

#pragma once
namespace af_layer {
static void finish_explicit_pairs(Session& detection,const Budget& budget,Clock::time_point start) {
    auto& result=detection.published;detection.cache.evict(detection.settings.cache_bytes);
    result.stats[1]=double(result.pairs.size());result.stats[6]+=milliseconds(start);result.stats[7]+=milliseconds(start);
    result.stats[15]=result.pairs.capacity()*sizeof(PairRecord);
    result.storage[0]=std::max(result.storage[0],double(budget.peak));result.storage[1]=double(detection.cache.bytes());
    result.storage[2]=result.stats[8]*sizeof(Fragment)+result.stats[9]*sizeof(Point);
}
static void include_explicit_pairs(const State& state,Session& detection,std::atomic<bool>& cancel) {
    auto start=Clock::now();std::set<std::pair<uint64_t,uint64_t>> seen;
    for(const auto& p:detection.published.pairs)seen.insert(relationship_key(p.first,p.second));
    Budget budget;budget.cancelled=&cancel;budget.max_bytes=detection.settings.result_bytes;budget.max_fragments=detection.settings.limit;
    claim_bytes(budget,detection.published.pairs.capacity()*sizeof(PairRecord));
    budget.fragments=uint64_t(detection.published.stats[8]);
    for(const auto& item:state.policies){if(item.second.mode!=2||item.second.excluded||seen.count(item.first))continue;
        int a=detection.indices.at(item.first.first),b=detection.indices.at(item.first.second);
        require(detection.sides[a].root==detection.sides[b].root,"RELATIONSHIP_ROOT_MISMATCH");
        claim_bytes(budget,sizeof(PairRecord)+sizeof(Job)+sizeof(PairSummary));
        Job job{a,b,true,std::make_shared<PairSummary>(),{}};execute_job(detection,job,budget,false);
        require(job.error.empty(),job.error.c_str());append(detection,detection.published,job);}
    finish_explicit_pairs(detection,budget,start);
}
}

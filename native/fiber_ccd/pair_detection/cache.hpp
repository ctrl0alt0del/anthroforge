#pragma once
namespace af_pair {
void PairResultCache::retain(const std::set<Key>& live) {
    for(auto it=entries.begin();it!=entries.end();)if(!live.count(it->first))it=entries.erase(it);else ++it;
}
void PairResultCache::invalidate(int domain) {
    for(auto it=entries.begin();it!=entries.end();)
        if(it->first.first==domain||it->first.second==domain)it=entries.erase(it);else ++it;
}
std::shared_ptr<PairSummary> PairResultCache::find(Key key,uint64_t a,uint64_t b) const {
    auto it=entries.find(key);
    return it!=entries.end()&&it->second.a==a&&it->second.b==b?it->second.result:nullptr;
}
void PairResultCache::put(Key key,uint64_t a,uint64_t b,std::shared_ptr<PairSummary> value) {
    entries[key]={std::move(value),a,b,++clock};
}
void PairResultCache::evict(uint64_t budget) {
    while(bytes()>budget&&!entries.empty()){
        auto oldest=std::min_element(entries.begin(),entries.end(),[](const auto& a,const auto& b){return a.second.used<b.second.used;});
        entries.erase(oldest);
    }
}
}

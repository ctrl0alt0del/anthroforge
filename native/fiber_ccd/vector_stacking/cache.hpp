#pragma once
#include <mutex>
#include <tuple>
namespace af_stack_vector {
using CacheKey=std::tuple<int,uint64_t,uint64_t>;
struct CacheEntry { std::string signature;std::shared_ptr<void> value;uint64_t bytes=0,used=0; };
class Cache {
    std::mutex mutex_;std::map<CacheKey,CacheEntry> entries_;uint64_t clock_=0,bytes_=0;
public:
    template<class T> std::shared_ptr<T> find(CacheKey key,const std::string& signature) {
        std::lock_guard<std::mutex> lock(mutex_);auto it=entries_.find(key);
        if(it==entries_.end()||it->second.signature!=signature)return {};
        it->second.used=++clock_;return std::static_pointer_cast<T>(it->second.value);
    }
    template<class T> void put(CacheKey key,std::string signature,std::shared_ptr<T> value,uint64_t bytes,uint64_t budget) {
        std::lock_guard<std::mutex> lock(mutex_);auto it=entries_.find(key);
        if(it!=entries_.end()){bytes_-=it->second.bytes;entries_.erase(it);}
        bytes+=signature.capacity()+sizeof(CacheEntry)+128;if(bytes>budget)return;
        entries_[key]={std::move(signature),std::move(value),bytes,++clock_};bytes_+=bytes;
        while(bytes_>budget){auto oldest=std::min_element(entries_.begin(),entries_.end(),[](const auto& a,const auto& b){return a.second.used<b.second.used;});
            bytes_-=oldest->second.bytes;entries_.erase(oldest);}
    }
    void retain(const std::set<uint64_t>& ids,uint64_t budget) {
        std::lock_guard<std::mutex> lock(mutex_);
        for(auto it=entries_.begin();it!=entries_.end();){auto [stage,a,b]=it->first;
            if(!ids.count(a)||(b&&!ids.count(b))||bytes_>budget){bytes_-=it->second.bytes;it=entries_.erase(it);}else ++it;}
    }
};
template<class T> static void append_signature(std::string& key,const T* values,size_t count) {
    key.append(reinterpret_cast<const char*>(&count),sizeof(count));if(count)key.append(reinterpret_cast<const char*>(values),sizeof(T)*count);
}
template<class T> static void append_signature(std::string& key,const std::vector<T>& values) {
    append_signature(key,values.data(),values.size());
}
template<class Derived> static void append_dense(std::string& key,const Eigen::MatrixBase<Derived>& values) {
    append_signature(key,values.derived().data(),values.size());
}
}

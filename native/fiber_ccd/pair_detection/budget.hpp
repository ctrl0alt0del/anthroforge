#pragma once
namespace af_pair {
static void check_cancel(const Budget& b) {
    require(!b.cancelled->load(),"PAIR_CANCELLED");
}
static void claim_bytes(Budget& b,uint64_t amount) {
    uint64_t old=b.bytes.load();
    do { require(amount<=b.max_bytes&&old<=b.max_bytes-amount,"PAIR_RESULT_BUDGET"); }
    while(!b.bytes.compare_exchange_weak(old,old+amount));
    auto peak=b.peak.load();while(peak<old+amount&&!b.peak.compare_exchange_weak(peak,old+amount)){}
}
template<class T> static void reserve(std::vector<T>& values,size_t needed,Budget& b) {
    if(needed<=values.capacity())return;
    size_t count=std::max(needed,values.capacity()+values.capacity()/2+8);
    uint64_t available=b.max_bytes-std::min(b.bytes.load(),b.max_bytes);
    if(count*sizeof(T)>available)count=needed;
    auto previous=values.capacity()*sizeof(T);claim_bytes(b,count*sizeof(T));
    try{values.reserve(count);}catch(...){b.bytes.fetch_sub(count*sizeof(T));throw;}
    b.bytes.fetch_sub(previous);
}
static void reserve_fragment(Result& out,size_t points,Budget& budget) {
    check_cancel(budget);
    require(budget.fragments.fetch_add(1)<budget.max_fragments,"PAIR_FRAGMENT_BUDGET");
    reserve(out.fragments,out.fragments.size()+1,budget);
    reserve(out.points,out.points.size()+points,budget);
}
struct Scratch {
    Budget& budget;Result value;
    explicit Scratch(Budget& b):budget(b){}
    ~Scratch(){auto size=bytes(value);value=Result{};budget.bytes.fetch_sub(size);}
};
}

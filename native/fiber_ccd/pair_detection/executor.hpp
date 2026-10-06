#pragma once
#include <functional>
namespace af_pair {
struct Work {
    std::vector<Side> incoming;
    Settings settings;
    uint64_t generation=0;
    bool exhaustive=false;
    std::atomic<int> state{0};
    std::atomic<bool> cancelled{false};
    std::string error;
};
struct Engine {
    Session session;std::shared_ptr<Work> work;std::thread worker;
    std::shared_ptr<void> extension;
    std::function<void(Session&,std::atomic<bool>&)> pipeline;
};
struct Report { int state;uint64_t generation;double stats[16];char message[512]; };
static std::shared_ptr<Work> capture_work(const Input* inputs,int count,const Settings& settings,uint64_t generation,bool exhaustive) {
    validate_settings(settings);require(count>=0&&count<=100000&&(count==0||inputs),"PAIR_INPUT_COUNT");
    auto work=std::make_shared<Work>();work->settings=settings;work->generation=generation;work->exhaustive=exhaustive;
    std::set<uint64_t> ids;work->incoming.reserve(count);
    for(int i=0;i<count;++i){require(ids.insert(inputs[i].id).second,"PAIR_DUPLICATE_DOMAIN");work->incoming.push_back(capture(inputs[i]));}
    return work;
}
static void run(Engine& engine,const std::shared_ptr<Work>& work) {
    auto start=Clock::now();work->state=1;engine.session.published=Published{};
    try{
        require(!work->cancelled,"PAIR_CANCELLED");synchronize(engine.session,work->incoming,work->settings);
        double prepare_ms=milliseconds(start);auto result=detect(engine.session,work->generation,work->cancelled,work->exhaustive);
        result.stats[12]=prepare_ms;result.stats[13]=milliseconds(start);engine.session.published=std::move(result);
        if(engine.pipeline)engine.pipeline(engine.session,work->cancelled);
        work->state=work->cancelled?3:2;
    }catch(const std::exception& e){work->error=e.what();work->state=work->cancelled?3:4;}
    catch(...){work->error="PAIR_NATIVE_FAILURE";work->state=4;}
    if(work->state!=2){engine.session.cache.clear();engine.session.indices.clear();engine.session.sides.clear();}
}
static bool ready(const Engine* engine,uint64_t generation) {
    return engine&&engine->work&&engine->work->state==2&&!engine->work->cancelled&&
        engine->session.published.generation==generation;
}
static void stop(Engine& engine) {
    if(engine.work)engine.work->cancelled=true;
    if(engine.worker.joinable())engine.worker.join();
    engine.work.reset();
}
}
AF_EXPORT int af_pair_version() { return 1; }
AF_EXPORT void* af_pair_create() {
    try{return new af_pair::Engine();}catch(...){return nullptr;}
}
AF_EXPORT void af_pair_destroy(void* handle) {
    auto* engine=static_cast<af_pair::Engine*>(handle);if(!engine)return;
    af_pair::stop(*engine);delete engine;
}
AF_EXPORT int af_pair_submit(void* handle,const af_pair::Input* inputs,int count,const af_pair::Settings* settings,uint64_t generation,int exhaustive) {
    auto* engine=static_cast<af_pair::Engine*>(handle);if(!engine||!settings)return 1;
    if(engine->work&&engine->work->state<2)return 2;
    try{
        auto work=af_pair::capture_work(inputs,count,*settings,generation,exhaustive!=0);
        af_pair::stop(*engine);engine->pipeline={};engine->extension.reset();engine->work=work;
        engine->worker=std::thread([engine,work]{af_pair::run(*engine,work);});return 0;
    }catch(...){return 1;}
}
AF_EXPORT int af_pair_poll(void* handle,af_pair::Report* report) {
    auto* engine=static_cast<af_pair::Engine*>(handle);if(!engine||!engine->work||!report)return 1;
    const auto& work=*engine->work;*report={};report->state=work.state.load();report->generation=work.generation;
    if(report->state==2&&work.cancelled)report->state=3;
    if(report->state==2)std::copy(engine->session.published.stats,engine->session.published.stats+16,report->stats);
    if(report->state>=2)std::memcpy(report->message,work.error.data(),std::min(work.error.size(),sizeof(report->message)-1));
    return 0;
}
AF_EXPORT int af_pair_cancel(void* handle,uint64_t generation) {
    auto* engine=static_cast<af_pair::Engine*>(handle);
    if(!engine||!engine->work||engine->work->generation!=generation)return 1;
    engine->work->cancelled=true;return 0;
}
AF_EXPORT int af_pair_release(void* handle,uint64_t generation) {
    auto* engine=static_cast<af_pair::Engine*>(handle);
    if(!engine||!engine->work||engine->work->generation!=generation||engine->work->state<2)return 1;
    if(engine->worker.joinable())engine->worker.join();return 0;
}
AF_EXPORT int af_pair_summary(void* handle,uint64_t generation,af_pair::PairRecord* rows,int capacity) {
    auto* engine=static_cast<af_pair::Engine*>(handle);if(!af_pair::ready(engine,generation))return 1;
    const auto& data=engine->session.published.pairs;
    if(capacity<int(data.size())||(!rows&&!data.empty()))return 2;
    std::copy(data.begin(),data.end(),rows);return 0;
}
AF_EXPORT int af_pair_footprint(void* handle,uint64_t generation,int index,af_pair::Fragment* rows,int nf,af_pair::Point* points,int np) {
    auto* engine=static_cast<af_pair::Engine*>(handle);if(!af_pair::ready(engine,generation))return 1;
    const auto& pairs=engine->session.published.pairs;if(index<0||index>=int(pairs.size()))return 2;
    if(nf<pairs[index].count||np<pairs[index].points||(!rows&&nf)||(!points&&np))return 2;
    try{const auto& s=engine->session;auto result=af_pair::pair_geometry(s,index,engine->work->cancelled,engine->work->exhaustive);
        return af_pair::export_geometry(s,result,rows,nf,points,np);
    }catch(const std::exception& e){return std::string(e.what()).find("BUDGET")!=std::string::npos?3:2;}catch(...){return 2;}
}
AF_EXPORT int af_pair_storage_version(){return 1;}
AF_EXPORT int af_pair_storage_stats(void* handle,uint64_t generation,double* values,int count) {
    auto* engine=static_cast<af_pair::Engine*>(handle);if(!af_pair::ready(engine,generation))return 1;
    if(!values||count<4)return 2;std::copy(engine->session.published.storage,engine->session.published.storage+4,values);return 0;
}

#pragma once
#include <atomic>
#include <memory>

struct AfWarningMeshInput {
    const double* vertices; const int64_t* faces; int vertex_count,face_count,owner;
    const double* matrix; const double* inverse;
};
struct AfWarningAnchor { double point[3]; int owner; double threshold; };
struct AfWarningStatus { int state,code,rows,anchors; double elapsed_ms; };
struct AfWarningMesh {
    std::vector<double> vertices; std::vector<int64_t> faces; int owner;
    std::array<double,16> matrix,inverse;
};
struct AfWarningJob {
    uint64_t id=0; std::atomic<int> state{0}; std::atomic<bool> cancelled{false};
    int code=0; double elapsed_ms=0;
    std::vector<AfWarningMesh> meshes; std::vector<AfWarningAnchor> anchors;
    std::vector<AfContactPair> rows; std::vector<AfContactResult> stats;
};
struct AfWarningExecutor {
    std::mutex mutex; std::condition_variable changed; std::thread worker;
    std::shared_ptr<AfWarningJob> job; uint64_t next_id=1; bool stop=false;
};
using AfWarningWorld=std::unique_ptr<AfWorld,decltype(&af_delete_world)>;

static AfWarningMesh af_warning_mesh(const AfWarningMeshInput& input) {
    if(!input.vertices||!input.faces||!input.matrix||!input.inverse||input.vertex_count<1||
       input.face_count<1||input.vertex_count>10000000||input.face_count>20000000)throw std::runtime_error("invalid warning mesh");
    AfWarningMesh mesh;mesh.owner=input.owner;
    mesh.vertices.assign(input.vertices,input.vertices+size_t(input.vertex_count)*3);
    mesh.faces.assign(input.faces,input.faces+size_t(input.face_count)*3);
    std::copy(input.matrix,input.matrix+16,mesh.matrix.begin());
    std::copy(input.inverse,input.inverse+16,mesh.inverse.begin());
    for(double value:mesh.matrix)if(!std::isfinite(value))throw std::runtime_error("invalid warning transform");
    for(double value:mesh.inverse)if(!std::isfinite(value))throw std::runtime_error("invalid warning inverse");
    return mesh;
}

static std::shared_ptr<AfWarningJob> af_warning_snapshot(const AfWarningMeshInput* meshes,int count,
                                                       const AfWarningAnchor* anchors,int anchor_count) {
    if(count<0||anchor_count<0||count>100000||anchor_count>1000000||
       (count&&!meshes)||(anchor_count&&!anchors))throw std::runtime_error("invalid warning snapshot");
    auto job=std::make_shared<AfWarningJob>();job->meshes.reserve(count);
    for(int i=0;i<count;++i)job->meshes.push_back(af_warning_mesh(meshes[i]));
    if(anchor_count)job->anchors.assign(anchors,anchors+anchor_count);
    for(const auto& row:job->anchors){if(!std::isfinite(row.threshold)||row.threshold<0)throw std::runtime_error("invalid warning threshold");
        for(double value:row.point)if(!std::isfinite(value))throw std::runtime_error("invalid warning point");}
    job->stats.resize(anchor_count);return job;
}

static AfWarningWorld af_warning_world(AfWarningJob& job) {
    AfWarningWorld world(new AfWorld(),af_delete_world);
    for(const auto& mesh:job.meshes){if(job.cancelled)return AfWarningWorld(nullptr,af_delete_world);int closed=0;
        if(!af_batch_add(*world,mesh.vertices.data(),int(mesh.vertices.size()/3),mesh.faces.data(),int(mesh.faces.size()/3),
            mesh.owner,mesh.matrix.data(),mesh.inverse.data(),closed))throw std::runtime_error("invalid warning collider");}
    for(size_t i=0;i<world->items.size();++i){world->items[i].bounds.index=int(i);world->order.push_back(world->items[i].bounds);}
    if(!world->order.empty())af_build_world_bvh(*world,0,int(world->order.size()));return world;
}

static void af_warning_contacts(AfWarningJob& job,const AfWorld& world) {
    for(size_t i=0;i<job.anchors.size();++i){if(job.cancelled)return;const auto& anchor=job.anchors[i];
        Vec point=load3(anchor.point);auto batch=af_pair_rows(world,int(i),point,point,0,0,0,anchor.owner,0.,anchor.threshold);
        job.stats[i]=batch.result;job.rows.insert(job.rows.end(),batch.rows.begin(),batch.rows.end());}
    std::stable_sort(job.rows.begin(),job.rows.end(),[](const auto& a,const auto& b){
        return std::tie(a.edge,a.collider,a.face,a.factor)<std::tie(b.edge,b.collider,b.face,b.factor);});
}

static void af_warning_run(AfWarningJob& job) {
    auto started=std::chrono::steady_clock::now();job.state=1;int state=2;
    try{auto world=af_warning_world(job);if(world)af_warning_contacts(job,*world);if(job.cancelled)state=3;}
    catch(...){job.code=1;state=4;}
    job.elapsed_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    job.state=state;
}

static void af_warning_loop(AfWarningExecutor* executor) {
    while(true){std::unique_lock<std::mutex> lock(executor->mutex);
        executor->changed.wait(lock,[&]{return executor->stop||(executor->job&&executor->job->state==0);});
        if(executor->stop)return;auto job=executor->job;lock.unlock();af_warning_run(*job);}
}

static std::shared_ptr<AfWarningJob> af_warning_job(AfWarningExecutor* executor,uint64_t id) {
    if(!executor)return {};std::lock_guard<std::mutex> lock(executor->mutex);
    return executor->job&&executor->job->id==id?executor->job:nullptr;
}

AF_EXPORT int af_warning_async_version() { return 1; }

AF_EXPORT void* af_warning_async_create() {
    try{auto value=std::make_unique<AfWarningExecutor>();value->worker=std::thread(af_warning_loop,value.get());return value.release();}
    catch(...){return nullptr;}
}

AF_EXPORT int af_warning_async_submit(void* handle,const AfWarningMeshInput* meshes,int count,
                                     const AfWarningAnchor* anchors,int anchor_count,uint64_t* id) {
    if(!handle||!id)return 1;auto& executor=*static_cast<AfWarningExecutor*>(handle);
    try{auto job=af_warning_snapshot(meshes,count,anchors,anchor_count);std::lock_guard<std::mutex> lock(executor.mutex);
        if(executor.stop||executor.job)return 2;job->id=executor.next_id++;*id=job->id;executor.job=job;executor.changed.notify_one();return 0;}
    catch(...){return 1;}
}

AF_EXPORT int af_warning_async_poll(void* handle,uint64_t id,AfWarningStatus* output) {
    auto job=af_warning_job(static_cast<AfWarningExecutor*>(handle),id);if(!job||!output)return 1;
    int state=job->state.load();*output={state,0,0,int(job->anchors.size()),0.};
    if(state>=2){output->code=job->code;output->rows=int(job->rows.size());output->elapsed_ms=job->elapsed_ms;}return 0;
}

AF_EXPORT int af_warning_async_read(void* handle,uint64_t id,AfContactPair* rows,int capacity,
                                   AfContactResult* stats,int anchor_count) {
    auto job=af_warning_job(static_cast<AfWarningExecutor*>(handle),id);
    if(!job||job->state!=2||capacity<int(job->rows.size())||anchor_count!=int(job->stats.size())||
       (!job->rows.empty()&&!rows)||(!job->stats.empty()&&!stats))return 1;
    std::copy(job->rows.begin(),job->rows.end(),rows);std::copy(job->stats.begin(),job->stats.end(),stats);return 0;
}

AF_EXPORT int af_warning_async_cancel(void* handle,uint64_t id) {
    auto* executor=static_cast<AfWarningExecutor*>(handle);auto job=af_warning_job(executor,id);
    if(!job)return 1;job->cancelled=true;executor->changed.notify_one();return 0;
}

AF_EXPORT int af_warning_async_release(void* handle,uint64_t id) {
    if(!handle)return 1;auto& executor=*static_cast<AfWarningExecutor*>(handle);std::lock_guard<std::mutex> lock(executor.mutex);
    if(!executor.job||executor.job->id!=id||executor.job->state<2)return 1;executor.job.reset();return 0;
}

AF_EXPORT void af_warning_async_destroy(void* handle) {
    if(!handle)return;auto* executor=static_cast<AfWarningExecutor*>(handle);
    {std::lock_guard<std::mutex> lock(executor->mutex);executor->stop=true;if(executor->job)executor->job->cancelled=true;}
    executor->changed.notify_one();if(executor->worker.joinable())executor->worker.join();delete executor;
}

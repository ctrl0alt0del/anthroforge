#pragma once

constexpr int AF_V3_CONTACT_JOB_EDGES=32;

struct AfV3CoordinatorWork {
    int contact_jobs=0,validation_jobs=0,structural_jobs=0,ccd_broad_jobs=0,ccd_pair_jobs=0;
    std::vector<int> workers;
};

struct AfV3CoordinatorStats {
    int operations,streams,contact_jobs,validation_jobs,structural_jobs,ccd_broad_jobs,ccd_pair_jobs;
    int workers,workers_used,deterministic;
    double elapsed_ms;
};

struct AfV3CoordinatorStream { void* session=nullptr;std::vector<int> operations; };

struct AfV3Coordinator {
    AfV3Operation* jobs=nullptr;int count=0;
    std::vector<AfV3CoordinatorStream> streams;
    std::vector<int> cursors;
    std::vector<AfV3CoordinatorWork> work;
};

static int af_v3_worker() {
#ifdef _OPENMP
    return omp_get_thread_num();
#else
    return 0;
#endif
}

static int af_v3_chunks(int count,int size) {
    return count<1?0:(count+size-1)/size;
}

static void af_v3_contact_range(AfV3NativeSession& value,const AfV3MeasureOperation& row,
                                int first,int last) {
    for(int edge=first;edge<last;++edge)af_v3_fill_pair(value,edge,row.points,row.span,row.activation);
}

static void af_v3_contact_jobs(AfV3NativeSession& value,const AfV3MeasureOperation& row,
                               AfV3CoordinatorWork& work) {
    int count=int(value.first.size()),jobs=af_v3_chunks(count,AF_V3_CONTACT_JOB_EDGES);
    work.contact_jobs=jobs;work.workers.assign(2*jobs,-1);
#pragma omp taskgroup
    for(int job=0;job<jobs;++job){int first=job*AF_V3_CONTACT_JOB_EDGES,last=std::min(count,first+AF_V3_CONTACT_JOB_EDGES);
#pragma omp task firstprivate(job,first,last) shared(value,row,work)
        {work.workers[job]=af_v3_worker();af_v3_contact_range(value,row,first,last);}}
}

static void af_v3_validation_range(AfV3NativeSession& value,const AfV3MeasureOperation& row,
                                   int first,int last) {
    for(int edge=first;edge<last;++edge)value.validations[edge]=af_world_validation_row(*value.world,
        load3(row.points+3*edge),load3(row.points+3*edge+3),value.first[edge],value.second[edge],
        row.span,row.threshold);
}

static void af_v3_validation_jobs(AfV3NativeSession& value,const AfV3MeasureOperation& row,
                                  AfV3CoordinatorWork& work) {
    int count=int(value.first.size()),jobs=af_v3_chunks(count,AF_V3_CONTACT_JOB_EDGES),offset=work.contact_jobs;
    work.validation_jobs=jobs;value.validations.resize(count);
#pragma omp taskgroup
    for(int job=0;job<jobs;++job){int first=job*AF_V3_CONTACT_JOB_EDGES,last=std::min(count,first+AF_V3_CONTACT_JOB_EDGES);
#pragma omp task firstprivate(job,first,last,offset) shared(value,row,work)
        {work.workers[offset+job]=af_v3_worker();af_v3_validation_range(value,row,first,last);}}
}

static int af_v3_coordinator_measure(AfV3MeasureOperation& row,AfV3CoordinatorWork& work) {
    auto& value=*static_cast<AfV3NativeSession*>(row.session);value.contacts.clear();
    af_v3_contact_jobs(value,row,work);af_v3_merge_contacts(value,row.contacts);
    row.code=af_v3_write_contacts(value,row.output,row.capacity,row.contacts);
    af_v3_validation_jobs(value,row,work);af_v3_write_validation(value,row.clear,row.blockers,row.minima,row.validation);
    ++value.stats.contact_queries;++value.stats.validations;++value.stats.measures;
    return row.code<0&&row.code!=-2?row.code:0;
}

static void af_v3_coord_edge_rows(const AfV3NativeSession& value,const AfV3BatchSweepJob& row,
                                  int edge,std::vector<AfV3SweepRow>& output,int& candidates) {
    std::vector<int> faces;if(!value.snapshot->nodes.empty())collect_candidates(*value.snapshot,0,
        moving_bounds(row.source,row.target,value.edges.data()+2*edge,row.clearance),faces);
    std::sort(faces.begin(),faces.end());candidates=int(faces.size());
    for(int face:faces)if(!af_v3_sweep_exempt(value,edge,face))
        output.push_back(af_v3_sweep_row(value,row.source,row.target,edge,face));
}

static void af_v3_coord_broad_range(const AfV3NativeSession& value,const AfV3BatchSweepJob& row,
                                    int first,int last,std::vector<std::vector<AfV3SweepRow>>& rows,
                                    std::vector<int>& candidates) {
    for(int edge=first;edge<last;++edge)af_v3_coord_edge_rows(value,row,edge,rows[edge],candidates[edge]);
}

static void af_v3_coord_broad_jobs(const AfV3NativeSession& value,const AfV3BatchSweepJob& row,
                                   std::vector<std::vector<AfV3SweepRow>>& rows,
                                   std::vector<int>& candidates,AfV3CoordinatorWork& work) {
    int count=int(value.first.size()),jobs=af_v3_chunks(count,AF_V3_CONTACT_JOB_EDGES);
    work.ccd_broad_jobs=jobs;work.workers.assign(jobs,-1);
#pragma omp taskgroup
    for(int job=0;job<jobs;++job){int first=job*AF_V3_CONTACT_JOB_EDGES,last=std::min(count,first+AF_V3_CONTACT_JOB_EDGES);
#pragma omp task firstprivate(job,first,last) shared(value,row,rows,candidates,work)
        {work.workers[job]=af_v3_worker();af_v3_coord_broad_range(value,row,first,last,rows,candidates);}}
}

static void af_v3_coord_merge_sweep(AfV3NativeSession& value,
                                    const std::vector<std::vector<AfV3SweepRow>>& rows) {
    value.sweep_rows.clear();for(const auto& edge:rows)value.sweep_rows.insert(value.sweep_rows.end(),edge.begin(),edge.end());
    value.stats.sweep_capacity=std::max(value.stats.sweep_capacity,int(value.sweep_rows.capacity()));
}

static void af_v3_coord_pair_range(const AfV3NativeSession& value,const AfV3BatchSweepJob& row,
                                   int first,int last,std::vector<Sweep>& results) {
    for(int pair=first;pair<last;++pair)results[pair]=af_v3_sweep_pair(
        value.sweep_rows[pair],1.0,row.clearance,row.tolerance,row.budget);
}

static void af_v3_coord_pair_jobs(const AfV3NativeSession& value,const AfV3BatchSweepJob& row,
                                  std::vector<Sweep>& results,AfV3CoordinatorWork& work) {
    int count=int(value.sweep_rows.size()),jobs=af_v3_chunks(count,AF_V3_CCD_JOB_PAIRS),offset=work.ccd_broad_jobs;
    work.ccd_pair_jobs=jobs;work.workers.resize(offset+jobs,-1);
#pragma omp taskgroup
    for(int job=0;job<jobs;++job){int first=job*AF_V3_CCD_JOB_PAIRS,last=std::min(count,first+AF_V3_CCD_JOB_PAIRS);
#pragma omp task firstprivate(job,first,last,offset) shared(value,row,results,work)
        {work.workers[offset+job]=af_v3_worker();af_v3_coord_pair_range(value,row,first,last,results);}}
}

static void af_v3_coord_absorb(MeshSweep& mesh,const Sweep& pair,int index) {
    ++mesh.tested;mesh.intervals+=pair.intervals;mesh.valid&=pair.valid;mesh.possible|=pair.possible;
    if(pair.reason==4)mesh.reason=4;
    if(pair.safe<mesh.safe){mesh.safe=pair.safe;mesh.limiting=index;}
}

static MeshSweep af_v3_coord_reduce(const std::vector<Sweep>& rows) {
    MeshSweep output{1.0,0,1,0,0,0,-1};
    for(int index=0;index<int(rows.size());++index){af_v3_coord_absorb(output,rows[index],index);
        if(!output.valid||output.safe<=0.0)break;}
    output.reason=!output.valid?2:output.reason==4?4:output.possible?3:0;return output;
}

static void af_v3_coord_limiter(const AfV3NativeSession& value,AfV3BatchSweepJob& row) {
    if(row.result.limiting<0)return;const auto& hit=value.sweep_rows[row.result.limiting];
    row.edge=hit.edge;row.face=hit.triangle;
}

static int af_v3_coordinator_sweep(AfV3BatchSweepJob& row,AfV3CoordinatorWork& work) {
    auto& value=*static_cast<AfV3NativeSession*>(row.session);int edges=int(value.first.size());
    std::vector<std::vector<AfV3SweepRow>> batches(edges);std::vector<int> candidates(edges,0);
    af_v3_coord_broad_jobs(value,row,batches,candidates,work);af_v3_coord_merge_sweep(value,batches);
    std::vector<Sweep> results(value.sweep_rows.size());af_v3_coord_pair_jobs(value,row,results,work);
    row.result=af_v3_coord_reduce(results);row.candidates=0;for(int count:candidates)row.candidates+=count;
    row.pairs=int(results.size());row.edge=row.face=-1;af_v3_coord_limiter(value,row);++value.stats.sweeps;
    return 0;
}

static int af_v3_coord_run(AfV3Operation& job,AfV3CoordinatorWork& work) {
    if(job.kind==AF_V3_MEASURE)return af_v3_coordinator_measure(*static_cast<AfV3MeasureOperation*>(job.payload),work);
    if(job.kind==AF_V3_STRUCTURAL){work.structural_jobs=1;return af_v3_run_structural(*static_cast<AfV3StructuralOperation*>(job.payload));}
    if(job.kind==AF_V3_SWEEP)return af_v3_coordinator_sweep(*static_cast<AfV3BatchSweepJob*>(job.payload),work);
    return 1;
}

static std::vector<AfV3CoordinatorStream> af_v3_coord_streams(AfV3Operation* jobs,int count) {
    std::vector<AfV3CoordinatorStream> output;
    for(int index=0;index<count;++index){void* session=af_v3_operation_session(jobs[index]);auto found=std::find_if(
        output.begin(),output.end(),[session](const auto& row){return row.session==session;});
        if(found==output.end()){output.push_back({session,{}});found=output.end()-1;}found->operations.push_back(index);}
    return output;
}

static bool af_v3_coord_expired(const std::chrono::steady_clock::time_point& deadline,bool bounded) {
    return bounded&&std::chrono::steady_clock::now()>=deadline;
}

static void af_v3_coord_stream_step(AfV3Coordinator& value,int stream,
                                    const std::chrono::steady_clock::time_point& deadline,bool bounded) {
    auto& cursor=value.cursors[stream];const auto& indices=value.streams[stream].operations;
    do{int index=indices[cursor++];auto started=std::chrono::steady_clock::now();
        value.jobs[index].worker=af_v3_worker();value.jobs[index].status=af_v3_coord_run(value.jobs[index],value.work[index]);
        value.jobs[index].elapsed_ms=std::chrono::duration<double,std::milli>(
            std::chrono::steady_clock::now()-started).count();}
    while(cursor<int(indices.size())&&!af_v3_coord_expired(deadline,bounded));
}

static void af_v3_coord_round(AfV3Coordinator& value,double budget_ms,int workers) {
    bool bounded=std::isfinite(budget_ms);auto deadline=std::chrono::steady_clock::now()+
        std::chrono::microseconds(int64_t(1000.0*std::max(0.0,budget_ms)));
#pragma omp parallel num_threads(workers)
#pragma omp single
    {for(int index=0;index<int(value.streams.size());++index)if(value.cursors[index]<int(value.streams[index].operations.size()))
#pragma omp task firstprivate(index) shared(value,deadline,bounded)
        af_v3_coord_stream_step(value,index,deadline,bounded);
#pragma omp taskwait
    }
}

static int af_v3_coord_workers(const std::vector<AfV3CoordinatorWork>& work) {
    std::vector<int> values;for(const auto& row:work)for(int worker:row.workers)if(worker>=0)values.push_back(worker);
    std::sort(values.begin(),values.end());return int(std::unique(values.begin(),values.end())-values.begin());
}

static int af_v3_coord_completed(const AfV3Coordinator& value) {
    int output=0;for(int cursor:value.cursors)output+=cursor;return output;
}

static bool af_v3_coord_done(const AfV3Coordinator& value) {
    return af_v3_coord_completed(value)>=value.count;
}

static AfV3Coordinator* af_v3_coord_create(AfV3Operation* jobs,int count) {
    if(!jobs||count<1)return nullptr;auto* value=new AfV3Coordinator();value->jobs=jobs;value->count=count;
    value->streams=af_v3_coord_streams(jobs,count);value->cursors.assign(value->streams.size(),0);
    value->work.resize(count);return value->streams.empty()?(delete value,nullptr):value;
}

static AfV3CoordinatorStats af_v3_coord_stats(int operations,int streams,int workers,double elapsed,
                                              const std::vector<AfV3CoordinatorWork>& work) {
    AfV3CoordinatorStats out{operations,streams,0,0,0,0,0,workers,af_v3_coord_workers(work),1,elapsed};
    for(const auto& row:work){out.contact_jobs+=row.contact_jobs;out.validation_jobs+=row.validation_jobs;
        out.structural_jobs+=row.structural_jobs;out.ccd_broad_jobs+=row.ccd_broad_jobs;out.ccd_pair_jobs+=row.ccd_pair_jobs;}
    return out;
}

AF_EXPORT int af_v3_coordinator_execute(AfV3Operation* jobs,int count,AfV3CoordinatorStats* stats) {
    if(!stats)return 1;auto* value=af_v3_coord_create(jobs,count);if(!value)return 1;
    auto started=std::chrono::steady_clock::now();af_v3_coord_round(*value,INFINITY,af_requested_workers);
    double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    *stats=af_v3_coord_stats(count,int(value->streams.size()),af_requested_workers,ms,value->work);
    bool valid=std::all_of(jobs,jobs+count,[](const auto& row){return row.status==0;});delete value;
    return valid?0:2;
}

AF_EXPORT void* af_v3_coordinator_create(AfV3Operation* jobs,int count) {
    return af_v3_coord_create(jobs,count);
}

AF_EXPORT void af_v3_coordinator_destroy(void* handle) {
    delete static_cast<AfV3Coordinator*>(handle);
}

AF_EXPORT int af_v3_coordinator_step(void* handle,double budget_ms,AfV3CoordinatorStats* stats,int* done) {
    if(!handle||!stats||!done||budget_ms<0.0)return 1;auto& value=*static_cast<AfV3Coordinator*>(handle);
    auto started=std::chrono::steady_clock::now();af_v3_coord_round(value,budget_ms,af_requested_workers);
    double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    *done=af_v3_coord_done(value);*stats=af_v3_coord_stats(af_v3_coord_completed(value),
        int(value.streams.size()),af_requested_workers,ms,value.work);return 0;
}

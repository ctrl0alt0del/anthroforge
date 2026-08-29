#pragma once

enum AfV3OperationKind { AF_V3_MEASURE=1,AF_V3_STRUCTURAL=2,AF_V3_SWEEP=3 };

struct AfV3MeasureOperation {
    void* session;const double* points;double span,activation,threshold;
    AfContactPair* output;int capacity,code;AfContactResult contacts;
    int* clear;int* blockers;double* minima;AfBatchResult validation;
};

struct AfV3StructuralOperation {
    void* session;const double *d,*l1,*l2,*rhs;const int64_t* edges;
    const double *factors,*normals;int contacts;const int64_t* pins;
    const double* targets;int pin_count,count;double *base,*responses;AfBlockResult result;
};

struct AfV3Operation {
    int kind,status,worker,ordinal;double elapsed_ms;void* payload;
};

struct AfV3OperationStats {
    int submitted,completed,workers,workers_used,measures,structurals,sweeps;
    double elapsed_ms;
};

static void* af_v3_operation_session(const AfV3Operation& job) {
    if(job.kind==AF_V3_MEASURE)return static_cast<AfV3MeasureOperation*>(job.payload)->session;
    if(job.kind==AF_V3_STRUCTURAL)return static_cast<AfV3StructuralOperation*>(job.payload)->session;
    if(job.kind==AF_V3_SWEEP)return static_cast<AfV3BatchSweepJob*>(job.payload)->session;
    return nullptr;
}

static int af_v3_run_measure(AfV3MeasureOperation& row) {
    row.code=af_v3_session_measure(row.session,row.points,row.span,row.activation,row.threshold,
        row.output,row.capacity,&row.contacts,row.clear,row.blockers,row.minima,&row.validation);
    return row.code<0&&row.code!=-2?row.code:0;
}

static int af_v3_run_structural(AfV3StructuralOperation& row) {
    return af_v3_session_structural_responses(row.session,row.d,row.l1,row.l2,row.rhs,row.edges,
        row.factors,row.normals,row.contacts,row.pins,row.targets,row.pin_count,row.count,
        row.base,row.responses,&row.result);
}

static int af_v3_run_operation(AfV3Operation& job) {
    if(job.kind==AF_V3_MEASURE)return af_v3_run_measure(*static_cast<AfV3MeasureOperation*>(job.payload));
    if(job.kind==AF_V3_STRUCTURAL)return af_v3_run_structural(*static_cast<AfV3StructuralOperation*>(job.payload));
    if(job.kind==AF_V3_SWEEP){af_v3_batch_run(*static_cast<AfV3BatchSweepJob*>(job.payload));
        return static_cast<AfV3BatchSweepJob*>(job.payload)->status;}
    return 1;
}

static bool af_v3_operation_inputs(AfV3Operation* jobs,int count,AfV3OperationStats* stats) {
    if(!jobs||!stats||count<1)return false;
    for(int index=0;index<count;++index){void* session=af_v3_operation_session(jobs[index]);
        if(!session||!jobs[index].payload)return false;for(int prior=0;prior<index;++prior)
            if(session==af_v3_operation_session(jobs[prior]))return false;}
    return true;
}

static void af_v3_execute_operation(AfV3Operation& job) {
    auto started=std::chrono::steady_clock::now();
#ifdef _OPENMP
    job.worker=omp_get_thread_num();
#else
    job.worker=0;
#endif
    job.status=af_v3_run_operation(job);job.elapsed_ms=std::chrono::duration<double,std::milli>(
        std::chrono::steady_clock::now()-started).count();
}

static int af_v3_workers_used(const AfV3Operation* jobs,int count) {
    std::vector<int> workers;for(int i=0;i<count;++i)workers.push_back(jobs[i].worker);
    std::sort(workers.begin(),workers.end());return int(std::unique(workers.begin(),workers.end())-workers.begin());
}

static AfV3OperationStats af_v3_operation_stats(const AfV3Operation* jobs,int count,int workers,double ms) {
    AfV3OperationStats out{count,0,workers,af_v3_workers_used(jobs,count),0,0,0,ms};
    for(int i=0;i<count;++i){out.completed+=jobs[i].status==0;out.measures+=jobs[i].kind==AF_V3_MEASURE;
        out.structurals+=jobs[i].kind==AF_V3_STRUCTURAL;out.sweeps+=jobs[i].kind==AF_V3_SWEEP;}
    return out;
}

AF_EXPORT int af_v3_execute_operations(AfV3Operation* jobs,int count,AfV3OperationStats* stats) {
    if(!af_v3_operation_inputs(jobs,count,stats))return 1;auto started=std::chrono::steady_clock::now();
    int workers=count>=af_requested_workers?af_requested_workers:1;
#pragma omp parallel for schedule(dynamic,1) if(workers>1) num_threads(workers)
    for(int index=0;index<count;++index)af_v3_execute_operation(jobs[index]);
    double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    *stats=af_v3_operation_stats(jobs,count,workers,ms);return stats->completed==count?0:2;
}

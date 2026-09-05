#pragma once

struct AfV3BatchSweepJob {
    void* session;
    const double* source;
    const double* target;
    double clearance,tolerance;
    int budget,status,candidates,pairs,edge,face;
    double elapsed_ms;
    MeshSweep result;
};

struct AfV3BatchStats { int submitted,completed,workers; double elapsed_ms; };

static bool af_v3_batch_job_valid(const AfV3BatchSweepJob& job) {
    return job.session&&job.source&&job.target&&job.clearance>=0.0&&
           job.tolerance>0.0&&job.budget>0;
}

static void af_v3_batch_run(AfV3BatchSweepJob& job) {
    job.edge=job.face=-1;auto started=std::chrono::steady_clock::now();
    job.status=af_v3_session_safe_step(job.session,job.source,job.target,
        job.clearance,job.tolerance,job.budget,&job.result,&job.candidates,
        &job.pairs,&job.edge,&job.face);
    job.elapsed_ms=std::chrono::duration<double,std::milli>(
        std::chrono::steady_clock::now()-started).count();
}

static bool af_v3_batch_inputs(AfV3BatchSweepJob* jobs,int count,AfV3BatchStats* stats) {
    if(!jobs||!stats||count<1)return false;
    for(int index=0;index<count;++index){if(!af_v3_batch_job_valid(jobs[index]))return false;
        for(int prior=0;prior<index;++prior)if(jobs[prior].session==jobs[index].session)return false;}
    return true;
}

AF_EXPORT int af_v3_batch_safe_steps(AfV3BatchSweepJob* jobs,int count,AfV3BatchStats* stats) {
    if(!af_v3_batch_inputs(jobs,count,stats))return 1;
    auto started=std::chrono::steady_clock::now();int workers=af_task_workers(count);
#pragma omp parallel for schedule(dynamic,1) if(workers>1) num_threads(workers)
    for(int index=0;index<count;++index)af_v3_batch_run(jobs[index]);
    double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    int complete=0;for(int index=0;index<count;++index)complete+=jobs[index].status==0;
    *stats={count,complete,workers,ms};return complete==count?0:2;
}

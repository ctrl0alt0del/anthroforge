#pragma once

struct AfV3SessionStats {
    uint64_t measures,contact_queries,validations,structural_solves,sweeps;
    int edge_capacity,contact_capacity,sweep_capacity;
};

struct AfV3CcdStats {
    uint64_t serial_sweeps,indexed_sweeps,indexed_clear,indexed_fallbacks;
    uint64_t serial_clear,candidate_pairs,indexed_pairs,serial_tests,serial_intervals;
};

struct AfV3BroadCache { Bounds fat{};std::vector<int> faces;int valid=0; };
static constexpr int AF_V3_BROAD_CACHE_MARGIN=2;
static constexpr int AF_V3_BROAD_CACHE_MIN_PAIRS=512;

struct AfV3SweepRow { Vec start[2],end[2],face[3]; int edge,triangle; };

struct AfV3NativeSession {
    const AfWorld* world=nullptr;
    std::vector<int64_t> edges;
    std::vector<int> first,second,only,skip;
    std::vector<AfPairRows> pair_batches;
    std::vector<AfContactPair> contacts;
    std::vector<AfValidationRow> validations;
    std::vector<AfMat3> diagonal,lower1,lower2;
    std::vector<Vec> rhs,base,response;
    std::vector<char> pinned;
    AfBlockFactor factor;
    const TriangleSnapshot* snapshot=nullptr;
    std::vector<int> face_owners;
    std::vector<AfV3SweepRow> sweep_rows;
    std::vector<AfV3BroadCache> broad_cache;
    int clear_sweep_streak=0;
    uint64_t last_pairs=0,last_intervals=0;
    AfV3CcdStats ccd_stats{};
    AfV3SessionStats stats{};
};

static bool af_v3_owner_inputs(const int* first,const int* second,int count) {
    return first&&second&&count>0;
}

static void af_v3_init_edges(AfV3NativeSession& value,const int* first,const int* second,int count) {
    value.edges.resize(2*count);value.first.assign(first,first+count);value.second.assign(second,second+count);
    value.only.assign(count,0);value.skip.assign(count,0);value.pair_batches.resize(count);
    value.broad_cache.resize(count);
    for(int edge=0;edge<count;++edge)value.edges[2*edge]=edge,value.edges[2*edge+1]=edge+1;
    value.stats.edge_capacity=count;
}

AF_EXPORT void* af_v3_session_create(void* world,const int* first,const int* second,int edge_count) {
    if(!world||!af_v3_owner_inputs(first,second,edge_count))return nullptr;
    auto* value=new AfV3NativeSession();value->world=static_cast<const AfWorld*>(world);
    af_v3_init_edges(*value,first,second,edge_count);return value;
}

AF_EXPORT void af_v3_session_destroy(void* handle) {
    delete static_cast<AfV3NativeSession*>(handle);
}

AF_EXPORT int af_v3_session_attach_snapshot(void* handle,void* snapshot,const int* owners,int count) {
    if(!handle||!snapshot||!owners||count<0)return 1;auto& value=*static_cast<AfV3NativeSession*>(handle);
    auto* mesh=static_cast<const TriangleSnapshot*>(snapshot);
    if(count!=int(mesh->triangles.size()/3))return 1;value.snapshot=mesh;value.face_owners.assign(owners,owners+count);
    for(auto& cache:value.broad_cache){cache.faces.clear();cache.valid=0;}value.last_pairs=value.last_intervals=0;return 0;
}

static void af_v3_fill_pair(AfV3NativeSession& value,int edge,const double* points,double span,double threshold) {
    auto& batch=value.pair_batches[edge];batch.rows.clear();batch.result={0,0,0,0,INFINITY};
    Vec a=load3(points+3*edge),b=load3(points+3*edge+3);
    af_collect_edge_contacts(*value.world,edge,a,b,value.first[edge],value.second[edge],0,0,
                             span,threshold,batch.rows,batch.result);
}

static void af_v3_collect_contacts(AfV3NativeSession& value,const double* points,double span,double threshold) {
    int count=int(value.first.size());value.contacts.clear();
#pragma omp parallel for schedule(static) if(af_parallel_batch(count)) num_threads(af_parallel_workers(count))
    for(int edge=0;edge<count;++edge)af_v3_fill_pair(value,edge,points,span,threshold);
}

static void af_v3_merge_contacts(AfV3NativeSession& value,AfContactResult& result) {
    result={0,0,0,0,INFINITY};
    for(auto& batch:value.pair_batches)af_merge_pair_rows(value.contacts,result,batch);
    std::stable_sort(value.contacts.begin(),value.contacts.end(),[](const auto& a,const auto& b){
        return std::tie(a.edge,a.collider,a.face,a.factor)<std::tie(b.edge,b.collider,b.face,b.factor);});
    result.active=int(value.contacts.size());for(const auto& row:value.contacts)result.minimum=std::min(result.minimum,row.distance);
}

static int af_v3_write_contacts(AfV3NativeSession& value,AfContactPair* output,int capacity,AfContactResult& result) {
    value.stats.contact_capacity=std::max(value.stats.contact_capacity,int(value.contacts.capacity()));
    if(output&&capacity<int(value.contacts.size()))return -2;
    if(output)std::copy(value.contacts.begin(),value.contacts.end(),output);
    return int(value.contacts.size());
}

AF_EXPORT int af_v3_session_copy_contacts(void* handle,AfContactPair* output,int capacity) {
    if(!handle||!output||capacity<0)return -1;auto& value=*static_cast<AfV3NativeSession*>(handle);
    if(capacity<int(value.contacts.size()))return -2;std::copy(value.contacts.begin(),value.contacts.end(),output);
    return int(value.contacts.size());
}

AF_EXPORT int af_v3_session_contacts(void* handle,const double* points,double span,double threshold,
                                      AfContactPair* output,int capacity,AfContactResult* result) {
    if(!handle||!points||!result||capacity<0)return -1;auto& value=*static_cast<AfV3NativeSession*>(handle);
    af_v3_collect_contacts(value,points,span,threshold);af_v3_merge_contacts(value,*result);
    ++value.stats.contact_queries;return af_v3_write_contacts(value,output,capacity,*result);
}

static void af_v3_collect_validation(AfV3NativeSession& value,const double* points,double span,double threshold) {
    int count=int(value.first.size());value.validations.resize(count);
#pragma omp parallel for schedule(static) if(af_parallel_batch(count)) num_threads(af_parallel_workers(count))
    for(int edge=0;edge<count;++edge)value.validations[edge]=af_world_validation_row(*value.world,
        load3(points+3*edge),load3(points+3*edge+3),value.first[edge],value.second[edge],span,threshold);
}

static void af_v3_write_validation(const AfV3NativeSession& value,int* clear,int* blockers,double* minima,
                                    AfBatchResult& result) {
    result={0,0,0,0,INFINITY};
    for(int edge=0;edge<int(value.validations.size());++edge)
        af_store_validation(value.validations[edge],edge,clear,blockers,minima,result);
}

AF_EXPORT int af_v3_session_validate(void* handle,const double* points,double span,double threshold,
                                      int* clear,int* blockers,double* minima,AfBatchResult* result) {
    if(!handle||!points||!clear||!blockers||!minima||!result)return 1;
    auto& value=*static_cast<AfV3NativeSession*>(handle);af_v3_collect_validation(value,points,span,threshold);
    af_v3_write_validation(value,clear,blockers,minima,*result);++value.stats.validations;return 0;
}

AF_EXPORT int af_v3_session_measure(void* handle,const double* points,double span,double activation,
                                     double threshold,AfContactPair* output,int capacity,AfContactResult* contacts,
                                     int* clear,int* blockers,double* minima,AfBatchResult* validation) {
    int count=af_v3_session_contacts(handle,points,span,activation,output,capacity,contacts);
    if(count<0&&count!=-2)return count;if(af_v3_session_validate(handle,points,span,threshold,clear,blockers,minima,validation))return -1;
    auto& value=*static_cast<AfV3NativeSession*>(handle);++value.stats.measures;return count;
}

static void af_v3_load_system(AfV3NativeSession& value,const double* d,const double* l1,
                              const double* l2,const double* source,int count) {
    value.diagonal.resize(count);value.lower1.resize(count);value.lower2.resize(count);value.rhs.resize(count);
    for(int i=0;i<count;++i){value.diagonal[i]=af_midentity(d[i]);value.lower1[i]=af_midentity(l1[i]);
        value.lower2[i]=af_midentity(l2[i]);value.rhs[i]=load3(source+3*i);}
}

static bool af_v3_factor(AfV3NativeSession& value,int count) {
    value.factor.low=INFINITY;value.factor.high=0.0;
    return af_factor_blocks(value.factor,reinterpret_cast<double*>(value.diagonal.data()),
        reinterpret_cast<double*>(value.lower1.data()),reinterpret_cast<double*>(value.lower2.data()),count);
}

static void af_v3_solve_into(AfV3NativeSession& value,const std::vector<Vec>& source,std::vector<Vec>& output) {
    output=source;
    for(int i=0;i<int(output.size());++i){if(i)output[i]=sub(output[i],af_mvec(value.factor.l1[i],output[i-1]));
        if(i>1)output[i]=sub(output[i],af_mvec(value.factor.l2[i],output[i-2]));}
    for(int i=0;i<int(output.size());++i)output[i]=af_mvec(value.factor.inv[i],output[i]);af_block_backward(value.factor,output);
}

static void af_v3_write_response(AfV3NativeSession& value,int edge,double factor,Vec normal,double* output) {
    std::fill(value.response.begin(),value.response.end(),Vec{0,0,0});
    if(!value.pinned[edge])value.response[edge]=mul(normal,1.0-factor);
    if(!value.pinned[edge+1])value.response[edge+1]=mul(normal,factor);
    af_v3_solve_into(value,value.response,value.base);af_write_vectors(value.base,output);
}

static bool af_v3_prepare_factor(AfV3NativeSession& value,const int64_t* pins,const double* targets,
                                 int pin_count,int count) {
    value.pinned.assign(count,0);for(int i=0;i<pin_count;++i)value.pinned[pins[i]]=1;
    af_apply_pins(value.diagonal,value.lower1,value.lower2,value.rhs,pins,targets,pin_count);
    value.response.assign(count,Vec{0,0,0});return af_v3_factor(value,count);
}

AF_EXPORT int af_v3_session_structural_responses(void* handle,const double* d,const double* l1,
        const double* l2,const double* rhs,const int64_t* edges,const double* factors,const double* normals,
        int contacts,const int64_t* pins,const double* targets,int pin_count,int count,double* base_output,
        double* responses,AfBlockResult* result) {
    if(!handle||!d||!l1||!l2||!rhs||!base_output||!responses||!result||!af_contact_inputs(count,edges,contacts,pins,pin_count))return 1;
    auto started=std::chrono::steady_clock::now();auto& value=*static_cast<AfV3NativeSession*>(handle);af_v3_load_system(value,d,l1,l2,rhs,count);
    if(!af_v3_prepare_factor(value,pins,targets,pin_count,count)){*result={INFINITY,0,0,0,count,0};return 0;}
    af_v3_solve_into(value,value.rhs,value.base);af_write_vectors(value.base,base_output);
    for(int i=0;i<contacts;++i)af_v3_write_response(value,int(edges[i]),factors[i],load3(normals+3*i),responses+3*count*i);
    double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();++value.stats.structural_solves;
    *result={value.factor.high/std::max(value.factor.low,eps()),0,0,elapsed,count,1};return 0;
}

static bool af_v3_sweep_exempt(const AfV3NativeSession& value,int edge,int face) {
    int owner=value.face_owners[face];return owner!=0&&(owner==value.first[edge]||owner==value.second[edge]);
}

static AfV3SweepRow af_v3_sweep_row(const AfV3NativeSession& value,const double* source,
                                    const double* target,int edge,int face) {
    AfV3SweepRow row{};row.edge=edge;row.triangle=face;
    row.start[0]=load3(source+3*edge);row.start[1]=load3(source+3*edge+3);
    row.end[0]=load3(target+3*edge);row.end[1]=load3(target+3*edge+3);
    snapshot_face(*value.snapshot,face,row.face);return row;
}

static Bounds af_v3_fat_bounds(Bounds value,double padding) {
    double margin=AF_V3_BROAD_CACHE_MARGIN*padding;
    for(int axis=0;axis<3;++axis)value.lo[axis]-=margin,value.hi[axis]+=margin;
    return value;
}

static bool af_v3_contains(const Bounds& outer,const Bounds& inner) {
    for(int axis=0;axis<3;++axis)if(inner.lo[axis]<outer.lo[axis]||inner.hi[axis]>outer.hi[axis])return false;
    return true;
}

static void af_v3_sweep_faces(AfV3NativeSession& value,int edge,const Bounds& exact,
                              double padding,std::vector<int>& output) {
    if(value.last_pairs<AF_V3_BROAD_CACHE_MIN_PAIRS){collect_candidates(*value.snapshot,0,exact,output);
        std::sort(output.begin(),output.end());return;}
    auto& cache=value.broad_cache[edge];if(!cache.valid||!af_v3_contains(cache.fat,exact)){
        cache.fat=af_v3_fat_bounds(exact,padding);cache.faces.clear();
        collect_candidates(*value.snapshot,0,cache.fat,cache.faces);std::sort(cache.faces.begin(),cache.faces.end());cache.valid=1;}
    for(int face:cache.faces)if(bounds_overlap(exact,value.snapshot->indexed_faces[size_t(face)]))output.push_back(face);
}

static void af_v3_build_sweep(AfV3NativeSession& value,const double* source,const double* target,
                              double padding,int& candidates) {
    value.sweep_rows.clear();candidates=0;
    for(int edge=0;edge<int(value.first.size());++edge){std::vector<int> faces;
        Bounds exact=moving_bounds(source,target,value.edges.data()+2*edge,padding);
        if(!value.snapshot->nodes.empty())af_v3_sweep_faces(value,edge,exact,padding,faces);
        candidates+=int(faces.size());for(int face:faces)if(!af_v3_sweep_exempt(value,edge,face))
            value.sweep_rows.push_back(af_v3_sweep_row(value,source,target,edge,face));}
    value.stats.sweep_capacity=std::max(value.stats.sweep_capacity,int(value.sweep_rows.capacity()));
}

static Sweep af_v3_sweep_pair(const AfV3SweepRow& row,double scale,double clearance,
                              double tolerance,int budget) {
    Vec end[2]={add(row.start[0],mul(sub(row.end[0],row.start[0]),scale)),
                add(row.start[1],mul(sub(row.end[1],row.start[1]),scale))};
    Context c{row.start[0],row.start[1],end[0],end[1],{row.face[0],row.face[1],row.face[2]},clearance,0.0,0.0};
    c.speed=std::max(norm(sub(c.a1,c.a0)),norm(sub(c.b1,c.b0)));double size=1.0;
    for(const Vec& p:{c.a0,c.b0,c.a1,c.b1,c.t[0],c.t[1],c.t[2]})for(double v:{p.x,p.y,p.z})size=std::max(size,std::abs(v));c.guard=eps()*size;
    double initial=distance_at(c,0.0);if(initial<=clearance+c.guard)return result(c,0.0,0.0,initial,1,0,0,2);
    if(!bounds_overlap(c)||c.speed<=c.guard)return result(c,1.0,1.0,initial,0,1,0,1);return subdivide(c,initial,tolerance,budget);
}

static MeshSweep af_v3_serial_batch(const AfV3NativeSession& value,int first,int last,double scale,
                                    double clearance,double tolerance,int budget) {
    MeshSweep output{1.0,0,1,0,0,0,-1};
    for(int index=first;index<last;++index){auto pair=af_v3_sweep_pair(
        value.sweep_rows[index],scale*output.safe,clearance,tolerance,budget);
        if(!absorb_mesh(output,pair,index-first))break;}
    output.reason=!output.valid?2:output.reason==4?4:output.possible?3:0;return output;
}

static void af_v3_absorb_serial(MeshSweep& output,const MeshSweep& row) {
    output.safe*=row.safe;output.possible|=row.possible;output.valid&=row.valid;
    output.tested+=row.tested;output.intervals+=row.intervals;if(row.reason==4)output.reason=4;
}

static MeshSweep af_v3_serial_sweep(const AfV3NativeSession& value,double clearance,double tolerance,
                                    int budget,int& edge,int& face) {
    MeshSweep output{1.0,0,1,0,0,0,-1};int count=int(value.sweep_rows.size());
    for(int first=0;first<count;first+=AF_V3_CCD_JOB_PAIRS){int last=std::min(count,first+AF_V3_CCD_JOB_PAIRS);
        auto row=af_v3_serial_batch(value,first,last,output.safe,clearance,tolerance,budget);
        if(row.limiting>=0){const auto& hit=value.sweep_rows[first+row.limiting];edge=hit.edge;face=hit.triangle;}
        af_v3_absorb_serial(output,row);if(!output.valid||output.reason==4)break;}
    output.reason=!output.valid?2:output.reason==4?4:output.possible?3:0;return output;
}

static void af_v3_indexed_rows(const AfV3NativeSession& value,double clearance,double tolerance,
                               int budget,std::vector<Sweep>& output) {
    int count=int(value.sweep_rows.size()),workers=af_v3_ccd_workers(count);output.resize(count);
#pragma omp parallel for schedule(static,AF_V3_CCD_JOB_PAIRS) if(workers>1) num_threads(workers)
    for(int index=0;index<count;++index)
        output[index]=af_v3_sweep_pair(value.sweep_rows[index],1.0,clearance,tolerance,budget);
}

static bool af_v3_absorb_indexed(MeshSweep& mesh,const Sweep& pair,int index) {
    ++mesh.tested;mesh.intervals+=pair.intervals;mesh.valid&=pair.valid;mesh.possible|=pair.possible;
    if(pair.reason==4)mesh.reason=4;
    if(pair.safe<mesh.safe){mesh.safe=pair.safe;mesh.limiting=index;}
    return mesh.valid&&mesh.safe>0.0;
}

static MeshSweep af_v3_reduce_indexed(const AfV3NativeSession& value,const std::vector<Sweep>& rows,
                                      int& edge,int& face) {
    MeshSweep output{1.0,0,1,0,0,0,-1};
    for(int index=0;index<int(rows.size());++index)if(!af_v3_absorb_indexed(output,rows[index],index))break;
    if(output.limiting>=0){const auto& hit=value.sweep_rows[output.limiting];edge=hit.edge;face=hit.triangle;}
    output.reason=!output.valid?2:output.reason==4?4:output.possible?3:0;return output;
}

static bool af_v3_indexed_clear(const MeshSweep& value) {
    return value.valid&&!value.possible&&value.reason==0&&value.safe>=1.0;
}

static bool af_v3_indexed_complex(const AfV3NativeSession& value) {
    return value.last_pairs>0&&2*value.last_intervals>=value.last_pairs;
}

static bool af_v3_try_indexed(AfV3NativeSession& value,double clearance,double tolerance,int budget,
                              int& edge,int& face,MeshSweep& output) {
    int pairs=int(value.sweep_rows.size());bool ready=value.clear_sweep_streak>=AF_V3_INDEXED_CLEAR_STREAK;
    if(!ready||!af_v3_indexed_complex(value)||af_v3_ccd_workers(pairs)<2)return false;
    std::vector<Sweep> rows;++value.ccd_stats.indexed_sweeps;value.ccd_stats.indexed_pairs+=pairs;
    af_v3_indexed_rows(value,clearance,tolerance,budget,rows);output=af_v3_reduce_indexed(value,rows,edge,face);
    value.last_pairs=pairs;value.last_intervals=output.intervals;
    if(af_v3_indexed_clear(output)){++value.ccd_stats.indexed_clear;++value.clear_sweep_streak;return true;}
    ++value.ccd_stats.indexed_fallbacks;value.clear_sweep_streak=0;edge=face=-1;return false;
}

static MeshSweep af_v3_record_serial(AfV3NativeSession& value,MeshSweep output,int pairs) {
    value.ccd_stats.serial_tests+=output.tested;value.ccd_stats.serial_intervals+=output.intervals;
    value.last_pairs=pairs;value.last_intervals=output.intervals;
    if(af_v3_indexed_clear(output)){++value.ccd_stats.serial_clear;++value.clear_sweep_streak;}
    else value.clear_sweep_streak=0;return output;
}

static MeshSweep af_v3_run_sweep(AfV3NativeSession& value,double clearance,double tolerance,
                                 int budget,int& edge,int& face) {
    int pairs=int(value.sweep_rows.size());value.ccd_stats.candidate_pairs+=pairs;MeshSweep output{};
    if(af_v3_try_indexed(value,clearance,tolerance,budget,edge,face,output))return output;
    ++value.ccd_stats.serial_sweeps;output=af_v3_serial_sweep(value,clearance,tolerance,budget,edge,face);
    return af_v3_record_serial(value,output,pairs);
}

AF_EXPORT int af_v3_session_safe_step(void* handle,const double* source,const double* target,
        double clearance,double tolerance,int budget,MeshSweep* output,int* candidates,
        int* pair_count,int* limiting_edge,int* limiting_face) {
    if(!handle||!source||!target||!output||!candidates||!pair_count||!limiting_edge||!limiting_face||clearance<0.0||tolerance<=0.0||budget<1)return 1;
    auto& value=*static_cast<AfV3NativeSession*>(handle);if(!value.snapshot)return 1;
    *limiting_edge=*limiting_face=-1;af_v3_build_sweep(value,source,target,clearance,*candidates);
    *pair_count=int(value.sweep_rows.size());*output=af_v3_run_sweep(value,clearance,tolerance,budget,*limiting_edge,*limiting_face);
    ++value.stats.sweeps;return 0;
}

AF_EXPORT int af_v3_session_stats(void* handle,AfV3SessionStats* result) {
    if(!handle||!result)return 1;*result=static_cast<AfV3NativeSession*>(handle)->stats;return 0;
}

AF_EXPORT int af_v3_session_ccd_stats(void* handle,AfV3CcdStats* result) {
    if(!handle||!result)return 1;*result=static_cast<AfV3NativeSession*>(handle)->ccd_stats;return 0;
}

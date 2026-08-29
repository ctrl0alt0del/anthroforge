#pragma once

enum AfV3SqpCcdMode { AF_V3_SQP_CCD_LEGACY=0,AF_V3_SQP_CCD_INDEXED=1 };
enum AfV3SqpTermination { AF_V3_SQP_CONVERGED=1,AF_V3_SQP_STALLED=2,AF_V3_SQP_BUDGET=3,AF_V3_SQP_UNSAFE=4 };

struct AfV3SqpConfig {
    double length_weight,fidelity_weight,epsilon,radius,slack,owner_span,numeric_floor,length_scale;
    double fixed_tolerance,stationarity_tolerance,relative_energy_tolerance;
    double trust_radius,min_trust,max_trust,regularization,regularization_scale,penalty;
    int accepted_cap,trial_cap,ccd_mode,ccd_budget;
};

struct AfV3SqpResult {
    int termination,accepted,rejected,trials,contacts,ccd_pairs,ccd_tests,spacing_enabled,validated,trace_count;
    double energy,fixed_residual,stationarity,regularization,trust_radius,maximum_violation,elapsed_ms;
};

struct AfV3SqpJob {
    void* session;const double* points;const double* reference;int count;
    const int64_t* pins;const double* targets;int pin_count;AfV3SqpConfig config;
    double* output,*safe_history,*ratio_history,*violation_history;
    int* decision_history,*limiting_edges,*limiting_faces;AfV3SqpResult result;
};

struct AfV3SqpContact {
    int edge,collider,face,contained,limiting,age,clear_streak;
    double factor,gap,multiplier;Vec normal,surface;
};

struct AfV3SqpMetrics { double maximum=INFINITY,squared=INFINITY,minimum=-INFINITY;bool feasible=false; };

struct AfV3SqpState {
    AfV3SqpJob* job=nullptr;AfV3NativeSession* native=nullptr;
    std::vector<Vec> points,reference,candidate;std::vector<AfV3SqpContact> contacts;
    AfV3SqpMetrics metrics;int accepted=0,rejected=0,trials=0,stalled=0,energy_streak=0;
    int ccd_pairs=0,ccd_tests=0,termination=0;bool spacing=false,done=false,trust_boundary=false;
    int last_decision=0,last_edge=-1,last_face=-1;double fixed=INFINITY,stationarity=INFINITY;
    double last_safe=1.0,last_ratio=NAN;
};

static double af_v3_sqp_length(Vec value) { return norm(value); }

static double af_v3_sqp_edge_length(const std::vector<Vec>& points,int edge,double epsilon) {
    Vec delta=sub(points[edge+1],points[edge]);return std::sqrt(dot(delta,delta)+epsilon*epsilon);
}

static double af_v3_sqp_mean_length(const std::vector<Vec>& points,double epsilon) {
    double total=0.0;for(int edge=0;edge+1<int(points.size());++edge)total+=af_v3_sqp_edge_length(points,edge,epsilon);
    return points.size()<2?0.0:total/double(points.size()-1);
}

static double af_v3_sqp_spacing_weight(const AfV3SqpState& state) {
    if(!state.spacing)return 0.0;double mean=af_v3_sqp_mean_length(state.points,state.job->config.epsilon);
    return .5*state.job->config.length_weight/std::max(mean,state.job->config.numeric_floor);
}

static double af_v3_sqp_segment_cv(const std::vector<Vec>& points) {
    if(points.size()<2)return 0.0;std::vector<double> rows(points.size()-1);double mean=0.0;
    for(int i=0;i<int(rows.size());++i){rows[i]=norm(sub(points[i+1],points[i]));mean+=rows[i];}mean/=rows.size();
    double squared=0.0;for(double row:rows)squared+=(row-mean)*(row-mean);return mean>0.0?std::sqrt(squared/rows.size())/mean:0.0;
}

static bool af_v3_sqp_same(const AfV3SqpContact& a,const AfV3SqpContact& b,double slack) {
    if(a.edge!=b.edge||a.collider!=b.collider||a.contained!=b.contained||a.limiting!=b.limiting)return false;
    if(std::abs(a.factor-b.factor)>1.0e-6||std::abs(a.gap-b.gap)>slack)return false;
    return dot(a.normal,b.normal)>=1.0-1.0e-6;
}

static bool af_v3_sqp_key(const AfV3SqpContact& a,const AfV3SqpContact& b) {
    return a.edge==b.edge&&a.collider==b.collider&&a.face==b.face&&
           a.contained==b.contained&&a.limiting==b.limiting;
}

static double af_v3_sqp_prior_multiplier(const AfV3SqpState& state,const AfV3SqpContact& row) {
    for(const auto& prior:state.contacts)if(af_v3_sqp_key(prior,row))return prior.multiplier;
    return 0.0;
}

static int af_v3_sqp_prior_age(const AfV3SqpState& state,const AfV3SqpContact& row) {
    for(const auto& prior:state.contacts)if(af_v3_sqp_key(prior,row))return prior.age+1;
    return 0;
}

static AfV3SqpContact af_v3_sqp_contact(const AfV3SqpState& state,const AfContactPair& pair) {
    double gap=pair.contained?-(pair.distance+state.job->config.radius):pair.distance-state.job->config.radius;
    AfV3SqpContact row{pair.edge,pair.collider,pair.face,pair.contained,0,0,0,pair.factor,gap,0.0,
        load3(pair.normal),load3(pair.closest)};
    row.multiplier=af_v3_sqp_prior_multiplier(state,row);row.age=af_v3_sqp_prior_age(state,row);return row;
}

static AfV3SqpContact af_v3_sqp_refresh_limiter(const AfV3SqpState& state,const AfV3SqpContact& row,
                                                const std::vector<Vec>& points) {
    AfV3SqpContact out=row;Vec sample=add(points[row.edge],mul(sub(points[row.edge+1],points[row.edge]),row.factor));
    out.gap=dot(sub(sample,row.surface),row.normal)-state.job->config.radius;return out;
}

static bool af_v3_sqp_migrate_limiter(const AfV3SqpContact& prior,std::vector<AfV3SqpContact>& output) {
    auto found=output.end();double best=INFINITY;for(auto it=output.begin();it!=output.end();++it)
        if(!it->limiting&&it->edge==prior.edge&&it->collider==prior.collider&&std::abs(it->factor-prior.factor)<best)
            best=std::abs(it->factor-prior.factor),found=it;
    if(found==output.end())return false;found->multiplier=std::max(found->multiplier,prior.multiplier);return true;
}

static void af_v3_sqp_retain_limiters(const AfV3SqpState& state,const std::vector<Vec>& points,
                                      std::vector<AfV3SqpContact>& output) {
    double clear=std::max(4.0*state.job->config.slack,.25*state.job->config.radius);
    for(const auto& prior:state.contacts)if(prior.limiting&&!af_v3_sqp_migrate_limiter(prior,output)){
        auto row=af_v3_sqp_refresh_limiter(state,prior,points);
        if(row.gap<=clear)output.push_back(row);}
}

static bool af_v3_sqp_has_key(const std::vector<AfV3SqpContact>& rows,const AfV3SqpContact& value) {
    return std::any_of(rows.begin(),rows.end(),[&value](const auto& row){return af_v3_sqp_key(row,value);});
}

static void af_v3_sqp_retain_contacts(const AfV3SqpState& state,std::vector<AfV3SqpContact>& output) {
    double clear=std::max(4.0*state.job->config.slack,.25*state.job->config.radius);
    for(const auto& prior:state.contacts)if(!prior.limiting&&!af_v3_sqp_has_key(output,prior)){auto row=prior;
        row.gap=clear;row.multiplier=std::max(0.0,row.multiplier-state.job->config.penalty*clear);++row.clear_streak;
        if(row.clear_streak<2||row.multiplier>state.job->config.penalty*state.job->config.slack)output.push_back(row);}
}

static std::vector<AfV3SqpContact> af_v3_sqp_contacts(const AfV3SqpState& state) {
    std::vector<AfV3SqpContact> output;
    for(const auto& pair:state.native->contacts){auto row=af_v3_sqp_contact(state,pair);bool duplicate=false;
        for(const auto& prior:output)if(af_v3_sqp_same(prior,row,state.job->config.slack)){duplicate=true;break;}
        if(!duplicate)output.push_back(row);}return output;
}

static AfV3SqpMetrics af_v3_sqp_metrics(const AfV3SqpState& state,const AfV3MeasureOperation& row,
                                        const std::vector<AfV3SqpContact>& contacts) {
    AfV3SqpMetrics out{0.0,0.0,row.validation.minimum,false};
    for(const auto& contact:contacts){double violation=std::max(0.0,-contact.gap);out.maximum=std::max(out.maximum,violation);out.squared+=violation*violation;}
    out.maximum=std::max(out.maximum,std::max(0.0,state.job->config.radius-state.job->config.slack-row.validation.minimum));
    out.feasible=row.validation.rejected==0&&out.maximum<=state.job->config.slack;return out;
}

static AfV3SqpMetrics af_v3_sqp_measure(AfV3SqpState& state,const std::vector<Vec>& points,
                                        std::vector<AfV3SqpContact>& contacts) {
    int edges=state.job->count-1;std::vector<int> clear(edges),blockers(edges);std::vector<double> minima(edges);
    double activation=state.job->config.radius+std::max(4.0*state.job->config.slack,.25*state.job->config.radius);
    AfV3MeasureOperation row{state.native,reinterpret_cast<const double*>(points.data()),state.job->config.owner_span,
        activation,std::max(0.0,state.job->config.radius-state.job->config.slack),nullptr,0,0,{},clear.data(),blockers.data(),minima.data(),{}};
    AfV3CoordinatorWork work;af_v3_coordinator_measure(row,work);contacts=af_v3_sqp_contacts(state);
    af_v3_sqp_retain_contacts(state,contacts);af_v3_sqp_retain_limiters(state,points,contacts);
    return af_v3_sqp_metrics(state,row,contacts);
}

static void af_v3_sqp_spacing_gradient(const std::vector<Vec>& points,double weight,std::vector<Vec>& gradient) {
    if(weight<=0.0||points.size()<2)return;double mean=af_v3_sqp_mean_length(points,0.0);
    for(int edge=0;edge+1<int(points.size());++edge){Vec delta=sub(points[edge+1],points[edge]);double length=norm(delta);
        Vec row=length>1.0e-15?mul(delta,weight*(length-mean)/length):Vec{0,0,0};gradient[edge]=sub(gradient[edge],row);gradient[edge+1]=add(gradient[edge+1],row);}
}

static void af_v3_sqp_bands(AfV3SqpState& state,std::vector<double>& diagonal,
                            std::vector<double>& lower1,std::vector<Vec>& rhs) {
    int count=state.job->count;double fidelity=state.job->config.fidelity_weight,spacing=af_v3_sqp_spacing_weight(state);
    diagonal.assign(count,fidelity+state.job->config.regularization+spacing);lower1.assign(count,0.0);
    rhs.resize(count);std::vector<Vec> gradient(count,Vec{0,0,0});af_v3_sqp_spacing_gradient(state.points,spacing,gradient);
    for(int i=0;i<count;++i)rhs[i]=sub(add(mul(state.reference[i],fidelity),mul(state.points[i],state.job->config.regularization+spacing)),gradient[i]);
    for(int edge=0;edge+1<count;++edge){double scale=.5*state.job->config.length_weight/af_v3_sqp_edge_length(state.points,edge,state.job->config.epsilon);
        diagonal[edge]+=scale;diagonal[edge+1]+=scale;lower1[edge+1]-=scale;}
}

static Vec af_v3_sqp_jacobian(const AfV3SqpContact& row,int node) {
    if(node==row.edge)return mul(row.normal,1.0-row.factor);
    return node==row.edge+1?mul(row.normal,row.factor):Vec{0,0,0};
}

static double af_v3_sqp_apply(const AfV3SqpContact& row,const std::vector<Vec>& values) {
    return dot(af_v3_sqp_jacobian(row,row.edge),values[row.edge])+
           dot(af_v3_sqp_jacobian(row,row.edge+1),values[row.edge+1]);
}

static std::vector<std::vector<Vec>> af_v3_sqp_responses(AfV3SqpState& state) {
    std::vector<std::vector<Vec>> output(state.contacts.size(),std::vector<Vec>(state.job->count));
    for(int index=0;index<int(state.contacts.size());++index){const auto& row=state.contacts[index];
        std::fill(state.native->response.begin(),state.native->response.end(),Vec{0,0,0});
        if(!state.native->pinned[row.edge])state.native->response[row.edge]=af_v3_sqp_jacobian(row,row.edge);
        if(!state.native->pinned[row.edge+1])state.native->response[row.edge+1]=af_v3_sqp_jacobian(row,row.edge+1);
        af_v3_solve_into(*state.native,state.native->response,output[index]);}return output;
}

static bool af_v3_sqp_factor(AfV3SqpState& state,const std::vector<double>& diagonal,
                             const std::vector<double>& lower1,const std::vector<Vec>& rhs) {
    std::vector<double> lower2(state.job->count,0.0);af_v3_load_system(*state.native,diagonal.data(),lower1.data(),lower2.data(),reinterpret_cast<const double*>(rhs.data()),state.job->count);
    return af_v3_prepare_factor(*state.native,state.job->pins,state.job->targets,state.job->pin_count,state.job->count);
}

static void af_v3_sqp_dense_solve(std::vector<double>& matrix,std::vector<double>& rhs,int count) {
    double scale=0.0;for(int i=0;i<count;++i)scale=std::max(scale,std::abs(matrix[count*i+i]));
    for(int i=0;i<count;++i)matrix[count*i+i]+=std::max(1.0e-14,1.0e-10*scale);
    for(int pivot=0;pivot<count;++pivot){int best=pivot;for(int row=pivot+1;row<count;++row)
        if(std::abs(matrix[count*row+pivot])>std::abs(matrix[count*best+pivot]))best=row;
        for(int col=pivot;col<count;++col)std::swap(matrix[count*pivot+col],matrix[count*best+col]);std::swap(rhs[pivot],rhs[best]);
        double value=matrix[count*pivot+pivot];if(std::abs(value)<1.0e-20)continue;for(int row=pivot+1;row<count;++row){double f=matrix[count*row+pivot]/value;
            for(int col=pivot;col<count;++col)matrix[count*row+col]-=f*matrix[count*pivot+col];rhs[row]-=f*rhs[pivot];}}
    for(int row=count-1;row>=0;--row){for(int col=row+1;col<count;++col)rhs[row]-=matrix[count*row+col]*rhs[col];rhs[row]/=matrix[count*row+row];}
}

static std::vector<int> af_v3_sqp_initial_active(const AfV3SqpState& state) {
    std::vector<int> output;for(int i=0;i<int(state.contacts.size());++i)
        if(state.contacts[i].gap<=0.0||state.contacts[i].multiplier>0.0)output.push_back(i);return output;
}

static std::vector<double> af_v3_sqp_equalities(const AfV3SqpState& state,const std::vector<std::vector<Vec>>& responses,
                                                const std::vector<int>& active,std::vector<Vec>& solved) {
    int count=int(active.size());std::vector<double> matrix(count*count),rhs(count);solved=state.native->base;
    for(int i=0;i<count;++i){const auto& row=state.contacts[active[i]];rhs[i]=af_v3_sqp_apply(row,state.points)-row.gap-af_v3_sqp_apply(row,solved);
        for(int j=0;j<count;++j)matrix[count*i+j]=af_v3_sqp_apply(row,responses[active[j]]);}af_v3_sqp_dense_solve(matrix,rhs,count);
    for(int j=0;j<count;++j)for(int node=0;node<int(solved.size());++node)solved[node]=add(solved[node],mul(responses[active[j]][node],rhs[j]));return rhs;
}

static int af_v3_sqp_active_change(const AfV3SqpState& state,const std::vector<int>& active,
                                   const std::vector<double>& multipliers,const std::vector<Vec>& solved) {
    double best=0.0;int change=0;for(int i=0;i<int(active.size());++i)if(multipliers[i]<best-1.0e-10){best=multipliers[i];change=-(active[i]+1);}
    if(change)return change;for(int i=0;i<int(state.contacts.size());++i)if(std::find(active.begin(),active.end(),i)==active.end()){
        const auto& row=state.contacts[i];double gap=row.gap+af_v3_sqp_apply(row,solved)-af_v3_sqp_apply(row,state.points);
        if(gap<best-1.0e-10){best=gap;change=i+1;}}return change;
}

static void af_v3_sqp_apply_change(std::vector<int>& active,int change) {
    int index=std::abs(change)-1;if(change<0)active.erase(std::find(active.begin(),active.end(),index));
    else active.push_back(index);std::sort(active.begin(),active.end());
}

static std::vector<double> af_v3_sqp_active_set(AfV3SqpState& state,const std::vector<std::vector<Vec>>& responses,
                                               std::vector<int>& active,std::vector<Vec>& solved) {
    std::vector<double> multipliers;int limit=std::min(16,std::max(4,2*int(state.contacts.size())+1));
    for(int iteration=0;iteration<limit;++iteration){multipliers=af_v3_sqp_equalities(state,responses,active,solved);
        int change=af_v3_sqp_active_change(state,active,multipliers,solved);if(!change)break;af_v3_sqp_apply_change(active,change);}return multipliers;
}

static void af_v3_sqp_restore_pins(AfV3SqpState& state,std::vector<Vec>& points) {
    for(int i=0;i<state.job->pin_count;++i)points[state.job->pins[i]]=load3(state.job->targets+3*i);
}

static bool af_v3_sqp_trust(AfV3SqpState& state,std::vector<Vec>& candidate) {
    double maximum=0.0;for(int i=0;i<int(candidate.size());++i)maximum=std::max(maximum,norm(sub(candidate[i],state.points[i])));
    double fraction=std::min(1.0,state.job->config.trust_radius/std::max(maximum,state.job->config.numeric_floor));
    for(int i=0;i<int(candidate.size());++i)candidate[i]=add(state.points[i],mul(sub(candidate[i],state.points[i]),fraction));
    af_v3_sqp_restore_pins(state,candidate);return maximum>=.8*state.job->config.trust_radius;
}

static bool af_v3_sqp_candidate(AfV3SqpState& state,std::vector<int>& active,std::vector<double>& multipliers) {
    std::vector<double> diagonal,lower1;std::vector<Vec> rhs;af_v3_sqp_bands(state,diagonal,lower1,rhs);
    if(!af_v3_sqp_factor(state,diagonal,lower1,rhs))return false;af_v3_solve_into(*state.native,state.native->rhs,state.native->base);
    auto responses=af_v3_sqp_responses(state);active=af_v3_sqp_initial_active(state);
    multipliers=af_v3_sqp_active_set(state,responses,active,state.candidate);
    state.trust_boundary=af_v3_sqp_trust(state,state.candidate);return true;
}

static double af_v3_sqp_spacing_energy(const std::vector<Vec>& points,double weight) {
    if(weight<=0.0||points.size()<2)return 0.0;double mean=af_v3_sqp_mean_length(points,0.0),energy=0.0;
    for(int edge=0;edge+1<int(points.size());++edge){double delta=norm(sub(points[edge+1],points[edge]))-mean;energy+=delta*delta;}return weight*energy;
}

static double af_v3_sqp_energy(const AfV3SqpState& state,const std::vector<Vec>& points) {
    double output=0.0;for(int i=0;i<int(points.size());++i){Vec delta=sub(points[i],state.reference[i]);output+=state.job->config.fidelity_weight*dot(delta,delta);}
    for(int edge=0;edge+1<int(points.size());++edge)output+=state.job->config.length_weight*af_v3_sqp_edge_length(points,edge,state.job->config.epsilon);
    return output+af_v3_sqp_spacing_energy(points,af_v3_sqp_spacing_weight(state));
}

static double af_v3_sqp_model_energy(const AfV3SqpState& state,const std::vector<Vec>& values) {
    double output=0.0;for(int i=0;i<int(values.size());++i){Vec delta=sub(values[i],state.reference[i]);output+=state.job->config.fidelity_weight*dot(delta,delta);}
    for(int edge=0;edge+1<int(values.size());++edge){double scale=.5*state.job->config.length_weight/af_v3_sqp_edge_length(state.points,edge,state.job->config.epsilon);
        Vec delta=sub(values[edge+1],values[edge]);output+=scale*dot(delta,delta);}return output+af_v3_sqp_spacing_energy(values,af_v3_sqp_spacing_weight(state));
}

static double af_v3_sqp_ratio(const AfV3SqpState& state,const std::vector<Vec>& candidate,
                              const AfV3SqpMetrics& metrics) {
    double predicted=af_v3_sqp_model_energy(state,state.points)-af_v3_sqp_model_energy(state,candidate);
    double proximal=0.0;for(int i=0;i<int(candidate.size());++i){Vec d=sub(candidate[i],state.points[i]);proximal+=dot(d,d);}predicted-=state.job->config.regularization*proximal;
    double actual=state.metrics.feasible?af_v3_sqp_energy(state,state.points)-af_v3_sqp_energy(state,candidate):
        state.metrics.maximum+std::sqrt(state.metrics.squared)-metrics.maximum-std::sqrt(metrics.squared);
    double roundoff=64.0*std::numeric_limits<double>::epsilon()*std::max(1.0,std::abs(af_v3_sqp_energy(state,state.points)));
    double floor=std::max({state.job->config.numeric_floor*state.job->config.numeric_floor,1.0e-16,roundoff});
    return predicted<=floor?(actual>=-floor?1.0:-INFINITY):actual/predicted;
}

static bool af_v3_sqp_filter(const AfV3SqpMetrics& before,const AfV3SqpMetrics& after) {
    double slack=std::max(1.0e-12,1.0e-6*std::max(1.0,before.maximum));
    if(after.maximum<before.maximum-slack)return true;bool level=std::abs(after.maximum-before.maximum)<=slack;
    return level&&after.squared<before.squared-slack*slack;
}

static void af_v3_sqp_controller(AfV3SqpState& state,double ratio,bool accepted,bool contact_changed=false) {
    double factor=!accepted?(contact_changed?2.0:4.0):std::isfinite(ratio)&&ratio>.75?.5:!std::isfinite(ratio)||ratio<.25?2.0:1.0;
    double low=1.0e-10*state.job->config.regularization_scale,high=1.0e2*state.job->config.regularization_scale;
    state.job->config.regularization=std::clamp(factor*state.job->config.regularization,low,high);
    if(!accepted||!std::isfinite(ratio)||ratio<.1)state.job->config.trust_radius=std::max(state.job->config.min_trust,.25*state.job->config.trust_radius);
    else if(ratio<.25)state.job->config.trust_radius=std::max(state.job->config.min_trust,.5*state.job->config.trust_radius);
    else if(ratio>.75&&state.trust_boundary)state.job->config.trust_radius=std::min(state.job->config.max_trust,2.0*state.job->config.trust_radius);
}

static MeshSweep af_v3_sqp_sweep(AfV3SqpState& state,const std::vector<Vec>& target,int& edge,int& face) {
    int candidates=0;edge=face=-1;auto* source=reinterpret_cast<const double*>(state.points.data());auto* end=reinterpret_cast<const double*>(target.data());
    if(!state.native->snapshot)return {1.0,0,1,0,0,0,-1};
    if(state.job->config.ccd_mode==AF_V3_SQP_CCD_LEGACY){af_v3_build_sweep(*state.native,source,end,state.job->config.radius-state.job->config.slack,candidates);
        state.ccd_pairs+=int(state.native->sweep_rows.size());auto result=af_v3_serial_sweep(*state.native,state.job->config.radius-state.job->config.slack,1.0e-5,state.job->config.ccd_budget,edge,face);state.ccd_tests+=result.tested;return result;}
    AfV3BatchSweepJob row{state.native,source,end,state.job->config.radius-state.job->config.slack,1.0e-5,state.job->config.ccd_budget};
    AfV3CoordinatorWork work;af_v3_coordinator_sweep(row,work);edge=row.edge;face=row.face;state.ccd_pairs+=row.pairs;state.ccd_tests+=row.result.tested;return row.result;
}

static const AfV3SweepRow* af_v3_sqp_sweep_row(const AfV3SqpState& state,int edge,int face) {
    for(const auto& row:state.native->sweep_rows)if(row.edge==edge&&row.triangle==face)return &row;
    return nullptr;
}

static Vec af_v3_sqp_limiter_normal(const AfSegmentPair& pair,const AfV3SweepRow& sweep,Vec source) {
    Vec normal=af_unit(sub(pair.line,pair.surface));if(norm(normal)>eps())return normal;
    normal=af_unit(pair.normal);return dot(sub(source,sweep.face[0]),normal)<0.0?mul(normal,-1.0):normal;
}

static std::pair<int,int> af_v3_sqp_face_identity(const AfV3SqpState& state,int face) {
    int offset=0;for(const auto& item:state.native->world->items){int count=int(item.mesh->triangles.size()/3);
        if(face<offset+count)return {item.collider,face-offset};offset+=count;}return {-1,face};
}

static AfV3SqpContact af_v3_sqp_limiter(AfV3SqpState& state,const MeshSweep& hit,int edge,int face) {
    const auto* sweep=af_v3_sqp_sweep_row(state,edge,face);if(!sweep)return {-1,0,0,0,0,0,0,0,0,0,{},{}};
    Vec a=add(sweep->start[0],mul(sub(sweep->end[0],sweep->start[0]),hit.safe));
    Vec b=add(sweep->start[1],mul(sub(sweep->end[1],sweep->start[1]),hit.safe));
    auto pair=af_closest_segment_face(a,b,sweep->face,-1);Vec sample=add(sweep->start[0],mul(sub(sweep->start[1],sweep->start[0]),pair.factor));
    Vec normal=af_v3_sqp_limiter_normal(pair,*sweep,sample);double gap=dot(sub(sample,pair.surface),normal)-state.job->config.radius;
    auto identity=af_v3_sqp_face_identity(state,face);
    return {edge,identity.first,identity.second,0,1,0,0,pair.factor,gap,0.0,normal,pair.surface};
}

static bool af_v3_sqp_inject(AfV3SqpState& state,const MeshSweep& hit,int edge,int face) {
    if(hit.safe>=1.0||edge<0||face<0)return false;auto row=af_v3_sqp_limiter(state,hit,edge,face);
    if(row.edge<0)return false;for(auto& prior:state.contacts)if(prior.limiting&&af_v3_sqp_key(prior,row)){
        bool changed=!af_v3_sqp_same(prior,row,state.job->config.slack);prior=row;return changed;}
    state.contacts.push_back(row);return true;
}

static std::vector<Vec> af_v3_sqp_safe_candidate(AfV3SqpState& state,const MeshSweep& sweep) {
    double fraction=sweep.safe>=1.0?1.0:.999*sweep.safe;std::vector<Vec> output(state.points.size());
    for(int i=0;i<int(output.size());++i)output[i]=add(state.points[i],mul(sub(state.candidate[i],state.points[i]),fraction));
    af_v3_sqp_restore_pins(state,output);return output;
}

static std::vector<AfV3SqpContact> af_v3_sqp_duals(const AfV3SqpState& state,
                                                   const std::vector<int>& active,
                                                   const std::vector<double>& multipliers) {
    std::vector<AfV3SqpContact> output;for(int i=0;i<int(active.size());++i){auto row=state.contacts[active[i]];
        row.multiplier=std::max(0.0,multipliers[i]);output.push_back(row);}return output;
}

static void af_v3_sqp_apply_multipliers(AfV3SqpState& state,const std::vector<AfV3SqpContact>& duals) {
    for(auto& row:state.contacts)row.multiplier=0.0;
    for(auto& row:state.contacts)for(const auto& prior:duals)if(af_v3_sqp_key(row,prior)){
        row.multiplier=prior.multiplier;break;}
}

static void af_v3_sqp_contact_gradient(const AfV3SqpState& state,std::vector<Vec>& gradient) {
    for(const auto& row:state.contacts){double active=std::max(0.0,row.multiplier-state.job->config.penalty*row.gap);
        gradient[row.edge]=sub(gradient[row.edge],mul(af_v3_sqp_jacobian(row,row.edge),active));
        gradient[row.edge+1]=sub(gradient[row.edge+1],mul(af_v3_sqp_jacobian(row,row.edge+1),active));}
}

static double af_v3_sqp_stationarity(const AfV3SqpState& state) {
    std::vector<Vec> gradient(state.points.size());double spacing=af_v3_sqp_spacing_weight(state);
    for(int i=0;i<int(state.points.size());++i)gradient[i]=mul(sub(state.points[i],state.reference[i]),state.job->config.fidelity_weight);
    for(int edge=0;edge+1<int(state.points.size());++edge){Vec delta=sub(state.points[edge+1],state.points[edge]);double scale=.5*state.job->config.length_weight/af_v3_sqp_edge_length(state.points,edge,state.job->config.epsilon);
        gradient[edge]=sub(gradient[edge],mul(delta,scale));gradient[edge+1]=add(gradient[edge+1],mul(delta,scale));}af_v3_sqp_spacing_gradient(state.points,spacing,gradient);
    af_v3_sqp_contact_gradient(state,gradient);
    for(int i=0;i<state.job->pin_count;++i)gradient[state.job->pins[i]]={0,0,0};double maximum=0.0;
    for(Vec row:gradient)maximum=std::max(maximum,norm(row));double scale=std::max(1.0,state.job->config.regularization_scale*state.job->config.length_scale);return maximum/scale;
}

static void af_v3_sqp_adopt(AfV3SqpState& state,std::vector<Vec>& points,std::vector<AfV3SqpContact>& contacts,
                            const AfV3SqpMetrics& metrics,const std::vector<int>& active,const std::vector<double>& multipliers) {
    double old=af_v3_sqp_energy(state,state.points),movement=0.0;for(int i=0;i<int(points.size());++i)movement=std::max(movement,norm(sub(points[i],state.points[i])));
    auto duals=af_v3_sqp_duals(state,active,multipliers);state.points.swap(points);state.contacts.swap(contacts);
    af_v3_sqp_apply_multipliers(state,duals);state.metrics=metrics;++state.accepted;
    state.fixed=movement/state.job->config.length_scale;state.stationarity=af_v3_sqp_stationarity(state);double energy=af_v3_sqp_energy(state,state.points);
    double relative=std::abs(energy-old)/std::max(1.0,std::abs(old));state.energy_streak=relative<=state.job->config.relative_energy_tolerance?state.energy_streak+1:0;
}

static bool af_v3_sqp_converged(const AfV3SqpState& state) {
    return state.metrics.feasible&&state.fixed<=state.job->config.fixed_tolerance&&
           state.stationarity<=state.job->config.stationarity_tolerance&&state.energy_streak>=3;
}

static bool af_v3_sqp_feasible_candidate(AfV3SqpState& state,std::vector<Vec>& proposed) {
    int edge=-1,face=-1;auto sweep=af_v3_sqp_sweep(state,state.candidate,edge,face);
    state.last_safe=sweep.safe;state.last_edge=edge;state.last_face=face;
    if(af_v3_sqp_inject(state,sweep,edge,face)){++state.rejected;state.stalled=0;state.last_decision=3;
        af_v3_sqp_controller(state,-INFINITY,false,true);return false;}
    if(!sweep.valid||sweep.safe<=state.job->config.numeric_floor){++state.rejected;++state.stalled;
        state.last_decision=4;af_v3_sqp_controller(state,-INFINITY,false);return false;}
    proposed=af_v3_sqp_safe_candidate(state,sweep);return true;
}

static bool af_v3_sqp_trial(AfV3SqpState& state) {
    state.last_safe=1.0;state.last_ratio=NAN;state.last_decision=0;state.last_edge=state.last_face=-1;
    if(!state.spacing&&state.accepted>=4&&af_v3_sqp_segment_cv(state.points)>.75)state.spacing=true;
    std::vector<int> active;std::vector<double> multipliers;if(!af_v3_sqp_candidate(state,active,multipliers)){
        state.done=true;state.termination=AF_V3_SQP_UNSAFE;state.last_decision=5;return false;}
    std::vector<Vec> proposed=state.candidate;if(state.metrics.feasible&&!af_v3_sqp_feasible_candidate(state,proposed))return false;
    std::vector<AfV3SqpContact> contacts;auto metrics=af_v3_sqp_measure(state,proposed,contacts);double ratio=af_v3_sqp_ratio(state,proposed,metrics);
    state.last_ratio=ratio;
    bool accepted=state.metrics.feasible?metrics.feasible&&ratio>=.1:af_v3_sqp_filter(state.metrics,metrics);af_v3_sqp_controller(state,ratio,accepted);
    if(accepted){af_v3_sqp_adopt(state,proposed,contacts,metrics,active,multipliers);state.stalled=0;}else{++state.rejected;++state.stalled;}
    state.last_decision=accepted?1:2;
    if(af_v3_sqp_converged(state))state.done=true,state.termination=AF_V3_SQP_CONVERGED;
    else if(state.stalled>=8)state.done=true,state.termination=state.metrics.feasible?AF_V3_SQP_STALLED:AF_V3_SQP_UNSAFE;
    return accepted;
}

static void af_v3_sqp_trace(AfV3SqpState& state) {
    int index=state.trials-1;if(index<0)return;auto* job=state.job;
    if(job->safe_history)job->safe_history[index]=state.last_safe;
    if(job->ratio_history)job->ratio_history[index]=state.last_ratio;
    if(job->violation_history)job->violation_history[index]=state.metrics.maximum;
    if(job->decision_history)job->decision_history[index]=state.last_decision;
    if(job->limiting_edges)job->limiting_edges[index]=state.last_edge;
    if(job->limiting_faces)job->limiting_faces[index]=state.last_face;
}

static AfV3SqpState af_v3_sqp_state(AfV3SqpJob& job) {
    AfV3SqpState state;state.job=&job;state.native=static_cast<AfV3NativeSession*>(job.session);
    state.points.assign(reinterpret_cast<const Vec*>(job.points),reinterpret_cast<const Vec*>(job.points)+job.count);
    state.reference.assign(reinterpret_cast<const Vec*>(job.reference),reinterpret_cast<const Vec*>(job.reference)+job.count);
    state.candidate.resize(job.count);state.metrics=af_v3_sqp_measure(state,state.points,state.contacts);return state;
}

static int af_v3_sqp_accepted(const std::vector<AfV3SqpState>& states) {
    int total=0;for(const auto& state:states)total+=state.accepted;return total;
}

static bool af_v3_sqp_all_done(const std::vector<AfV3SqpState>& states) {
    return std::all_of(states.begin(),states.end(),[](const auto& state){return state.done;});
}

static void af_v3_sqp_sync_owner_span(std::vector<AfV3SqpState>& states) {
    double value=1.0e-9;for(const auto& state:states){const auto& config=state.job->config;
        value=std::max({value,4.0*config.slack,2.5*config.radius});
        if(state.points.size()>1){value=std::max(value,norm(sub(state.points[1],state.points[0])));
            value=std::max(value,norm(sub(state.points.back(),state.points[state.points.size()-2])));}}
    for(auto& state:states)state.job->config.owner_span=value;
}

static void af_v3_sqp_finish(AfV3SqpState& state,bool budget,double elapsed) {
    std::vector<AfV3SqpContact> contacts;state.metrics=af_v3_sqp_measure(state,state.points,contacts);
    af_write_vectors(state.points,state.job->output);auto& out=state.job->result;
    out.termination=!state.metrics.feasible?AF_V3_SQP_UNSAFE:state.termination?state.termination:budget?AF_V3_SQP_BUDGET:AF_V3_SQP_STALLED;
    out.accepted=state.accepted;out.rejected=state.rejected;out.trials=state.trials;out.contacts=int(state.contacts.size());
    out.ccd_pairs=state.ccd_pairs;out.ccd_tests=state.ccd_tests;out.spacing_enabled=state.spacing;out.validated=state.metrics.feasible;
    out.trace_count=state.trials;
    out.energy=af_v3_sqp_energy(state,state.points);out.fixed_residual=state.fixed;out.stationarity=state.stationarity;
    out.regularization=state.job->config.regularization;out.trust_radius=state.job->config.trust_radius;out.maximum_violation=state.metrics.maximum;out.elapsed_ms=elapsed;
}

static void af_v3_sqp_loop(std::vector<AfV3SqpState>& states,int accepted_cap,int trial_cap) {
    int cursor=0,trials=0;while(af_v3_sqp_accepted(states)<accepted_cap&&trials<trial_cap&&!af_v3_sqp_all_done(states)){
        if(cursor==0)af_v3_sqp_sync_owner_span(states);
        int checked=0;while(states[cursor].done&&checked++<int(states.size()))cursor=(cursor+1)%states.size();
        if(states[cursor].done)break;++states[cursor].trials;af_v3_sqp_trial(states[cursor]);af_v3_sqp_trace(states[cursor]);
        cursor=(cursor+1)%states.size();++trials;}
}

AF_EXPORT int af_v3_native_sqp_solve(AfV3SqpJob* jobs,int count,int accepted_cap,int trial_cap) {
    if(!jobs||count<1||accepted_cap<1||trial_cap<1)return 1;auto started=std::chrono::steady_clock::now();
    std::vector<AfV3SqpState> states;states.reserve(count);
#pragma omp parallel num_threads(af_requested_workers)
#pragma omp single
    {for(int i=0;i<count;++i)states.push_back(af_v3_sqp_state(jobs[i]));af_v3_sqp_loop(states,accepted_cap,trial_cap);}
    double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    bool budget=af_v3_sqp_accepted(states)>=accepted_cap;for(auto& state:states)af_v3_sqp_finish(state,budget,elapsed);return 0;
}

#pragma once

constexpr int AF_MUSCLE_NUMERIC_CAPABILITY=67108864;
constexpr int AF_MUSCLE_PARALLEL_POINTS=1024;
static int af_muscle_parallel_points=AF_MUSCLE_PARALLEL_POINTS;

struct AfMuscleInput {
    int point_start,input_rows,input_cols,target_cols,densify,closed_u,topology_closed_v;
    int topology_flip,inflation_mode,inflation_enabled,falloff,inflation_closed_v,inflation_flip,initialize_control;
    double amount,radius,depth,b_strength,b_band,b_power,taper,control[3];
};

struct AfMuscleStats { int workers,parallel,muscles,input_points,output_points;double elapsed_ms; };
struct AfMuscleOutput { std::vector<double> boundary_weights,length_weights;std::vector<Vec> base,inflated;std::vector<int64_t> faces;int rows=0,cols=0,status=0; };
struct AfMuscleBatch { std::vector<AfMuscleOutput> outputs; };

static Vec af_muscle_lerp(Vec a,Vec b,double t) { return add(a,mul(sub(b,a),t)); }

static Vec af_muscle_unit(Vec value,Vec fallback={0,0,1}) {
    double length=norm(value);if(length<=1.0e-10)value=fallback,length=norm(value);
    return length<=1.0e-12?Vec{0,0,1}:mul(value,1.0/length);
}

static std::vector<double> af_muscle_spans(const Vec* points,int count,bool closed) {
    int total=count+(closed&&norm(sub(points[0],points[count-1]))>1.0e-9?1:0);
    std::vector<double> spans(total,0.0);
    for(int i=1;i<total;++i)spans[i]=spans[i-1]+norm(sub(i==count?points[0]:points[i],points[i-1]));
    return spans;
}

static Vec af_muscle_sample(const Vec* points,int count,const std::vector<double>& spans,double target) {
    for(int i=0;i+1<int(spans.size());++i)if(spans[i+1]>=target){
        double width=std::max(1.0e-9,spans[i+1]-spans[i]);Vec next=i+1==count?points[0]:points[i+1];
        return af_muscle_lerp(points[i],next,(target-spans[i])/width);}
    return spans.size()>size_t(count)?points[0]:points[count-1];
}

static std::vector<Vec> af_muscle_resample_row(const Vec* points,int count,int output,bool closed) {
    auto spans=af_muscle_spans(points,count,closed);std::vector<Vec> row(output,points[0]);
    if(spans.back()<=1.0e-9)return row;
    double divisor=double(closed?output:std::max(1,output-1));
    for(int i=0;i<output;++i)row[i]=af_muscle_sample(points,count,spans,spans.back()*i/divisor);
    return row;
}

static double af_muscle_row_score(const Vec* reference,const std::vector<Vec>& row,int shift,bool reverse) {
    double score=0.0;int count=int(row.size());
    for(int i=0;i<count;++i){int index=reverse?(count-1-((i+shift)%count)):((i+shift)%count);
        Vec delta=sub(reference[i],row[index]);score+=dot(delta,delta);}
    return score/std::max(1,count);
}

static std::vector<Vec> af_muscle_aligned(const Vec* reference,const std::vector<Vec>& row) {
    int best_shift=0;bool best_reverse=false;double best=INFINITY;int count=int(row.size());
    for(int reverse=0;reverse<2;++reverse)for(int shift=0;shift<count;++shift){
        double score=af_muscle_row_score(reference,row,shift,reverse!=0);
        if(score<best){best=score;best_shift=shift;best_reverse=reverse!=0;}}
    std::vector<Vec> out(count);for(int i=0;i<count;++i){int index=best_reverse?(count-1-((i+best_shift)%count)):((i+best_shift)%count);out[i]=row[index];}
    return out;
}

static std::vector<Vec> af_muscle_resample(const double* points,const AfMuscleInput& input) {
    int rows=input.input_rows,source=input.input_cols,cols=input.target_cols;std::vector<Vec> out(rows*cols);
    for(int i=0;i<rows;++i){auto row=af_muscle_resample_row(reinterpret_cast<const Vec*>(points)+i*source,source,cols,input.closed_u!=0);
        if(input.closed_u&&i)row=af_muscle_aligned(out.data()+(i-1)*cols,row);
        std::copy(row.begin(),row.end(),out.begin()+i*cols);}
    return out;
}

static double af_muscle_u_step(const std::vector<Vec>& rows,int count,int cols) {
    double sum=0.0;int samples=0;
    for(int i=0;i<count;++i)for(int j=0;j+1<cols;++j)sum+=norm(sub(rows[i*cols+j+1],rows[i*cols+j])),++samples;
    return std::max(1.0e-6,sum/std::max(1,samples));
}

static int af_muscle_inserts(const Vec* first,const Vec* second,int cols,double step,int minimum) {
    double average=0.0;for(int j=0;j<cols;++j)average+=norm(sub(second[j],first[j]));
    average/=double(cols);int count=int(std::nearbyint(average/step-1.0e-6))-1;
    return std::max(minimum,count);
}

static void af_muscle_append_row(std::vector<Vec>& out,const Vec* first,const Vec* second,int cols,double factor) {
    size_t offset=out.size();out.resize(offset+cols);
    for(int j=0;j<cols;++j)out[offset+j]=second?af_muscle_lerp(first[j],second[j],factor):first[j];
}

static std::vector<Vec> af_muscle_densify(const std::vector<Vec>& source,int rows,int cols,bool closed) {
    if(rows<2)return source;double step=af_muscle_u_step(source,rows,cols);std::vector<Vec> out;
    af_muscle_append_row(out,source.data(),nullptr,cols,0.0);
    for(int i=0;i+1<rows;++i){const Vec* a=source.data()+i*cols;const Vec* b=a+cols;
        int inserts=af_muscle_inserts(a,b,cols,step,closed?3:0);
        for(int k=1;k<=inserts;++k)af_muscle_append_row(out,a,b,cols,double(k)/double(inserts+1));
        af_muscle_append_row(out,b,nullptr,cols,0.0);}
    return out;
}

static void af_muscle_face(AfMuscleOutput&,const AfMuscleInput&,int,int,int,int,int);

static void af_muscle_faces(AfMuscleOutput& out,const AfMuscleInput& input) {
    int pairs=out.rows-1+(input.topology_closed_v&&out.rows>2?1:0);
    int columns=input.closed_u&&out.cols>2?out.cols:out.cols-1;out.faces.resize(size_t(pairs)*columns*4);
    for(int pair=0;pair<pairs;++pair){int first=pair==out.rows-1?out.rows-1:pair,second=pair==out.rows-1?0:pair+1;
        for(int j=0;j<columns;++j)af_muscle_face(out,input,pair,first,second,j,columns);}
}

static void af_muscle_face(AfMuscleOutput& out,const AfMuscleInput& input,int pair,int first,int second,int j,int columns) {
    int next=(j+1)%out.cols;int64_t q[4]={int64_t(first*out.cols+j),int64_t(second*out.cols+j),int64_t(second*out.cols+next),int64_t(first*out.cols+next)};
    int64_t* dst=out.faces.data()+4*(pair*columns+j);
    if(input.topology_flip)dst[0]=q[0],dst[1]=q[3],dst[2]=q[2],dst[3]=q[1];
    else std::copy(q,q+4,dst);
}

static Vec af_muscle_centroid(const std::vector<Vec>& points) {
    Vec value{0,0,0};for(Vec point:points)value=add(value,point);
    return mul(value,1.0/std::max<size_t>(1,points.size()));
}

static Vec af_muscle_normal(const std::vector<Vec>& points,int i,int j,int rows,int cols,Vec centroid) {
    int im=std::max(0,i-1),ip=std::min(rows-1,i+1),jm=std::max(0,j-1),jp=std::min(cols-1,j+1);
    Vec tv=sub(points[ip*cols+j],points[im*cols+j]);Vec tu=sub(points[i*cols+jp],points[i*cols+jm]);
    Vec value=cross(tv,tu);if(norm(value)<=1.0e-10)value=sub(points[i*cols+j],centroid);
    return af_muscle_unit(value);
}

static std::vector<Vec> af_muscle_normals(const std::vector<Vec>& points,int rows,int cols,bool coherent) {
    std::vector<Vec> out(points.size());Vec centroid=af_muscle_centroid(points);
    for(int i=0;i<rows;++i)for(int j=0;j<cols;++j){int index=i*cols+j;out[index]=af_muscle_normal(points,i,j,rows,cols,centroid);
        if(coherent&&index){Vec ref=j?out[index-1]:out[index-cols];if(dot(out[index],ref)<0.0)out[index]=mul(out[index],-1.0);}}
    return out;
}

static double af_muscle_edge_alpha(int i,int j,int rows,int cols,const AfMuscleInput& input,const AfMuscleOutput* output=nullptr) {
    if(output&&!output->boundary_weights.empty())return output->boundary_weights[i*cols+j];
    bool on_u=j==0||j==cols-1;bool on_v=!input.inflation_closed_v&&(i==0||i==rows-1);if(on_u||on_v)return 0.0;
    int du=cols>1?std::min(j,cols-1-j):0;int dv=input.inflation_closed_v?1000000000:(rows>1?std::min(i,rows-1-i):0);
    double edge=std::clamp(std::min(du,dv)/input.b_band,0.0,1.0);double smooth=edge*edge*(3.0-2.0*edge);
    return (1.0-input.b_strength)+input.b_strength*std::pow(smooth,input.b_power);
}

static double af_muscle_length_fade(int j,int cols,double taper) {
    double band=std::max(1.0,taper*std::max(0,cols-1));double distance=std::min(j,std::max(0,cols-1-j));
    double value=std::clamp(distance/band,0.0,1.0);return value*value*(3.0-2.0*value);
}

static double af_muscle_stability(const std::vector<Vec>& normals,int i,int j,int rows,int cols) {
    double result=1.0;bool found=false;const int offsets[4][2]={{-1,0},{1,0},{0,-1},{0,1}};
    for(auto& offset:offsets){int ii=i+offset[0],jj=j+offset[1];if(ii<0||ii>=rows||jj<0||jj>=cols)continue;
        result=std::min(result,std::max(0.0,dot(normals[i*cols+j],normals[ii*cols+jj])));found=true;}
    return found?result:1.0;
}

static double af_muscle_support(const std::vector<Vec>& points,int i,int j,int rows,int cols) {
    double result=INFINITY;const int offsets[4][2]={{-1,0},{1,0},{0,-1},{0,1}};
    for(auto& offset:offsets){int ii=i+offset[0],jj=j+offset[1];if(ii<0||ii>=rows||jj<0||jj>=cols)continue;
        result=std::min(result,norm(sub(points[ii*cols+jj],points[i*cols+j])));}
    return std::isfinite(result)?result:0.0;
}

static double af_muscle_distributed_amount(const AfMuscleOutput& out,const std::vector<Vec>& normals,const AfMuscleInput& input,int i,int j) {
    double fade=out.length_weights.empty()?af_muscle_length_fade(j,out.cols,input.taper):out.length_weights[i*out.cols+j];
    double raw=input.amount*af_muscle_edge_alpha(i,j,out.rows,out.cols,input,&out)*fade;
    double stable=af_muscle_stability(normals,i,j,out.rows,out.cols);if(raw<=0.0||stable>=0.85)return std::max(0.0,raw);
    double radius=af_muscle_support(out.base,i,j,out.rows,out.cols);double limit=radius>1.0e-8?radius*2.5:0.0;
    return std::min(raw,limit)+(raw-std::min(raw,limit))*std::clamp(stable/0.85,0.0,1.0);
}

static void af_muscle_inflate_distributed(AfMuscleOutput& out,const AfMuscleInput& input) {
    auto normals=af_muscle_normals(out.base,out.rows,out.cols,true);out.inflated=out.base;
    for(int i=0;i<out.rows;++i)for(int j=0;j<out.cols;++j){int index=i*out.cols+j;
        double amount=af_muscle_distributed_amount(out,normals,input,i,j);
        if(amount>0.0)out.inflated[index]=add(out.base[index],mul(normals[index],input.inflation_flip?-amount:amount));}
}

static double af_muscle_falloff(double value,int mode) {
    double x=std::clamp(value,0.0,1.0);if(mode==1)return 1.0-x;
    if(mode==2){double smooth=x*x*(3.0-2.0*x);return 1.0-smooth;}
    return std::exp(-4.0*x*x);
}

static int af_muscle_closest(const std::vector<Vec>& points,Vec control) {
    int best=0;double distance=INFINITY;
    for(int i=0;i<int(points.size());++i){Vec delta=sub(points[i],control);double value=dot(delta,delta);
        if(value<distance){distance=value;best=i;}}
    return best;
}

static void af_muscle_control_point(AfMuscleOutput&,const AfMuscleInput&,Vec,Vec,Vec,int,int);

static void af_muscle_inflate_control(AfMuscleOutput& out,const AfMuscleInput& input) {
    auto normals=af_muscle_normals(out.base,out.rows,out.cols,false);Vec control=input.initialize_control?out.base[(out.rows/2)*out.cols+out.cols/2]:af_vec(input.control);
    Vec n0=normals[af_muscle_closest(out.base,control)];double sign=input.inflation_flip?-1.0:1.0;
    Vec center=sub(control,mul(n0,input.depth*sign));out.inflated=out.base;
    for(int i=0;i<out.rows;++i)for(int j=0;j<out.cols;++j)af_muscle_control_point(out,input,control,n0,center,i,j);
}

static void af_muscle_control_point(AfMuscleOutput& out,const AfMuscleInput& input,Vec control,Vec n0,Vec center,int i,int j) {
    int index=i*out.cols+j;double edge=af_muscle_edge_alpha(i,j,out.rows,out.cols,input,&out);Vec delta=sub(out.base[index],control);
    double ratio=edge>0.0?norm(delta)/input.radius:2.0;if(edge<=0.0||(input.falloff!=0&&ratio>1.0))return;
    double weight=af_muscle_falloff(ratio,input.falloff);if(weight<=1.0e-8)return;Vec direction=sub(out.base[index],center);
    direction=norm(direction)>1.0e-10?af_muscle_unit(direction):n0;out.inflated[index]=add(out.base[index],mul(direction,input.amount*weight*edge));
}

static void af_muscle_inflate(AfMuscleOutput& out,const AfMuscleInput& input) {
    out.inflated=out.base;if(!input.inflation_enabled||input.amount<=0.0)return;
    if(input.inflation_mode==1)af_muscle_inflate_distributed(out,input);else af_muscle_inflate_control(out,input);
}

static void af_muscle_compute(const double* points,int point_count,const AfMuscleInput& input,AfMuscleOutput& out) {
    int required=input.point_start+input.input_rows*input.input_cols;if(input.point_start<0||required>point_count||input.target_cols<2){out.status=1;return;}
    auto sampled=af_muscle_resample(points+3*input.point_start,input);out.cols=input.target_cols;
    out.base=input.densify?af_muscle_densify(sampled,input.input_rows,out.cols,input.closed_u!=0):sampled;
    out.rows=int(out.base.size())/out.cols;if(out.rows<2){out.status=1;return;}
    af_muscle_faces(out,input);af_muscle_inflate(out,input);
}

AF_EXPORT void* af_muscle_batch_create(const double* points,int point_count,const AfMuscleInput* inputs,int count,AfMuscleStats* stats) {
    if(!points||point_count<0||!inputs||count<0||!stats)return nullptr;auto* batch=new AfMuscleBatch();batch->outputs.resize(count);
    int work=0;for(int i=0;i<count;++i)work+=inputs[i].input_rows*inputs[i].target_cols;bool parallel=af_requested_workers>1&&work>=af_muscle_parallel_points;
    auto started=std::chrono::steady_clock::now();
#pragma omp parallel for schedule(static) if(parallel) num_threads(af_requested_workers)
    for(int i=0;i<count;++i)af_muscle_compute(points,point_count,inputs[i],batch->outputs[i]);
    int output=0;for(auto& item:batch->outputs)output+=int(item.base.size());double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    *stats={parallel?af_requested_workers:1,parallel?1:0,count,point_count,output,elapsed};return batch;
}

AF_EXPORT int af_muscle_batch_info(void* handle,int index,int* rows,int* cols,int* faces,int* status) {
    auto* batch=static_cast<AfMuscleBatch*>(handle);if(!batch||index<0||index>=int(batch->outputs.size())||!rows||!cols||!faces||!status)return 1;
    const auto& item=batch->outputs[index];*rows=item.rows;*cols=item.cols;*faces=int(item.faces.size()/4);*status=item.status;return 0;
}

AF_EXPORT int af_muscle_batch_copy(void* handle,int index,double* base,double* inflated,int64_t* faces) {
    auto* batch=static_cast<AfMuscleBatch*>(handle);if(!batch||index<0||index>=int(batch->outputs.size()))return 1;const auto& item=batch->outputs[index];
    if(item.status||(!item.base.empty()&&(!base||!inflated))||(!item.faces.empty()&&!faces))return 2;
    if(base)std::memcpy(base,item.base.data(),item.base.size()*sizeof(Vec));if(inflated)std::memcpy(inflated,item.inflated.data(),item.inflated.size()*sizeof(Vec));
    if(faces)std::memcpy(faces,item.faces.data(),item.faces.size()*sizeof(int64_t));return 0;
}

AF_EXPORT void af_muscle_batch_destroy(void* handle) { delete static_cast<AfMuscleBatch*>(handle); }

AF_EXPORT int af_muscle_set_parallel_threshold(int value) {
    if(value<0)return 1;af_muscle_parallel_points=value;return 0;
}


AF_EXPORT void* af_muscle_prepared_create(const double* points,const AfMuscleInput* input,const double* edge,const double* fade) {
    if(!points||!input||!edge||!fade||input->input_rows<2||input->input_cols<2)return nullptr;
    auto* batch=new AfMuscleBatch();batch->outputs.resize(1);auto& out=batch->outputs[0];
    out.rows=input->input_rows;out.cols=input->input_cols;size_t count=size_t(out.rows)*out.cols;
    auto* source=reinterpret_cast<const Vec*>(points);out.base.assign(source,source+count);
    out.boundary_weights.assign(edge,edge+count);out.length_weights.assign(fade,fade+count);
    af_muscle_faces(out,*input);af_muscle_inflate(out,*input);return batch;
}

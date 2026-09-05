#pragma once

struct AfMat3 { double v[9]; };
struct AfBlockResult { double condition,assembly_ms,factor_ms,solve_ms; int count,valid; };
struct AfContactPair {
    int edge, collider, instance, face, contained;
    double factor, distance, closest[3], normal[3];
};

static AfMat3 af_mzero() { return {{0,0,0,0,0,0,0,0,0}}; }

static AfMat3 af_mload(const double* value) {
    AfMat3 out{}; std::copy(value,value+9,out.v); return out;
}

static AfMat3 af_msub(AfMat3 a,const AfMat3& b) {
    for(int i=0;i<9;++i)a.v[i]-=b.v[i];return a;
}

static AfMat3 af_mtranspose(const AfMat3& a) {
    AfMat3 out{};for(int i=0;i<3;++i)for(int j=0;j<3;++j)out.v[3*i+j]=a.v[3*j+i];return out;
}

static AfMat3 af_mmul(const AfMat3& a,const AfMat3& b) {
    AfMat3 out=af_mzero();for(int i=0;i<3;++i)for(int k=0;k<3;++k)
        for(int j=0;j<3;++j)out.v[3*i+j]+=a.v[3*i+k]*b.v[3*k+j];return out;
}

static Vec af_mvec(const AfMat3& a,Vec b) {
    return {a.v[0]*b.x+a.v[1]*b.y+a.v[2]*b.z,
            a.v[3]*b.x+a.v[4]*b.y+a.v[5]*b.z,
            a.v[6]*b.x+a.v[7]*b.y+a.v[8]*b.z};
}

static double af_mscale(const AfMat3& a) {
    double out=1.0;for(double value:a.v)out=std::max(out,std::abs(value));return out;
}

static double af_mdet(const AfMat3& a) {
    return a.v[0]*(a.v[4]*a.v[8]-a.v[5]*a.v[7])
         - a.v[1]*(a.v[3]*a.v[8]-a.v[5]*a.v[6])
         + a.v[2]*(a.v[3]*a.v[7]-a.v[4]*a.v[6]);
}

static AfMat3 af_madjugate(const AfMat3& a) {
    return {{a.v[4]*a.v[8]-a.v[5]*a.v[7],a.v[2]*a.v[7]-a.v[1]*a.v[8],a.v[1]*a.v[5]-a.v[2]*a.v[4],
             a.v[5]*a.v[6]-a.v[3]*a.v[8],a.v[0]*a.v[8]-a.v[2]*a.v[6],a.v[2]*a.v[3]-a.v[0]*a.v[5],
             a.v[3]*a.v[7]-a.v[4]*a.v[6],a.v[1]*a.v[6]-a.v[0]*a.v[7],a.v[0]*a.v[4]-a.v[1]*a.v[3]}};
}

static bool af_minverse(const AfMat3& a,AfMat3& inverse,double& low,double& high) {
    double scale=af_mscale(a),det=af_mdet(a),minor=a.v[0]*a.v[4]-a.v[1]*a.v[3];
    if(a.v[0]<=eps()*scale||minor<=eps()*scale*scale||det<=eps()*scale*scale*scale)return false;
    inverse=af_madjugate(a);for(double& value:inverse.v)value/=det;
    for(int i=0;i<3;++i)low=std::min(low,a.v[3*i+i]),high=std::max(high,a.v[3*i+i]);return true;
}

struct AfBlockFactor { std::vector<AfMat3> d,inv,l1,l2; double low=INFINITY,high=0.0; };

static AfMat3 af_block_correction(const AfMat3& l,const AfMat3& d) {
    return af_mmul(af_mmul(l,d),af_mtranspose(l));
}

static AfMat3 af_first_lower(const AfBlockFactor& f,const AfMat3& a,int row) {
    if(row<2)return af_mmul(a,f.inv[row-1]);
    AfMat3 cross=af_mmul(af_mmul(f.l2[row],f.d[row-2]),af_mtranspose(f.l1[row-1]));
    return af_mmul(af_msub(a,cross),f.inv[row-1]);
}

static bool af_factor_row(AfBlockFactor& f,const double* diagonal,const double* lower1,
                          const double* lower2,int row) {
    if(row>1)f.l2[row]=af_mmul(af_mload(lower2+9*row),f.inv[row-2]);
    if(row)f.l1[row]=af_first_lower(f,af_mload(lower1+9*row),row);
    AfMat3 pivot=af_mload(diagonal+9*row);
    if(row)pivot=af_msub(pivot,af_block_correction(f.l1[row],f.d[row-1]));
    if(row>1)pivot=af_msub(pivot,af_block_correction(f.l2[row],f.d[row-2]));
    f.d[row]=pivot;return af_minverse(pivot,f.inv[row],f.low,f.high);
}

static bool af_factor_blocks(AfBlockFactor& f,const double* diagonal,const double* lower1,
                             const double* lower2,int count) {
    f.d.resize(count);f.inv.resize(count);f.l1.assign(count,af_mzero());f.l2.assign(count,af_mzero());
    for(int row=0;row<count;++row)if(!af_factor_row(f,diagonal,lower1,lower2,row))return false;
    return true;
}

static std::vector<Vec> af_block_forward(const AfBlockFactor& f,const double* rhs) {
    std::vector<Vec> out(f.d.size());
    for(int i=0;i<int(out.size());++i){out[i]=load3(rhs+3*i);if(i)out[i]=sub(out[i],af_mvec(f.l1[i],out[i-1]));
        if(i>1)out[i]=sub(out[i],af_mvec(f.l2[i],out[i-2]));}return out;
}

static void af_block_backward(const AfBlockFactor& f,std::vector<Vec>& values) {
    for(int i=int(values.size())-1;i>=0;--i){if(i+1<int(values.size()))values[i]=sub(values[i],af_mvec(af_mtranspose(f.l1[i+1]),values[i+1]));
        if(i+2<int(values.size()))values[i]=sub(values[i],af_mvec(af_mtranspose(f.l2[i+2]),values[i+2]));}
}

AF_EXPORT int af_block_pentadiagonal_solve(const double* diagonal,const double* lower1,
                                            const double* lower2,const double* rhs,int count,
                                            double* output,AfBlockResult* result) {
    if(!diagonal||!lower1||!lower2||!rhs||!output||!result||count<1)return 1;
    auto factor_start=std::chrono::steady_clock::now();AfBlockFactor factor;
    if(!af_factor_blocks(factor,diagonal,lower1,lower2,count)){*result={INFINITY,0,0,0,count,0};return 0;}
    double factor_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-factor_start).count();auto solve_start=std::chrono::steady_clock::now();
    auto values=af_block_forward(factor,rhs);for(int i=0;i<count;++i)values[i]=af_mvec(factor.inv[i],values[i]);
    af_block_backward(factor,values);for(int i=0;i<count;++i){output[3*i]=values[i].x;output[3*i+1]=values[i].y;output[3*i+2]=values[i].z;}
    double solve_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-solve_start).count();
    *result={factor.high/std::max(factor.low,eps()),0,factor_ms,solve_ms,count,1};return 0;
}

static AfMat3 af_midentity(double value) {
    AfMat3 out=af_mzero();out.v[0]=out.v[4]=out.v[8]=value;return out;
}

static void af_mouter_add(AfMat3& out,Vec a,Vec b,double scale) {
    const double* x=&a.x;const double* y=&b.x;
    for(int i=0;i<3;++i)for(int j=0;j<3;++j)out.v[3*i+j]+=scale*x[i]*y[j];
}

static void af_rhs_add(Vec& rhs,Vec jacobian,double value) {
    rhs=add(rhs,mul(jacobian,value));
}

static void af_add_contact(std::vector<AfMat3>& diagonal,std::vector<AfMat3>& lower1,
                           std::vector<Vec>& rhs,const double* current,int edge,double factor,
                           Vec normal,double gap,double multiplier,double mu) {
    Vec first=mul(normal,1.0-factor),second=mul(normal,factor);double s=std::max(0.0,multiplier-mu*gap);
    if(s<=0.0)return;
    Vec x0=load3(current+3*edge),x1=load3(current+3*edge+3);double projected=dot(first,x0)+dot(second,x1);
    af_mouter_add(diagonal[edge],first,first,mu);af_mouter_add(diagonal[edge+1],second,second,mu);
    af_mouter_add(lower1[edge+1],second,first,mu);af_rhs_add(rhs[edge],first,mu*projected+s);af_rhs_add(rhs[edge+1],second,mu*projected+s);
}

static AfMat3& af_band(std::vector<AfMat3>& diagonal,std::vector<AfMat3>& lower1,
                       std::vector<AfMat3>& lower2,int row,int column) {
    int distance=std::abs(row-column),high=std::max(row,column);
    return distance==0?diagonal[row]:distance==1?lower1[high]:lower2[high];
}

static void af_eliminate_pin(std::vector<AfMat3>& diagonal,std::vector<AfMat3>& lower1,
                             std::vector<AfMat3>& lower2,std::vector<Vec>& rhs,
                             const std::vector<char>& pinned,int pin,Vec target) {
    for(int row=std::max(0,pin-2);row<=std::min(int(rhs.size())-1,pin+2);++row){if(row!=pin&&!pinned[row])rhs[row]=sub(rhs[row],af_mvec(row>pin?af_band(diagonal,lower1,lower2,row,pin):af_mtranspose(af_band(diagonal,lower1,lower2,pin,row)),target));
        if(row!=pin)af_band(diagonal,lower1,lower2,row,pin)=af_mzero();}
    diagonal[pin]=af_midentity(1.0);rhs[pin]=target;
}

static void af_apply_pins(std::vector<AfMat3>& diagonal,std::vector<AfMat3>& lower1,
                          std::vector<AfMat3>& lower2,std::vector<Vec>& rhs,
                          const int64_t* pins,const double* targets,int pin_count) {
    std::vector<char> mask(rhs.size(),0);for(int i=0;i<pin_count;++i)mask[pins[i]]=1;
    for(int i=0;i<pin_count;++i)af_eliminate_pin(diagonal,lower1,lower2,rhs,mask,int(pins[i]),load3(targets+3*i));
}

static bool af_contact_inputs(int count,const int64_t* edges,int contacts,const int64_t* pins,int pin_count) {
    if(count<2||contacts<0||pin_count<0)return false;
    for(int i=0;i<contacts;++i)if(edges[i]<0||edges[i]+1>=count)return false;
    for(int i=0;i<pin_count;++i)if(pins[i]<0||pins[i]>=count)return false;return true;
}

AF_EXPORT int af_contact_block_solve(const double* base_diagonal,const double* base_lower1,
                                      const double* base_lower2,const double* base_rhs,
                                      const double* current,const int64_t* edges,const double* factors,
                                      const double* normals,const double* gaps,const double* multipliers,
                                      int contacts,double mu,const int64_t* pins,const double* targets,
                                      int pin_count,int count,double* output,AfBlockResult* result) {
    if(!base_diagonal||!base_lower1||!base_lower2||!base_rhs||!current||!output||!result||
       !af_contact_inputs(count,edges,contacts,pins,pin_count))return 1;auto started=std::chrono::steady_clock::now();
    std::vector<AfMat3> diagonal(count),lower1(count),lower2(count);std::vector<Vec> rhs(count);
    for(int i=0;i<count;++i){diagonal[i]=af_midentity(base_diagonal[i]);lower1[i]=af_midentity(base_lower1[i]);lower2[i]=af_midentity(base_lower2[i]);rhs[i]=load3(base_rhs+3*i);}
    for(int i=0;i<contacts;++i)af_add_contact(diagonal,lower1,rhs,current,int(edges[i]),factors[i],load3(normals+3*i),gaps[i],multipliers[i],mu);
    af_apply_pins(diagonal,lower1,lower2,rhs,pins,targets,pin_count);double assembly=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    int code=af_block_pentadiagonal_solve(reinterpret_cast<double*>(diagonal.data()),reinterpret_cast<double*>(lower1.data()),reinterpret_cast<double*>(lower2.data()),reinterpret_cast<double*>(rhs.data()),count,output,result);
    result->assembly_ms=assembly;return code;
}

static std::vector<Vec> af_solve_factor(const AfBlockFactor& factor,std::vector<Vec> rhs) {
    for(int i=0;i<int(rhs.size());++i){if(i)rhs[i]=sub(rhs[i],af_mvec(factor.l1[i],rhs[i-1]));
        if(i>1)rhs[i]=sub(rhs[i],af_mvec(factor.l2[i],rhs[i-2]));}
    for(int i=0;i<int(rhs.size());++i)rhs[i]=af_mvec(factor.inv[i],rhs[i]);
    af_block_backward(factor,rhs);return rhs;
}

static std::vector<Vec> af_response_rhs(int count,int edge,double factor,Vec normal,
                                        const std::vector<char>& pinned) {
    std::vector<Vec> rhs(count,Vec{0,0,0});
    if(!pinned[edge])rhs[edge]=mul(normal,1.0-factor);
    if(!pinned[edge+1])rhs[edge+1]=mul(normal,factor);return rhs;
}

static void af_write_vectors(const std::vector<Vec>& rows,double* output) {
    for(int i=0;i<int(rows.size());++i){output[3*i]=rows[i].x;output[3*i+1]=rows[i].y;output[3*i+2]=rows[i].z;}
}

AF_EXPORT int af_structural_contact_responses(const double* base_diagonal,const double* base_lower1,
        const double* base_lower2,const double* base_rhs,const int64_t* edges,const double* factors,
        const double* normals,int contacts,const int64_t* pins,const double* targets,int pin_count,
        int count,double* base_output,double* responses,AfBlockResult* result) {
    if(!base_diagonal||!base_lower1||!base_lower2||!base_rhs||!base_output||!responses||!result||
       !af_contact_inputs(count,edges,contacts,pins,pin_count))return 1;auto started=std::chrono::steady_clock::now();
    std::vector<AfMat3> d(count),l1(count),l2(count);std::vector<Vec> rhs(count);std::vector<char> mask(count,0);
    for(int i=0;i<count;++i){d[i]=af_midentity(base_diagonal[i]);l1[i]=af_midentity(base_lower1[i]);l2[i]=af_midentity(base_lower2[i]);rhs[i]=load3(base_rhs+3*i);}for(int i=0;i<pin_count;++i)mask[pins[i]]=1;
    af_apply_pins(d,l1,l2,rhs,pins,targets,pin_count);AfBlockFactor factor;if(!af_factor_blocks(factor,reinterpret_cast<double*>(d.data()),reinterpret_cast<double*>(l1.data()),reinterpret_cast<double*>(l2.data()),count)){*result={INFINITY,0,0,0,count,0};return 0;}
    auto base=af_solve_factor(factor,rhs);af_write_vectors(base,base_output);for(int i=0;i<contacts;++i){auto row=af_response_rhs(count,int(edges[i]),factors[i],load3(normals+3*i),mask);row=af_solve_factor(factor,row);af_write_vectors(row,responses+3*count*i);}
    double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();*result={factor.high/std::max(factor.low,eps()),0,0,elapsed,count,1};return 0;
}

static Vec af_pair_normal(const AfInstance& item,const AfSegmentPair& pair,bool inside) {
    Vec direction=inside?sub(pair.surface,pair.line):sub(pair.line,pair.surface);
    Vec normal=af_unit(direction);return norm(normal)>eps()?normal:af_unit(pair.normal);
}

static void af_write_contact(AfContactPair& out,int edge,const AfInstance& item,int instance,
                             int face,const AfSegmentPair& pair,bool inside,double factor) {
    Vec normal=af_pair_normal(item,pair,inside);out={edge,item.collider,instance,face,int(inside),factor,pair.distance,
        {pair.surface.x,pair.surface.y,pair.surface.z},{normal.x,normal.y,normal.z}};
}

static void af_append_face_contacts(const AfInstance& item,int instance,int edge,Vec a,Vec b,
                                    double low,double high,double threshold,std::vector<AfContactPair>& rows,
                                    AfContactResult& result) {
    Vec la=af_transform(item.inverse,a),lb=af_transform(item.inverse,b);std::vector<int> faces;
    if(!item.mesh->nodes.empty())collect_candidates(*item.mesh,0,af_segment_bounds(la,lb,af_inverse_padding(item,threshold)),faces);
    result.candidates+=int(faces.size());for(int face:faces){Vec triangle[3];af_world_face(item,face,triangle);
        auto pair=af_closest_segment_face(a,b,triangle,instance);++result.tested;if(pair.distance>=threshold)continue;
        AfContactPair out{};double factor=low+(high-low)*pair.factor;af_write_contact(out,edge,item,instance,face,pair,af_inside_instance(item,pair.line),factor);rows.push_back(out);}
}

static void af_append_contained(const AfInstance& item,int instance,int edge,Vec point,double factor,
                                std::vector<AfContactPair>& rows,AfContactResult& result) {
    if(!af_inside_instance(item,point))return;AfNearest nearest{{},{},INFINITY,-1};af_nearest_item(item,instance,point,nearest);
    AfSegmentPair pair{point,nearest.point,nearest.face_normal,nearest.distance,factor,instance};AfContactPair out{};
    af_write_contact(out,edge,item,instance,-1,pair,true,factor);rows.push_back(out);++result.contained;
}

static void af_collect_edge_contacts(const AfWorld& world,int edge,Vec a,Vec b,int first,int second,
                                      int only,int skip,double span,double threshold,
                                      std::vector<AfContactPair>& rows,AfContactResult& result) {
    std::vector<int> hits;if(!world.nodes.empty())af_collect_world(world,0,af_segment_bounds(a,b,threshold),hits);
    for(int index:hits){const auto& item=world.items[index];if(!af_contact_filter(item,only,skip))continue;
        auto range=af_test_range(a,b,item,first,second,span);if(range.first>=range.second)continue;
        Vec low=add(a,mul(sub(b,a),range.first)),high=add(a,mul(sub(b,a),range.second));
        af_append_face_contacts(item,index,edge,low,high,range.first,range.second,threshold,rows,result);}
    for(int index=0;index<int(world.items.size());++index){const auto& item=world.items[index];if(!af_contact_filter(item,only,skip))continue;
        if(first!=item.owner)af_append_contained(item,index,edge,a,0.0,rows,result);if(second!=item.owner)af_append_contained(item,index,edge,b,1.0,rows,result);}
}

struct AfPairRows { std::vector<AfContactPair> rows; AfContactResult result{0,0,0,0,INFINITY}; };

static AfPairRows af_pair_rows(const AfWorld& world,int edge,Vec a,Vec b,int first,int second,
                               int only,int skip,double span,double threshold) {
    AfPairRows out;af_collect_edge_contacts(world,edge,a,b,first,second,only,skip,span,threshold,out.rows,out.result);return out;
}

static void af_merge_pair_rows(std::vector<AfContactPair>& rows,AfContactResult& result,AfPairRows& batch) {
    result.candidates+=batch.result.candidates;result.tested+=batch.result.tested;
    result.contained+=batch.result.contained;rows.insert(rows.end(),batch.rows.begin(),batch.rows.end());
}

AF_EXPORT int af_world_query_contact_pairs(void* handle,const double* points,const int64_t* edges,
                                             const int* first,const int* second,const int* only,const int* skip,
                                             int count,double span,double threshold,AfContactPair* output,
                                             int capacity,AfContactResult* result) {
    if(!handle||!points||!edges||!first||!second||!only||!skip||!result||count<0||capacity<0)return -1;
    const auto& world=*static_cast<AfWorld*>(handle);std::vector<AfContactPair> rows;std::vector<AfPairRows> batches(count);*result={0,0,0,0,INFINITY};
#pragma omp parallel for schedule(static) if(af_parallel_batch(count)) num_threads(af_parallel_workers(count))
    for(int i=0;i<count;++i)batches[i]=af_pair_rows(world,i,load3(points+3*edges[2*i]),load3(points+3*edges[2*i+1]),
        first[i],second[i],only[i],skip[i],span,threshold);
    for(auto& batch:batches)af_merge_pair_rows(rows,*result,batch);
    std::stable_sort(rows.begin(),rows.end(),[](const auto& a,const auto& b){return std::tie(a.edge,a.collider,a.face,a.factor)<std::tie(b.edge,b.collider,b.face,b.factor);});
    result->active=int(rows.size());result->minimum=INFINITY;for(const auto& row:rows)result->minimum=std::min(result->minimum,row.distance);
    if(output&&capacity<int(rows.size()))return -2;if(output)std::copy(rows.begin(),rows.end(),output);return int(rows.size());
}

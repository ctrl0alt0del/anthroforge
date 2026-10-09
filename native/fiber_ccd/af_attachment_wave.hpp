#pragma once

constexpr int AF_ATTACHMENT_WAVE_CAPABILITY=33554432;
constexpr int AF_ATTACHMENT_PARALLEL_COST=256;

struct AfAttachmentSurface {
    int owner,vertex_start,vertex_count;
    double relative[16],rotation[9];
};

struct AfAttachmentScpOp {
    int child,parent,surface,depth,mode,follow,backsolve,back_parent;
    int64_t tri[3],flow_tri[3];
    double weights[3],flow_weights[3],hint[3],offset[3],origin[3];
    double child_tangent[3],child_normal[3],scale[3],parent_local[3],anchor_local[3];
};

struct AfAttachmentFiberOp {
    int fiber,node,owner,surface,output;
    int64_t tri[3];
    double weights[3],offset[3];
};

struct AfAttachmentStats {
    int workers,parallel,cost,scp_operations,fiber_operations,waves;
    double elapsed_ms;
};

struct AfBasis { Vec tangent,bitangent,normal; };

static Vec af_vec(const double* value) { return {value[0],value[1],value[2]}; }
static void af_store(Vec value,double* out) { out[0]=value.x;out[1]=value.y;out[2]=value.z; }
static bool af_finite(Vec value) { return std::isfinite(value.x)&&std::isfinite(value.y)&&std::isfinite(value.z); }

static Vec af_unit(Vec value,Vec fallback) {
    double length=norm(value);if(length<=1.0e-6)value=fallback,length=norm(value);
    return length<=1.0e-12?Vec{1,0,0}:mul(value,1.0/length);
}

static Vec af_project(Vec value,Vec normal) { return sub(value,mul(normal,dot(value,normal))); }

static Vec af_transform_point(const double* matrix,Vec value) {
    return {matrix[0]*value.x+matrix[1]*value.y+matrix[2]*value.z+matrix[3],
            matrix[4]*value.x+matrix[5]*value.y+matrix[6]*value.z+matrix[7],
            matrix[8]*value.x+matrix[9]*value.y+matrix[10]*value.z+matrix[11]};
}

static Vec af_transform3(const double* matrix,Vec value) {
    return {matrix[0]*value.x+matrix[1]*value.y+matrix[2]*value.z,
            matrix[3]*value.x+matrix[4]*value.y+matrix[5]*value.z,
            matrix[6]*value.x+matrix[7]*value.y+matrix[8]*value.z};
}

static void af_multiply4(const double* left,const double* right,double* out) {
    for(int row=0;row<4;++row)for(int col=0;col<4;++col){double value=0.0;
        for(int k=0;k<4;++k)value+=left[4*row+k]*right[4*k+col];out[4*row+col]=value;}
}

static void af_multiply3(const double* left,const double* right,double* out) {
    for(int row=0;row<3;++row)for(int col=0;col<3;++col){double value=0.0;
        for(int k=0;k<3;++k)value+=left[3*row+k]*right[3*k+col];out[3*row+col]=value;}
}

static Vec af_basis_apply(const AfBasis& basis,Vec value) {
    return add(add(mul(basis.tangent,value.x),mul(basis.bitangent,value.y)),mul(basis.normal,value.z));
}

static AfBasis af_basis(Vec tangent,Vec normal) {
    Vec t=af_unit(tangent,{1,0,0});Vec n=af_project(normal,t);
    Vec axis=std::abs(t.z)<=0.99?Vec{0,0,1}:Vec{0,1,0};n=af_unit(n,af_project(axis,t));
    Vec b=af_unit(cross(n,t),{0,1,0});t=af_unit(cross(b,n),{1,0,0});return {t,b,n};
}

static void af_basis_matrix(const AfBasis& basis,double* out) {
    out[0]=basis.tangent.x;out[1]=basis.bitangent.x;out[2]=basis.normal.x;
    out[3]=basis.tangent.y;out[4]=basis.bitangent.y;out[5]=basis.normal.y;
    out[6]=basis.tangent.z;out[7]=basis.bitangent.z;out[8]=basis.normal.z;
}

static bool af_triangle(const double* vertices,int count,const int64_t* tri,const double* matrix,Vec* out) {
    for(int i=0;i<3;++i){if(tri[i]<0||tri[i]>=count)return false;
        out[i]=af_transform_point(matrix,af_vec(vertices+3*tri[i]));}return true;
}

static Vec af_weighted(const Vec* values,const double* weights) {
    return add(add(mul(values[0],weights[0]),mul(values[1],weights[1])),mul(values[2],weights[2]));
}

static Vec af_hint_fallback(const double* rotation,Vec normal) {
    Vec tangent=af_project(af_transform3(rotation,{1,0,0}),normal);
    return norm(tangent)>1.0e-6?tangent:af_project(af_transform3(rotation,{0,1,0}),normal);
}

static Vec af_scp_tangent(const AfAttachmentScpOp& op,const Vec* tri,Vec point,Vec normal,
                          const double* vertices,int count,const double* matrix,const double* rotation) {
    Vec flow[3];bool valid=op.mode==1&&af_triangle(vertices,count,op.flow_tri,matrix,flow);
    Vec value=valid?af_project(sub(af_weighted(flow,op.flow_weights),point),normal):Vec{0,0,0};
    if(valid&&norm(value)>1.0e-6)return af_unit(value,sub(tri[1],tri[0]));
    return af_unit(af_project(af_transform3(rotation,af_vec(op.hint)),normal),af_hint_fallback(rotation,normal));
}

static bool af_surface_frame(const AfAttachmentSurface& surface,const double* vertices,const double* matrices,
                             const double* rotations,const int64_t* tri,const double* weights,AfBasis& basis,Vec& point) {
    double matrix[16],rotation[9];af_multiply4(matrices+16*surface.owner,surface.relative,matrix);
    af_multiply3(rotations+9*surface.owner,surface.rotation,rotation);Vec abc[3];
    if(!af_triangle(vertices+3*surface.vertex_start,surface.vertex_count,tri,matrix,abc))return false;
    Vec normal=cross(sub(abc[1],abc[0]),sub(abc[2],abc[0]));if(norm(normal)<=1.0e-12)return false;
    point=af_weighted(abc,weights);basis=af_basis(sub(abc[1],abc[0]),normal);return true;
}

static bool af_scp_frame(const AfAttachmentScpOp& op,const AfAttachmentSurface* surfaces,const double* vertices,
                         const double* matrices,const double* rotations,AfBasis& basis,Vec& point) {
    if(op.surface<0){point={matrices[16*op.parent+3],matrices[16*op.parent+7],matrices[16*op.parent+11]};
        basis=af_basis(af_transform3(rotations+9*op.parent,{1,0,0}),af_transform3(rotations+9*op.parent,{0,0,1}));return true;}
    const auto& surface=surfaces[op.surface];double matrix[16],rotation[9];
    af_multiply4(matrices+16*surface.owner,surface.relative,matrix);af_multiply3(rotations+9*surface.owner,surface.rotation,rotation);
    Vec abc[3];if(!af_triangle(vertices+3*surface.vertex_start,surface.vertex_count,op.tri,matrix,abc))return false;
    point=af_weighted(abc,op.weights);Vec normal=cross(sub(abc[1],abc[0]),sub(abc[2],abc[0]));
    basis=af_basis(af_scp_tangent(op,abc,point,normal,vertices+3*surface.vertex_start,surface.vertex_count,matrix,rotation),normal);return true;
}

static void af_rotation_from_basis(const AfBasis& parent,const AfAttachmentScpOp& op,double* rotation) {
    double world[9],local[9];af_basis_matrix(parent,world);af_basis_matrix(af_basis(af_vec(op.child_tangent),af_vec(op.child_normal)),local);
    for(int row=0;row<3;++row)for(int col=0;col<3;++col){rotation[3*row+col]=0.0;
        for(int k=0;k<3;++k)rotation[3*row+col]+=world[3*row+k]*local[3*col+k];}
}

static void af_compose(Vec position,const double* rotation,const double* scale,double* matrix) {
    for(int row=0;row<3;++row)for(int col=0;col<3;++col)matrix[4*row+col]=rotation[3*row+col]*scale[col];
    matrix[3]=position.x;matrix[7]=position.y;matrix[11]=position.z;
    matrix[12]=matrix[13]=matrix[14]=0.0;matrix[15]=1.0;
}

static bool af_run_scp(const AfAttachmentScpOp& op,const AfAttachmentSurface* surfaces,const double* vertices,
                       double* matrices,double* rotations,const int* status) {
    if(status[op.parent]!=0)return false;AfBasis basis;Vec point;if(!af_scp_frame(op,surfaces,vertices,matrices,rotations,basis,point))return false;
    double* matrix=matrices+16*op.child;double* rotation=rotations+9*op.child;double updated[9];
    if(op.follow)af_rotation_from_basis(basis,op,updated);else std::copy(rotation,rotation+9,updated);
    Vec scaled={op.origin[0]*op.scale[0],op.origin[1]*op.scale[1],op.origin[2]*op.scale[2]};
    Vec position=sub(add(point,af_basis_apply(basis,af_vec(op.offset))),af_transform3(updated,scaled));
    if(op.follow)af_compose(position,updated,op.scale,matrix);
    else matrix[3]=position.x,matrix[7]=position.y,matrix[11]=position.z;
    std::copy(updated,updated+9,rotation);return af_finite(position);
}

static void af_apply_backsolve(const AfAttachmentScpOp& op,double* matrices) {
    if(!op.backsolve)return;double* matrix=matrices+16*op.child;const double* parent=matrices+16*op.back_parent;
    Vec target=af_transform_point(parent,af_vec(op.parent_local));Vec anchor=af_transform_point(matrix,af_vec(op.anchor_local));
    Vec delta=sub(target,anchor);matrix[3]+=delta.x;matrix[7]+=delta.y;matrix[11]+=delta.z;
}

static bool af_run_fiber(const AfAttachmentFiberOp& op,const AfAttachmentSurface* surfaces,const double* vertices,
                         const double* matrices,const double* rotations,double* output) {
    if(op.surface<0)return false;AfBasis basis;Vec point;
    if(!af_surface_frame(surfaces[op.surface],vertices,matrices,rotations,op.tri,op.weights,basis,point))return false;
    point=add(point,af_basis_apply(basis,af_vec(op.offset)));af_store(point,output+3*op.output);return af_finite(point);
}

static bool af_attachment_parallel(int cost) { return af_requested_workers>1&&cost>=AF_ATTACHMENT_PARALLEL_COST; }

AF_EXPORT int af_attachment_wave_execute(double* matrices,double* rotations,int scp_count,const double* vertices,int vertex_count,
    const AfAttachmentSurface* surfaces,int surface_count,const AfAttachmentScpOp* scp_ops,int scp_op_count,const int* wave_offsets,int wave_count,
    const AfAttachmentFiberOp* fiber_ops,int fiber_op_count,double* fiber_points,int* scp_status,int* fiber_status,int force_serial,AfAttachmentStats* stats) {
    if(scp_count<0||vertex_count<0||surface_count<0||scp_op_count<0||wave_count<0||fiber_op_count<0||!stats)return 1;
    if(scp_count&&(!matrices||!rotations||!scp_status))return 1;
    if(vertex_count&&!vertices||surface_count&&!surfaces||scp_op_count&&!scp_ops||wave_count&&!wave_offsets)return 1;
    if(fiber_op_count&&(!fiber_ops||!fiber_points||!fiber_status))return 1;
    int cost=16*scp_op_count+fiber_op_count;bool parallel=!force_serial&&af_attachment_parallel(cost);auto started=std::chrono::steady_clock::now();
#pragma omp parallel if(parallel) num_threads(af_requested_workers)
    {for(int wave=0;wave<wave_count;++wave){int first=wave_offsets[wave],last=wave_offsets[wave+1];
#pragma omp for schedule(static)
        for(int i=first;i<last;++i){const auto& op=scp_ops[i];bool ok=op.child>=0&&op.child<scp_count&&op.parent>=0&&op.parent<scp_count&&scp_status[op.child]==0;
            ok=ok&&op.surface<surface_count&&af_run_scp(op,surfaces,vertices,matrices,rotations,scp_status);scp_status[op.child]=ok?0:1;if(ok)af_apply_backsolve(op,matrices);}}
#pragma omp for schedule(static,64)
    for(int i=0;i<fiber_op_count;++i){const auto& op=fiber_ops[i];bool ok=op.owner>=0&&op.owner<scp_count&&scp_status[op.owner]==0;
        ok=ok&&op.surface>=0&&op.surface<surface_count&&af_run_fiber(op,surfaces,vertices,matrices,rotations,fiber_points);fiber_status[i]=ok?0:1;}}
    auto elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    *stats={parallel?af_requested_workers:1,parallel?1:0,cost,scp_op_count,fiber_op_count,wave_count,elapsed};return 0;
}

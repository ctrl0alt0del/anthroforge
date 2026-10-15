#pragma once
#include <fstream>
namespace af_ad {
inline std::filesystem::path weight_path(const State& s,int count) {
    uint64_t hash=14695981039346656037ULL;
    auto add=[&](const void* data,size_t bytes){auto p=static_cast<const unsigned char*>(data);
        for(size_t i=0;i<bytes;++i){hash^=p[i];hash*=1099511628211ULL;}};
    add(s.rest.data(),s.rest.size()*sizeof(double));add(s.tets.data(),s.tets.size()*sizeof(int));add(&count,sizeof(count));
    return std::filesystem::path(s.cancel).parent_path()/("bbw_v1_"+std::to_string(hash)+".bin");
}
inline bool read_weights(const std::filesystem::path& path,M& weights) {
    std::ifstream file(path,std::ios::binary);if(!file)return false;
    auto bytes=weights.size()*sizeof(double);if(std::filesystem::file_size(path)!=bytes)return false;
    file.read(reinterpret_cast<char*>(weights.data()),bytes);
    return bool(file)&&weights.allFinite()&&weights.minCoeff()>=-1e-6&&weights.rowwise().sum().minCoeff()>0;
}
inline void bbw_weights(State& s,int count) {
    auto path=weight_path(s,count);
    if(read_weights(path,s.weights)){std::printf("BBW_CACHE_HIT\n");return;}
    igl::BBWData settings;settings.active_set_params.max_iter=30;settings.verbosity=0;M bc=M::Identity(count,count);
    if(!igl::bbw(s.rest,s.tets,s.handles,bc,settings,s.weights))throw std::runtime_error("BBW_FAILED");
    for(int i=0;i<s.weights.rows();++i)s.weights.row(i)/=s.weights.row(i).sum();
    std::ofstream file(path,std::ios::binary);file.write(reinterpret_cast<const char*>(s.weights.data()),s.weights.size()*sizeof(double));
    if(!file)throw std::runtime_error("BBW_CACHE_WRITE_FAILED");
}
inline void adjacency(State& s) {
    std::set<std::pair<int,int>> edges;
    for(int i=0;i<s.tets.rows();++i)for(int a=0;a<4;++a)for(int b=a+1;b<4;++b)edges.insert(std::minmax(s.tets(i,a),s.tets(i,b)));
    s.edges.resize(s.rest.rows());
    for(auto [a,b]:edges){double d=(s.rest.row(a)-s.rest.row(b)).norm();s.edges[a].emplace_back(b,d);s.edges[b].emplace_back(a,d);}
}
inline V distances(const State& s,int start) {
    V result=V::Constant(s.rest.rows(),INFINITY);result[start]=0;
    using Pair=std::pair<double,int>; std::priority_queue<Pair,std::vector<Pair>,std::greater<Pair>> queue;queue.emplace(0,start);
    while(!queue.empty()) {
        auto [distance,a]=queue.top();queue.pop();if(distance>result[a])continue;
        for(auto [b,length]:s.edges[a])if(distance+length<result[b]){result[b]=distance+length;queue.emplace(result[b],b);}
    }
    return result;
}
inline M handles(State& s,int count) {
    adjacency(s); count=std::min(count,int(s.rest.rows()));s.handles.resize(count);M d(s.rest.rows(),count);
    V nearest=V::Constant(s.rest.rows(),INFINITY);int chosen=0;
    for(int j=0;j<count;++j){check(s);s.handles[j]=chosen;d.col(j)=distances(s,chosen);nearest=nearest.cwiseMin(d.col(j));nearest.maxCoeff(&chosen);}
    if(!nearest.allFinite())throw std::runtime_error("INSUFFICIENT_HANDLES_FOR_PROXY_COMPONENTS");
    s.controls=s.rest(s.handles,Eigen::all);return d;
}
inline M graph_weights(const M& distances) {
    M weights=M::Zero(distances.rows(),distances.cols());
    for(int i=0;i<weights.rows();++i) {
        std::vector<std::pair<double,int>> order;for(int j=0;j<weights.cols();++j)order.emplace_back(distances(i,j),j);
        std::partial_sort(order.begin(),order.begin()+5,order.end());double radius=order[4].first;
        if(!std::isfinite(radius))radius=order[0].first+1;
        for(int k=0;k<4;++k)weights(i,order[k].second)=std::pow(std::max(0.,1-order[k].first/std::max(radius,1e-15)),2);
        weights.row(i)/=weights.row(i).sum();
    }
    return weights;
}
inline V identity(int h) {
    V result=V::Zero(12*h);for(int d=0;d<3;++d)for(int j=0;j<h;++j)result[d*h+d*3*h+j]=1;return result;
}
inline S skinning_matrix(const M& points,const M& weights) {
    int n=points.rows(),h=weights.cols();std::vector<T> entries;
    for(int i=0;i<n;++i)for(int j=0;j<h;++j)if(weights(i,j)!=0)
        for(int x=0;x<3;++x)for(int c=0;c<4;++c)entries.emplace_back(x*n+i,x*h+c*3*h+j,weights(i,j)*(c<3?points(i,c):1.));
    S result(3*n,12*h);result.setFromTriplets(entries.begin(),entries.end());return result;
}
inline void basis(State& s,int count) {
    M d=handles(s,count); s.weights=graph_weights(d);std::printf("PREP_STAGE handles\n");std::fflush(stdout);
    if(s.method==2)bbw_weights(s,count);
    s.groups.resize(s.rest.rows());for(int i=0;i<s.groups.size();++i)s.weights.row(i).maxCoeff(&s.groups[i]);
    std::printf("PREP_STAGE weights\n");std::fflush(stdout);
    s.lbs=skinning_matrix(s.rest,s.weights);s.reduced_constraints=s.block*s.lbs;s.identity=identity(count);
}
inline S graph_penalty(State& s) {
    int h=s.controls.rows(),row=0;std::set<std::pair<int,int>> edges;std::vector<T> entries;
    for(int i=0;i<s.rest.rows();++i)for(auto [j,length]:s.edges[i])if(s.groups[i]!=s.groups[j])edges.insert(std::minmax(s.groups[i],s.groups[j]));
    double scale=1/std::sqrt(double(std::max<size_t>(1,edges.size())));
    for(auto [a,b]:edges)for(int x=0;x<3;++x,++row)for(int c=0;c<4;++c){double v=scale*(c<3?s.controls(b,c):1.);
        entries.emplace_back(row,x*h+c*3*h+a,v);entries.emplace_back(row,x*h+c*3*h+b,-v);}
    double rotation_scale=.1/std::sqrt(double(h));
    for(int c=0;c<3;++c)for(int x=0;x<3;++x)for(int j=0;j<h;++j)entries.emplace_back(row++,x*h+c*3*h+j,rotation_scale);
    S result(row,12*h);result.setFromTriplets(entries.begin(),entries.end());return result;
}
inline void reduced_prepare(State& s,int count) {
    basis(s,count);S normal=s.reduced_constraints.transpose()*s.reduced_constraints;
    if(s.method==2){s.fast.energy=igl::ARAP_ENERGY_TYPE_ELEMENTS;s.fast.effective_dim=3;s.fast.print_timings=false;
        if(!igl::arap_dof_precomputation(s.rest,s.tets,s.lbs,s.groups,s.fast))throw std::runtime_error("FAST_PRECOMPUTE_FAILED");
        s.reduced_hessian=M(s.fast.Q)+s.lambda*M(normal);}
    else {s.stiffness=graph_penalty(s);s.reduced_hessian=M(s.stiffness.transpose()*s.stiffness)+s.lambda*M(normal);}
    s.reduced_hessian.diagonal().array()+=1e-10;s.reduced_factor.compute(s.reduced_hessian);
    if(s.reduced_factor.info()!=Eigen::Success)throw std::runtime_error("REDUCED_FACTORIZATION_FAILED");
}
inline V graph_rhs(State& s,const V& x) {
    int h=s.controls.rows();V rhs=V::Zero(s.stiffness.rows());int first=rhs.size()-9*h;
    for(int j=0;j<h;++j){R3 a;for(int c=0;c<3;++c)for(int d=0;d<3;++d)a(d,c)=x[d*h+c*3*h+j];
        R3 r=rotation(a);for(int c=0;c<3;++c)for(int d=0;d<3;++d)rhs[first+c*3*h+d*h+j]=.1/std::sqrt(double(h))*r(d,c);}
    return s.stiffness.transpose()*rhs;
}
inline V fast_rhs(State& s,const V& x) {
    M covariance(s.fast.CSM_M[0].rows(),3),rotations;V column;
    for(int j=0;j<3;++j)covariance.col(j)=s.fast.CSM_M[j]*x;
    igl::fit_rotations(covariance,false,rotations);igl::columnize(rotations,int(rotations.cols()/3),2,column);
    return -.5*(s.fast.M_KG*column);
}
inline M reduced_solve(State& s,const M& delta) {
    M target=s.sample_weights.cwiseSqrt().asDiagonal()*(s.constraints*s.rest+delta);
    V constant=s.lambda*(s.reduced_constraints.transpose()*vector(target))+1e-10*s.identity,x=s.identity;
    for(int i=0;i<80;++i){check(s);V rhs=s.method==2?fast_rhs(s,x):graph_rhs(s,x);V next=s.reduced_factor.solve(rhs+constant);
        if(!next.allFinite())throw std::runtime_error("NONFINITE_REDUCED_SOLVE");s.residual=(next-x).norm();x=next;s.iterations=i+1;
        if(s.residual<1e-8)break;}
    return matrix(s.lbs*x,s.rest.rows());
}
}

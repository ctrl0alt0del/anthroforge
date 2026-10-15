#pragma once
namespace af_ad {
constexpr double mu=1./2.6, bulk_lambda=.3/(1.3*.4);
inline R3 element_block(const Element& e,int i,int j) {
    Eigen::Vector3d a=e.g.row(i),b=e.g.row(j);
    return e.volume*(mu*a.dot(b)*R3::Identity()+mu*b*a.transpose()+bulk_lambda*a*b.transpose());
}
inline void stiffness(State& s) {
    std::vector<T> triplets; triplets.reserve(s.tets.rows()*144); int n=s.rest.rows();
    for(int e=0;e<s.tets.rows();++e)for(int i=0;i<4;++i)for(int j=0;j<4;++j) {
        R3 block=element_block(s.elements[e],i,j);
        for(int a=0;a<3;++a)for(int b=0;b<3;++b)triplets.emplace_back(a*n+s.tets(e,i),b*n+s.tets(e,j),block(a,b));
    }
    s.stiffness.resize(3*n,3*n); s.stiffness.setFromTriplets(triplets.begin(),triplets.end());
    S h=s.stiffness+s.lambda*S(s.block.transpose()*s.block); S eye(h.rows(),h.cols());eye.setIdentity();h+=1e-10*eye;
    s.factor.compute(h); if(s.factor.info()!=Eigen::Success)throw std::runtime_error("ELASTIC_FACTORIZATION_FAILED");
}
inline double physical(State& s,const M& x,M* gradient=nullptr) {
    double energy=0; s.minimum_j=INFINITY; if(gradient)gradient->setZero(x.rows(),3);
    for(int e=0;e<s.tets.rows();++e) {
        const auto& element=s.elements[e]; R3 f=frame(x,s.tets,e)*element.inverse; s.minimum_j=std::min(s.minimum_j,f.determinant());
        R3 r=rotation(f); double trace=(r.transpose()*f).trace()-3;
        energy+=element.volume*(mu*(f-r).squaredNorm()+.5*bulk_lambda*trace*trace);
        if(gradient){R3 stress=2*mu*(f-r)+bulk_lambda*trace*r;
            for(int i=0;i<4;++i)gradient->row(s.tets(e,i))+=element.volume*(stress*element.g.row(i).transpose()).transpose();}
    }
    return energy;
}
inline double objective(State& s,const M& x,const M& delta,M* gradient=nullptr) {
    double energy=physical(s,x,gradient); M residual=s.weighted*(x-s.rest)-s.sample_weights.cwiseSqrt().asDiagonal()*delta;
    energy+=.5*s.lambda*residual.squaredNorm(); if(gradient)*gradient+=s.lambda*(s.weighted.transpose()*residual);
    return s.minimum_j>1e-8?energy:INFINITY;
}
inline M linear(State& s,const M& delta) {
    M weighted=s.sample_weights.cwiseSqrt().asDiagonal()*delta;
    V displacement=s.factor.solve(s.lambda*(s.block.transpose()*vector(weighted)));
    if(!displacement.allFinite())throw std::runtime_error("NONFINITE_LINEAR_SOLVE");
    s.iterations=1; return s.rest+matrix(displacement,s.rest.rows());
}
inline M nonlinear_step(State& s,const M& x,const M& delta,double& change) {
    M gradient; double old=objective(s,x,delta,&gradient);
    V direction=s.factor.solve(-vector(gradient)); M step=matrix(direction,x.rows()); double alpha=1;
    for(int line=0;line<24;++line,alpha*=.5) {
        check(s); M candidate=x+alpha*step; double value=objective(s,candidate,delta);
        if(value<=old+1e-4*alpha*vector(gradient).dot(direction)) { change=(alpha*step).rowwise().norm().maxCoeff();return candidate; }
    }
    change=0; return x;
}
inline M nonlinear(State& s,const M& delta) {
    M x=s.rest; s.iterations=0;
    for(int stage=1;stage<=5;++stage)for(int it=0;it<40;++it) {
        check(s); double change; x=nonlinear_step(s,x,delta*(stage/5.),change); ++s.iterations;
        if(change<1e-8)break;
    }
    M gradient; objective(s,x,delta,&gradient); s.residual=gradient.norm(); return x;
}
}

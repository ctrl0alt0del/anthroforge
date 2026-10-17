#include "../export.h"
#include <memory>
#include <igl/bbw.h>
#include <igl/arap_dof.h>
#include <igl/lbs_matrix.h>
#include <igl/in_element.h>
#include <igl/boundary_facets.h>
#include "model.hpp"
#include "elastic.hpp"
#include "reduced.hpp"
namespace af_ad {
static thread_local std::string error;
#define API AF_NATIVE_EXPORT
API int af_ad_version(){return 1;}
API const char* af_ad_error(){return error.c_str();}
API void af_ad_destroy(void* handle){delete static_cast<State*>(handle);}
API void af_ad_cancel_path(void* handle,const char* path){static_cast<State*>(handle)->cancel=path?path:"";}
API void af_ad_areas(const double* points,int n,const int* faces,int nf,int arity,double* output) {
    M p=Eigen::Map<const RM>(points,n,3);std::fill(output,output+n,0.);
    for(int f=0;f<nf;++f)for(int k=1;k<arity-1;++k){int a=faces[f*arity],b=faces[f*arity+k],c=faces[f*arity+k+1];
        Eigen::Vector3d u=p.row(b)-p.row(a),v=p.row(c)-p.row(a);double area=u.cross(v).norm()/6;
        output[a]+=area;output[b]+=area;output[c]+=area;}
}
API void* af_ad_create(const double* v,int n,const int* t,int nt,const double* points,int np,
    const double* samples,int ns,const double* weights,int method,int count,double strength,const char* cancel) {
    auto s=std::make_unique<State>();
    try{if(method!=0 && method!=2)throw std::runtime_error("UNSUPPORTED_DEFORMATION_METHOD");
        s->started=std::chrono::steady_clock::now();s->rest=Eigen::Map<const RM>(v,n,3);s->tets=Eigen::Map<const RI>(t,nt,4);
        s->points=Eigen::Map<const RM>(points,np,3);s->samples=Eigen::Map<const RM>(samples,ns,3);s->sample_weights=Eigen::Map<const V>(weights,ns);
        s->method=method;s->lambda=strength;s->cancel=cancel?cancel:"";common(*s);
        if(method==0||method==3)stiffness(*s);else reduced_prepare(*s,count);return s.release();
    }catch(const std::exception& e){error=e.what();return nullptr;}
}
API int af_ad_solve(void* handle,const double* targets,double* out,double* diagnostics,double* predicted) {
    try{auto& s=*static_cast<State*>(handle);s.started=std::chrono::steady_clock::now();check(s);
        M delta=Eigen::Map<const RM>(targets,s.samples.rows(),3)-s.samples,x;
        if(s.method==0)x=linear(s,delta);else if(s.method==3)x=nonlinear(s,delta);else x=reduced_solve(s,delta);
        M skin=s.points+s.skin*(x-s.rest),p=s.samples+s.constraints*(x-s.rest);
        Eigen::Map<RM>(out,skin.rows(),3)=skin;Eigen::Map<RM>(predicted,p.rows(),3)=p;physical(s,x);
        diagnostics[0]=s.iterations;diagnostics[1]=s.residual;diagnostics[2]=s.minimum_j;diagnostics[3]=s.outside;diagnostics[4]=s.max_outside;
        diagnostics[5]=(s.skin*s.rest-s.points).rowwise().norm().maxCoeff();return 1;
    }catch(const std::exception& e){error=e.what();return 0;}
}
API int af_ad_embedding(void* handle,int* ids,double* weights) {
    try{auto& s=*static_cast<State*>(handle);Eigen::SparseMatrix<double,Eigen::RowMajor> rows=s.skin;
        std::fill(ids,ids+4*rows.rows(),0);std::fill(weights,weights+4*rows.rows(),0.);
        for(int i=0;i<rows.rows();++i){int j=0;for(decltype(rows)::InnerIterator it(rows,i);it;++it){
            if(j>=4)throw std::runtime_error("INVALID_EMBEDDING_ARITY");ids[4*i+j]=int(it.col());weights[4*i+j++]=it.value();}}
        return 1;
    }catch(const std::exception& e){error=e.what();return 0;}
}
}
#include "contact.hpp"

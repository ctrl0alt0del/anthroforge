#pragma once
#include "scan.hpp"
AF_EXPORT int af_base_intersections_version() { return 1; }
AF_EXPORT void* af_base_intersections_scan(const af_base_check::Input* inputs,int count,double epsilon,int limit,char* error,int size) {
    try{return new af_base_check::Result(af_base_check::scan(inputs,count,epsilon,limit));}
    catch(const std::exception& e){if(error&&size>0){std::strncpy(error,e.what(),size-1);error[size-1]=0;}return nullptr;}
}
AF_EXPORT void af_base_intersections_free(void* handle) { delete static_cast<af_base_check::Result*>(handle); }
AF_EXPORT int af_base_intersections_sizes(void* handle,int64_t* sizes) {
    if(!handle||!sizes)return 1;auto& r=*static_cast<af_base_check::Result*>(handle);
    int64_t values[]={int64_t(r.pairs.size()),int64_t(r.witnesses.size()),int64_t(r.degenerate.size()),r.broad,r.tests};
    std::copy(values,values+5,sizes);return 0;
}
AF_EXPORT int af_base_intersections_copy(void* handle,af_base_check::Pair* pairs,af_base_check::Witness* witnesses,int64_t* degenerate) {
    if(!handle||!pairs||!witnesses||!degenerate)return 1;auto& r=*static_cast<af_base_check::Result*>(handle);
    std::copy(r.pairs.begin(),r.pairs.end(),pairs);std::copy(r.witnesses.begin(),r.witnesses.end(),witnesses);
    std::copy(r.degenerate.begin(),r.degenerate.end(),degenerate);return 0;
}

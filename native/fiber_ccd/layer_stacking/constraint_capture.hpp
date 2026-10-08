#pragma once
namespace af_layer {
static void validate_axis(const double* values,int count) {
    require(values&&count>=2,"STACK_CONSTRAINT_CHART");
    for(int i=0;i<count;++i)require(std::isfinite(values[i])&&(i==0||values[i]>values[i-1]),"STACK_CONSTRAINT_CHART");
}
static std::pair<int,double> parameter_interval(const double* values,int count,double point) {
    require(values&&count>=2&&std::isfinite(point),"STACK_CONSTRAINT_PARAMETER");
    require(point>=values[0]-1e-12&&point<=values[count-1]+1e-12,"STACK_CONSTRAINT_OUTSIDE_CHART");
    int i=std::clamp(int(std::upper_bound(values,values+count,point)-values)-1,0,count-2);
    return {i,std::clamp((point-values[i])/(values[i+1]-values[i]),0.,1.)};
}
}
AF_EXPORT int af_stack_constraint_capture_version(){return 1;}
AF_EXPORT int af_stack_chart_constraints(const double* across,int rows,const double* along,int columns,const int64_t* mapping,const double* uv,int count,int64_t* indices,double* weights) {
    if(!mapping||count<0||count>2000000||rows<2||columns<2||int64_t(rows)*columns>2000000||(!uv&&count)||(!indices&&count)||(!weights&&count))return 1;
    try{af_layer::validate_axis(across,rows);af_layer::validate_axis(along,columns);
        for(int k=0;k<count;++k){auto u=af_layer::parameter_interval(across,rows,uv[2*k]);
        auto v=af_layer::parameter_interval(along,columns,uv[2*k+1]);
        int offsets[]={u.first*columns+v.first,(u.first+1)*columns+v.first,(u.first+1)*columns+v.first+1,u.first*columns+v.first+1};
        double w[]={(1-u.second)*(1-v.second),u.second*(1-v.second),u.second*v.second,(1-u.second)*v.second};
        for(int j=0;j<4;++j){indices[4*k+j]=mapping[offsets[j]];weights[4*k+j]=w[j];}}
        return 0;
    }catch(...){return 1;}
}

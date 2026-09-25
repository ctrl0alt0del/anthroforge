// Convex sampled ordering constraints for the sparse ruled-strip fit.
namespace af_base {
struct Halfspace { std::vector<double> row; double lower; };
static Vec reference(const double* samples,int count,int part,double u,double v) {
    double best=1e30;Vec value={0,0,0};
    for(int i=0;i<count;++i){auto p=samples+7*i;if(int(p[0])!=part)continue;double d=(p[1]-u)*(p[1]-u)+(p[2]-v)*(p[2]-v);
        if(d<best){best=d;value=load3(p+3);}}
    return value;
}
static void inequality(std::vector<Halfspace>& h,int n,int nu,int nv,int pa,int ua,int pb,int ub,double v,Vec dir,double margin) {
    double length=norm(dir);if(length<1e-8)return;dir=mul(dir,1/length);Halfspace item;item.row.resize(n*3);item.lower=margin*length;
    for(int j=0;j<nv;++j){double w=basis(j,3,std::min(v,1-1e-13),nv);int a=(pa*nu+ua)*nv+j,b=(pb*nu+ub)*nv+j;
        for(int k=0;k<3;++k){double component=k==0?dir.x:(k==1?dir.y:dir.z);item.row[a*3+k]+=w*component;item.row[b*3+k]-=w*component;}}
    h.push_back(std::move(item));
}
static std::vector<Halfspace> strip_order(const double* samples,int count,int parts,int nu,int nv,const int64_t* active) {
    std::vector<Halfspace> result;int n=parts*nu*nv;
    for(int p=0;p<parts;++p)for(int u=0;u<active[p]-1;++u)for(int t=1;t<24;++t){double v=double(t)/24;
        Vec a=reference(samples,count,p,double(u+1)/(active[p]-1),v),b=reference(samples,count,p,double(u)/(active[p]-1),v);
        inequality(result,n,nu,nv,p,u+1,p,u,v,sub(a,b),.08);}
    return result;
}
static void seam_order(std::vector<Halfspace>& h,const double* samples,int count,int parts,int nu,int nv,const int64_t* active,const int64_t* joins,int join_count) {
    for(int s=0;s<join_count;++s){auto j=joins+4*s;int pa=int(j[0]),pb=int(j[2]),ua=j[1]?int(active[pa])-1:0,ub=j[3]?int(active[pb])-1:0;
        int na=ua+(j[1]?-1:1),nb=ub+(j[3]?-1:1);Vec tangent=sub(reference(samples,count,pa,double(j[1]),1),reference(samples,count,pa,double(j[1]),0));
        double length=norm(tangent);if(length<1e-9)continue;tangent=mul(tangent,1/length);
        for(int t=1;t<24;++t){double v=double(t)/24;Vec a=reference(samples,count,pa,double(na)/(active[pa]-1),v),b=reference(samples,count,pb,double(nb)/(active[pb]-1),v);
            Vec dir=sub(a,b);dir=sub(dir,mul(tangent,dot(dir,tangent)));
            inequality(h,parts*nu*nv,nu,nv,pa,na,pa,ua,v,dir,.015);inequality(h,parts*nu*nv,nu,nv,pb,ub,pb,nb,v,dir,.015);}}
}
static void vector_system(const std::vector<double>& a,const std::vector<double>& b,const std::vector<double>& c,const std::vector<double>& d,int n,std::vector<double>& matrix,std::vector<double>& rhs,std::vector<double>& equal,std::vector<double>& targets) {
    int size=n*3,m=int(d.size()/3);matrix.resize(size*size);rhs.resize(size*3);equal.resize(m*3*size);targets.resize(m*9);
    for(int i=0;i<n;++i)for(int k=0;k<3;++k){rhs[(i*3+k)*3]=b[i*3+k];for(int j=0;j<n;++j)matrix[(i*3+k)*size+j*3+k]=a[i*n+j];}
    for(int i=0;i<m;++i)for(int k=0;k<3;++k){targets[(i*3+k)*3]=d[i*3+k];for(int j=0;j<n;++j)equal[(i*3+k)*size+j*3+k]=c[i*n+j];}
}
static int violated(const std::vector<Halfspace>& rows,const std::vector<double>& x) {
    int worst=-1;double limit=-1e-8;
    for(int i=0;i<int(rows.size());++i){double value=-rows[i].lower;for(int j=0;j<int(rows[i].row.size());++j)value+=rows[i].row[j]*x[j];
        if(value<limit){worst=i;limit=value;}}
    return worst;
}
static bool ordered_solve(const std::vector<double>& a,const std::vector<double>& b,const std::vector<double>& c,const std::vector<double>& d,int n,const std::vector<Halfspace>& limits,std::vector<double>& x) {
    std::vector<double> matrix,rhs,equal,targets;vector_system(a,b,c,d,n,matrix,rhs,equal,targets);
    for(int step=0;step<64;++step){int index=violated(limits,x);if(index<0)return true;
        equal.insert(equal.end(),limits[index].row.begin(),limits[index].row.end());targets.insert(targets.end(),{limits[index].lower,0,0});
        auto system=matrix,values=rhs;std::vector<double> result;augment(system,values,equal,targets,n*3);
        if(!solve(system,values,result))return false;for(int i=0;i<n*3;++i)x[i]=result[i*3];}
    return false;
}
}

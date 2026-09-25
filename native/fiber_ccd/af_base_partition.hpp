// Local shared-border partition of two directed, longitudinally monotone strips.
#pragma once
namespace af_partition {
using Path=std::vector<Vec>;
struct Strip { std::vector<Path> rows; int side; bool reversed=false; double low=0,high=0; };
struct Join { double x; Vec a,b,common; bool active; };
static Vec point(const Path& p,double x) {
    auto i=std::upper_bound(p.begin(),p.end(),x,[](double v,Vec q){return v<q.x;});
    if(i==p.begin())return p.front();if(i==p.end())return p.back();
    Vec b=*i,a=*(i-1);return add(a,mul(sub(b,a),(x-a.x)/(b.x-a.x)));
}
static Strip read(const double* data,int rows,int cols,int side,const Vec* axes,Vec origin) {
    Strip s;s.side=side;s.low=-1e100;s.high=1e100;
    for(int r=0;r<rows;++r){Path p;
        for(int j=0;j<cols;++j){Vec d=sub(load3(data+3*(r*cols+j)),origin);p.push_back({dot(d,axes[0]),dot(d,axes[1]),dot(d,axes[2])});}
        bool reverse=p.front().x>p.back().x;if(!r)s.reversed=reverse;if(reverse!=s.reversed)throw 2;
        if(reverse)std::reverse(p.begin(),p.end());
        for(int j=1;j<cols;++j)if(p[j].x-p[j-1].x<=1e-10)throw 2;
        s.low=std::max(s.low,p.front().x);s.high=std::min(s.high,p.back().x);s.rows.push_back(p);}
    if(s.high-s.low<1e-8)throw 2;return s;
}
static const Path& border(const Strip& s) { return s.rows[s.side? s.rows.size()-1:0]; }
static double direction(const Strip& s,double x) {
    double d=point(s.rows[s.side?0:s.rows.size()-1],x).y-point(border(s),x).y;
    if(std::abs(d)<1e-10)throw 3;return d>0?1:-1;
}
static std::vector<double> knots(const Strip& a,const Strip& b,double lo,double hi,double sign) {
    std::vector<double> x{lo,hi};for(const auto* s:{&a,&b})for(const auto& p:s->rows)for(Vec q:p)if(q.x>lo&&q.x<hi)x.push_back(q.x);
    std::sort(x.begin(),x.end());x.erase(std::unique(x.begin(),x.end()),x.end());auto base=x;
    for(size_t i=1;i<base.size();++i){double l=base[i-1],r=base[i];
        double u=sign*(point(border(b),l).y-point(border(a),l).y),v=sign*(point(border(b),r).y-point(border(a),r).y);
        if(u*v<0)x.push_back(l+(r-l)*u/(u-v));}
    double epsilon=(hi-lo)*1e-7;std::sort(x.begin(),x.end());x.erase(std::unique(x.begin(),x.end(),[=](double u,double v){return std::abs(u-v)<epsilon;}),x.end());return x;
}
static std::vector<Join> joins(const Strip& a,const Strip& b,const std::vector<double>& xs,double sign,double depth) {
    std::vector<Join> out;
    for(double x:xs){Vec p=point(border(a),x),q=point(border(b),x);bool active=sign*(q.y-p.y)>=-1e-10;
        if(active&&std::abs(q.z-p.z)>depth)throw 4;
        out.push_back({x,p,q,mul(add(p,q),.5),active});}
    return out;
}
static double blend(const std::vector<Join>& joins,double x,double distance) {
    double d=1e100;for(size_t i=1;i<joins.size();++i)if(joins[i-1].active&&joins[i].active)
        d=std::min(d,std::max({joins[i-1].x-x,0.0,x-joins[i].x}));
    if(d>=distance)return 0;double t=1-d/distance;return t*t*(3-2*t);
}
static Vec delta(const Strip& a,const Strip& b,int which,double x,double sign,const std::vector<Join>& js,double fade) {
    Vec p=point(border(a),x),q=point(border(b),x),mid=mul(add(p,q),.5),own=which?q:p;
    double lo=js.front().x,hi=js.back().x,w=(x>=lo&&x<=hi)?blend(js,x,fade):0;
    bool active=x>=lo&&x<=hi&&sign*(q.y-p.y)>=-1e-10;
    return {0,active?mid.y-own.y:0,w*(mid.z-own.z)};
}
static std::vector<double> targets(const Strip& s,const std::vector<Join>& js,double fade) {
    std::vector<double> xs;double epsilon=(s.high-s.low)*1e-7;
    for(const auto& row:s.rows)for(Vec p:row)if(p.x>s.low+epsilon&&p.x<s.high-epsilon)xs.push_back(p.x);
    for(size_t i=0;i<js.size();++i){bool transition=i==0||i+1==js.size()||js[i].active!=js[i-1].active||js[i].active!=js[i+1].active;
        for(double x:{js[i].x,js[i].x-(transition?fade:0),js[i].x+(transition?fade:0)})if(x>s.low+epsilon&&x<s.high-epsilon)xs.push_back(x);}
    std::sort(xs.begin(),xs.end());xs.erase(std::unique(xs.begin(),xs.end(),[=](double x,double y){return std::abs(x-y)<epsilon;}),xs.end());return xs;
}
static double distance(Vec p,const Path& path) {
    double best=1e100;for(size_t i=1;i<path.size();++i){Vec d=sub(path[i],path[i-1]);double t=std::clamp(dot(sub(p,path[i-1]),d)/std::max(dot(d,d),1e-24),0.0,1.0);
        Vec error=sub(p,add(path[i-1],mul(d,t)));best=std::min(best,std::sqrt(dot(error,error)));}return best;
}
static double outline(const Strip& s,const std::vector<Path>& rows,Vec* axes,Vec origin) {
    int i=s.side?0:int(rows.size()-1);Path before;
    for(Vec p:s.rows[i])before.push_back(add(origin,add(mul(axes[0],p.x),add(mul(axes[1],p.y),mul(axes[2],p.z)))));
    double error=0;for(Vec p:before)error=std::max(error,distance(p,rows[i]));for(Vec p:rows[i])error=std::max(error,distance(p,before));return error;
}
static void row_output(const Strip& s,int r,const std::vector<double>& xs,const std::vector<Vec>& change,Vec* axes,Vec origin,Path& out,double limit,double& maximum) {
    double weight=s.side?double(r)/(s.rows.size()-1):1-double(r)/(s.rows.size()-1);
    out.push_back(s.rows[r].front());
    for(size_t j=0;j<xs.size();++j){Vec d=mul(change[j],weight);maximum=std::max(maximum,std::sqrt(dot(d,d)));
        if(maximum>limit)throw 5;out.push_back(add(point(s.rows[r],xs[j]),d));}
    out.push_back(s.rows[r].back());if(s.reversed)std::reverse(out.begin(),out.end());
    for(Vec& p:out)p=add(origin,add(mul(axes[0],p.x),add(mul(axes[1],p.y),mul(axes[2],p.z))));
}
static std::vector<Path> output(const Strip& a,const Strip& b,int which,const std::vector<Join>& js,double sign,const double* settings,Vec* axes,Vec origin,double& maximum) {
    const Strip& s=which?b:a;auto xs=targets(s,js,settings[0]);std::vector<Vec> ds;
    for(double x:xs)ds.push_back(delta(a,b,which,x,sign,js,settings[0]));
    std::vector<Path> out(s.rows.size());
    for(int r=0;r<int(out.size());++r)row_output(s,r,xs,ds,axes,origin,out[r],settings[1],maximum);
    for(size_t j=0;j<xs.size();++j){double last=point(s.rows[0],xs[j]).y+ds[j].y*(s.side?0:1);
        for(size_t r=1;r<s.rows.size();++r){double w=s.side?double(r)/(s.rows.size()-1):1-double(r)/(s.rows.size()-1);
            double y=point(s.rows[r],xs[j]).y+ds[j].y*w;
            if((y-last)*(s.rows.back()[0].y-s.rows.front()[0].y)<=0)throw 3;last=y;}}
    return out;
}
static void locks(const Strip& a,const Strip& b,const std::vector<Join>& js,double sign,double fade) {
    for(int i=0;i<2;++i){const Strip& s=i?b:a;for(Vec p:{border(s).front(),border(s).back()}){
        Vec d=delta(a,b,i,p.x,sign,js,fade);if(dot(d,d)>1e-14)throw 6;}}
}
static void write(const std::vector<Path>& rows,double* data) {
    for(const auto& row:rows)for(Vec p:row){*data++=p.x;*data++=p.y;*data++=p.z;}
}
}
AF_EXPORT int af_base_partition(const double* first,int nr,int nc,const double* second,int mr,int mc,const int64_t* sides,const double* frame,const double* settings,double* aout,double* bout,int* sizes,double* stats) {
    using namespace af_partition;if(!sides||!sizes||!stats||nr<2||nr>8||mr<2||mr>8||nc<2||nc>1025||mc<2||mc>1025)return 1;
    if(!af_base::finite(first,nr*nc*3)||!af_base::finite(second,mr*mc*3)||!af_base::finite(frame,9)||!af_base::finite(settings,3))return 1;
    if(sides[0]<0||sides[0]>1||sides[1]<0||sides[1]>1||settings[0]<=0||settings[1]<=0||settings[2]<0)return 1;
    try{Vec axes[3]={load3(frame),load3(frame+3),load3(frame+6)},origin=load3(first);
        auto a=read(first,nr,nc,int(sides[0]),axes,origin),b=read(second,mr,mc,int(sides[1]),axes,origin);
        double lo=std::max(a.low,b.low),hi=std::min(a.high,b.high);if(hi<=lo)throw 7;
        double sign=direction(a,(lo+hi)/2);if(direction(b,(lo+hi)/2)==sign)throw 3;
        auto js=joins(a,b,knots(a,b,lo,hi,sign),sign,settings[2]);locks(a,b,js,sign,settings[0]);double maximum=0;
        auto ar=output(a,b,0,js,sign,settings,axes,origin,maximum),br=output(a,b,1,js,sign,settings,axes,origin,maximum);
        sizes[0]=int(ar[0].size());sizes[1]=int(br[0].size());stats[0]=maximum;stats[1]=0;stats[2]=std::max(outline(a,ar,axes,origin),outline(b,br,axes,origin));
        for(size_t i=1;i<js.size();++i)if(js[i-1].active&&js[i].active)stats[1]+=js[i].x-js[i-1].x;
        if(aout&&bout){write(ar,aout);write(br,bout);}return 0;
    }catch(int code){return code;}catch(...){return 8;}
}

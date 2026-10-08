#pragma once
// Triangle-interior diagnostics, independent of inflation direction and layer order.
namespace af_base_check {
struct Hit { int kind=0; Vec first{},second{}; double area=0; };
static Vec unit_normal(const Vec* p) {
    Vec n=cross(sub(p[1],p[0]),sub(p[2],p[0]));double length=norm(n);
    return length>0?mul(n,1/length):Vec{};
}
static double edge_distance(Vec p,Vec a,Vec b,Vec normal) {
    Vec edge=sub(b,a);return dot(cross(edge,sub(p,a)),normal)/norm(edge);
}
static bool inside(Vec point,const Vec* triangle,Vec normal,double epsilon) {
    for(int i=0;i<3;++i)if(edge_distance(point,triangle[i],triangle[(i+1)%3],normal)<-epsilon)return false;
    return true;
}
static std::vector<Vec> clip(const std::vector<Vec>& points,Vec a,Vec b,Vec normal) {
    std::vector<Vec> out;if(points.empty())return out;Vec p=points.back();double dp=edge_distance(p,a,b,normal);
    for(Vec q:points){double dq=edge_distance(q,a,b,normal);
        if((dp<0)!=(dq<0))out.push_back(add(p,mul(sub(q,p),dp/(dp-dq))));
        if(dq>=0)out.push_back(q);p=q;dp=dq;}
    return out;
}
static Hit span(const std::vector<Vec>& points,double epsilon) {
    Hit hit;if(points.empty())return hit;hit.kind=3;hit.first=hit.second=points.front();double best=0;
    for(Vec p:points)for(Vec q:points){double length=norm(sub(p,q));
        if(length>best){best=length;hit.first=p;hit.second=q;}}
    if(best>epsilon)hit.kind=1;return hit;
}
static void plane_hits(const Vec* a,const Vec* b,Vec normal,double epsilon,std::vector<Vec>& points) {
    for(int i=0;i<3;++i){Vec p=a[i],q=a[(i+1)%3];double dp=dot(sub(p,b[0]),normal),dq=dot(sub(q,b[0]),normal);
        if(std::abs(dp)<=epsilon&&inside(p,b,normal,epsilon))points.push_back(p);
        if((dp<0)!=(dq<0)){Vec hit=add(p,mul(sub(q,p),dp/(dp-dq)));
            if(inside(hit,b,normal,epsilon))points.push_back(hit);}}
}
static Hit coplanar(const Vec* a,const Vec* b,Vec normal,double epsilon) {
    std::vector<Vec> polygon(a,a+3);for(int i=0;i<3;++i)polygon=clip(polygon,b[i],b[(i+1)%3],normal);
    Hit hit=span(polygon,epsilon);double area=0;
    for(size_t i=1;i+1<polygon.size();++i)area+=norm(cross(sub(polygon[i],polygon[0]),sub(polygon[i+1],polygon[0])))*.5;
    if(area>epsilon*epsilon){hit.kind=2;hit.area=area;return hit;}
    std::vector<Vec> contacts=polygon;plane_hits(a,b,normal,epsilon,contacts);plane_hits(b,a,unit_normal(a),epsilon,contacts);
    hit=span(contacts,epsilon);if(hit.kind)hit.kind=3;return hit;
}
static bool separated(const Vec* a,const Vec* b,Vec normal,double epsilon) {
    double low=INFINITY,high=-INFINITY;for(int i=0;i<3;++i){double d=dot(sub(a[i],b[0]),normal);low=std::min(low,d);high=std::max(high,d);}
    return low>epsilon||high<-epsilon;
}
static Hit intersection(const Vec* a,const Vec* b,double epsilon) {
    Vec na=unit_normal(a),nb=unit_normal(b);
    if(separated(a,b,nb,epsilon)||separated(b,a,na,epsilon))return {};
    if(norm(cross(na,nb))<1e-10)return coplanar(a,b,nb,epsilon);
    std::vector<Vec> points;plane_hits(a,b,nb,epsilon,points);plane_hits(b,a,na,epsilon,points);
    return span(points,epsilon);
}
}

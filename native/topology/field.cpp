#include <Eigen/Dense>
#include <complex>
#include <vector>
#include <map>
#include <algorithm>
#include <queue>
using V=Eigen::Vector3d;using C=std::complex<double>;
extern "C" __declspec(dllexport) int af_topology_version(){return 1;}
struct Face {V p,n,x,y;C prior,target,z;double weight=0,confidence=0;int owner=-1;std::vector<int> adjacent;};
V vec(const double*p,int i){return V(p[3*i],p[3*i+1],p[3*i+2]);}
C phase(const V&v,const Face&f){double a=std::atan2(v.dot(f.y),v.dot(f.x));return std::polar(1.,4*a);}
V direction(C z,const Face&f){double a=std::arg(z)/4.;return std::cos(a)*f.x+std::sin(a)*f.y;}
std::vector<Face> geometry(const double*v,const int*t,int count,const double*prior){
 std::vector<Face> fs(count);std::map<std::pair<int,int>,int> edges;
 for(int i=0;i<count;i++){auto&f=fs[i];V a=vec(v,t[3*i]),b=vec(v,t[3*i+1]),c=vec(v,t[3*i+2]);
  f.p=(a+b+c)/3.;f.n=(b-a).cross(c-a).normalized();f.x=(b-a).normalized();f.y=f.n.cross(f.x);
  f.prior=f.z=phase(vec(prior,i),f);
  for(int k=0;k<3;k++){int a=t[3*i+k],b=t[3*i+(k+1)%3];auto key=std::minmax(a,b);auto it=edges.find(key);
   if(it!=edges.end()){f.adjacent.push_back(it->second);fs[it->second].adjacent.push_back(i);}else edges[key]=i;}
 }return fs;
}
std::vector<int> route(const double*v,const std::vector<std::vector<int>>&graph,int a,int b){
 std::vector<double>cost(graph.size(),1e100);std::vector<int>previous(graph.size(),-1);cost[a]=0;
 using Entry=std::pair<double,int>;std::priority_queue<Entry,std::vector<Entry>,std::greater<Entry>> queue;queue.push({0,a});
 while(!queue.empty()){auto[c,i]=queue.top();queue.pop();if(c!=cost[i])continue;if(i==b)break;
  for(int j:graph[i]){double next=c+(vec(v,i)-vec(v,j)).norm();if(next<cost[j]){cost[j]=next;previous[j]=i;queue.push({next,j});}}}
 std::vector<int> result;if(previous[b]<0&&a!=b)return result;
 for(int j=b;j!=a;j=previous[j])result.push_back(j);result.push_back(a);std::reverse(result.begin(),result.end());return result;
}
int path_impl(const double*v,int nv,const int*t,int nt,const double*p,int np,int*out,int capacity){
 std::vector<std::vector<int>>graph(nv);for(int i=0;i<nt;i++)for(int k=0;k<3;k++){int a=t[3*i+k],b=t[3*i+(k+1)%3];graph[a].push_back(b);graph[b].push_back(a);}
 std::vector<int>anchors;for(int j=0;j<np;j++){double best=1e100;int id=-1;for(int i=0;i<nv;i++){double d=(vec(v,i)-vec(p,j)).squaredNorm();if(d<best){best=d;id=i;}}anchors.push_back(id);}
 int used=0;for(int i=1;i<np;i++){auto path=route(v,graph,anchors[i-1],anchors[i]);if(path.empty())return -1;
  for(size_t k=1;k<path.size();k++){if(used+2>capacity)return -2;out[used++]=path[k-1];out[used++]=path[k];}}return used/2;
}
void constrain(Face&f,const double*p,const double*d,const double*n,const int*ids,int count,double radius,bool robust){
 std::vector<std::pair<double,int>> near;double r2=radius*radius;
 for(int j=0;j<count;j++){double dd=(vec(p,j)-f.p).squaredNorm();if(dd<r2)near.emplace_back(dd,j);}
 std::sort(near.begin(),near.end());if(near.size()>12)near.resize(12);C sum=0.;double total=0,best=0;
 for(auto [dd,j]:near){V normal=vec(n,j),v=vec(d,j);double dot=normal.norm()<.5?1.:f.n.dot(normal);if(dot<.2)continue;
  v-=v.dot(f.n)*f.n;if(v.norm()<1e-9)continue;double w=std::exp(-6*dd/r2)*dot*dot;C z=phase(v,f);
  if(robust)w*=std::max(.05,std::pow(std::max(0.,(1.+std::real(z*std::conj(f.z)))/2.),2));
  sum+=w*z;total+=w;if(w>best){best=w;f.owner=ids[j];}}
 f.confidence=total>0?std::abs(sum)/total:0;f.weight=total>0?12*std::min(1.,total)*f.confidence:0;
 f.target=std::abs(sum)>1e-12?sum/std::abs(sum):f.prior;
}
void relax(std::vector<Face>&fs,int iterations){
 std::vector<C> next(fs.size());
 for(int it=0;it<iterations;it++){for(size_t i=0;i<fs.size();i++){auto&f=fs[i];C sum=.15*f.prior+f.weight*f.target;
   for(int j:f.adjacent){V d=direction(fs[j].z,fs[j]);Eigen::Quaterniond q=Eigen::Quaterniond::FromTwoVectors(fs[j].n,f.n);sum+=phase(q*d,f);}
   next[i]=std::abs(sum)>1e-12?sum/std::abs(sum):f.z;}
  for(size_t i=0;i<fs.size();i++)fs[i].z=next[i];}
}
extern "C" __declspec(dllexport) int af_field(const double*v,const int*t,int count,const double*prior,
 const double*p,const double*d,const double*n,const int*ids,int samples,double radius,int robust,double*out,double*info){
 try{auto fs=geometry(v,t,count,prior);for(auto&f:fs)constrain(f,p,d,n,ids,samples,radius,false);relax(fs,100);
  if(robust)for(int pass=0;pass<3;pass++){for(auto&f:fs)constrain(f,p,d,n,ids,samples,radius,true);relax(fs,60);}
  for(int i=0;i<count;i++){V x=direction(fs[i].z,fs[i]);for(int k=0;k<3;k++)out[3*i+k]=x[k];
   info[3*i]=fs[i].weight;info[3*i+1]=fs[i].confidence;info[3*i+2]=fs[i].owner;}return 1;
 }catch(...){return 0;}
}

extern "C" __declspec(dllexport) int af_path(const double*v,int nv,const int*t,int nt,const double*p,int np,int*out,int capacity){
 try {return path_impl(v,nv,t,nt,p,np,out,capacity);}catch(...){return -3;}
}
bool overlaps(const double*p,int a,int b,const std::vector<V>&used,double radius){
 for(int j=a;j<b;j++)for(auto&v:used)if((vec(p,j)-v).squaredNorm()<radius*radius)return true;
 return false;
}
extern "C" __declspec(dllexport) int af_select_paths(const double*p,const int*offsets,int count,double radius,int*out){
 try{std::vector<std::pair<double,int>>order;std::vector<V>used;int n=0;
  for(int i=0;i<count;i++){double length=0;for(int j=offsets[i]+1;j<offsets[i+1];j++)length+=(vec(p,j)-vec(p,j-1)).norm();order.emplace_back(-length,i);}
  std::sort(order.begin(),order.end());
  for(auto [length,i]:order){int a=offsets[i],b=offsets[i+1];if(b-a<2||overlaps(p,a,b,used,radius))continue;
   out[n++]=i;for(int j=a;j<b;j++)used.push_back(vec(p,j));}return n;
 }catch(...){return -1;}
}

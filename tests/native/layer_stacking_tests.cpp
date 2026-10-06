#include "../../native/fiber_ccd/af_fiber_ccd.cpp"
#include <iostream>
using namespace af_layer;

static Side triangle() {
    Side s;s.id=1;s.base={{0,0,0},{1,0,0},{0,1,0}};s.own=s.base;s.direction={{0,0,1},{0,0,1},{0,0,1}};
    s.faces={0,1,2};s.parts={0};s.sources={0};prepare_snapshot(s,nullptr);return s;
}
static Material correspondence(const Side& s) {
    double weights[]={1,1,1};int64_t indices[]={0,1,2};
    ConstraintInput in{1,reinterpret_cast<const double*>(s.base.data()),s.faces.data(),indices,weights,nullptr,3,1,3,1,0,1};
    return capture_material(in,s);
}
static void signed_mapper_test() {
    auto s=triangle(),provider=triangle();s.direction[0]={.9950371902,0,.099503719};
    af_pair::Settings settings;settings.search=10;Result diagnostics;
    Query q{s,provider,settings,0,0,0,{}, {}};require(prepare(q,diagnostics),"Query setup");cache_chart(q);
    ProviderChart chart;for(int i=0;i<3;++i){auto p=s.base[i];chart.world[i]=sub({p.x,p.y,2*p.x+.3},q.origin);}
    auto row=support_row(q.projected[0],q,chart,s,correspondence(s),0,2);
    require(std::any_of(row.terms.begin(),row.terms.end(),[](auto term){return term.second<0;}),"Signed coefficient lost");
}
static void fold_test() {
    auto s=triangle();auto points=s.own;std::swap(points[1],points[2]);bool rejected=false;
    try{validate_final(s,points);}catch(const std::exception&){rejected=true;}require(rejected,"Fold accepted");
}
static void crossing_test() {
    auto a=triangle(),b=triangle();b.base={{.2,-.2,1},{.2,.8,1},{.2,.3,2}};b.own=b.base;prepare_snapshot(b,nullptr);
    auto c=base_copy(b);c.base={{.2,-.2,-1},{.2,.8,-1},{.2,.3,1}};c.own=c.base;prepare_snapshot(c,nullptr);
    std::atomic<bool> cancel{false};bool rejected=false;
    try{no_new_crossings(a,a,b,c,false,cancel);}catch(const std::exception&){rejected=true;}
    require(rejected,"New intersection accepted");no_new_crossings(a,a,c,c,false,cancel);
}
static void shared_boundary_test() {
    auto a=triangle(),b=triangle();b.base={{0,0,0},{1,0,0},{0,0,1}};b.own=b.base;prepare_snapshot(b,nullptr);
    std::atomic<bool> cancel{false};require(crossing_count(a,b,cancel)==0,"Boundary contact rejected");
}
static void invalid_direction_is_local_test() {
    auto a=triangle(),b=triangle();b.id=2;for(auto& p:b.base)p.z=.1;b.own=b.base;
    b.direction={{1,0,0},{-.5,.866025403784,0},{-.5,-.866025403784,0}};
    Session session;std::vector<Side> incoming;incoming.push_back(std::move(a));incoming.push_back(std::move(b));
    af_pair::Settings settings;settings.search=2;synchronize(session,incoming,settings);std::atomic<bool> cancel{false};
    auto result=safe_resolve(session,0,1,cancel);require(result.summary.status==int(OrderStatus::projection),"Invalid direction escaped local rejection");
}
static State ordered_pair(const Side& a,const Side& b) {
    State state;Evidence e;e.summary.first=a.id;e.summary.second=b.id;e.summary.status=0;
    e.summary.underlying=a.id;e.summary.covering=b.id;state.orders.push_back(e);return state;
}
static void supported_crossing_rejected() {
    auto a=triangle(),b=triangle();b.id=2;for(auto& p:b.base)p.z=1;b.own=b.base;prepare_snapshot(b,nullptr);
    auto final=surface_copy(b,{{0,0,-.1},{1,0,.1},{0,1,.1}});auto state=ordered_pair(a,b);std::atomic<bool> cancel{false};
    require(!final_support_separated(a,final,state,cancel),"Real crossing was accepted as contact");
    bool rejected=false;try{validate_contact_pair(a,a,b,final,state,cancel);}catch(const std::exception&){rejected=true;}
    require(rejected,"Supported pair real crossing was not rejected");
}
static void supported_contact_allowed() {
    auto a=triangle(),b=triangle();b.id=2;for(auto& p:b.base)p.z=.1;b.own=b.base;prepare_snapshot(b,nullptr);
    auto final=surface_copy(b,{{.1,.1,0},{.7,.1,0},{.1,.7,.2}});auto state=ordered_pair(a,b);std::atomic<bool> cancel{false};
    require(final_support_separated(a,final,state,cancel),"Exact contact not certified");
    validate_contact_pair(a,a,b,final,state,cancel);
}
static void unsupported_contact_not_bypassed() {
    auto a=triangle(),b=triangle();b.id=2;auto state=ordered_pair(a,b);state.orders.clear();std::atomic<bool> cancel{false};
    require(!final_support_separated(a,b,state,cancel),"Unordered pair bypassed validation");
}

int main() {
    try{signed_mapper_test();fold_test();crossing_test();shared_boundary_test();invalid_direction_is_local_test();supported_contact_allowed();supported_crossing_rejected();unsupported_contact_not_bypassed();std::cout<<"8 stacking kernel groups passed\n";return 0;}
    catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}

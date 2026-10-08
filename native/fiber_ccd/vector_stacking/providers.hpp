#pragma once
namespace af_stack_vector {
struct Provider { Side side;std::vector<Mask> masks;std::vector<Match> matches; };
static bool in_polygon(Vec bary,const std::vector<Vec>& polygon) {
    double sign=0;for(size_t j=0;j<polygon.size();++j){auto a=polygon[j],b=polygon[(j+1)%polygon.size()];
        double cross=(b.y-a.y)*(bary.z-a.z)-(b.z-a.z)*(bary.y-a.y);
        if(std::abs(cross)<=1e-9)continue;if(sign*cross<0)return false;sign=cross;}return true;
}
static std::vector<bool> allowed_vertices(const Side& cover,const std::vector<Mask>& masks) {
    std::vector<bool> allowed(cover.base.size(),false);
    for(const auto& m:masks)for(int j=0;j<3;++j){Vec bary{};(&bary.x)[j]=1;if(in_polygon(bary,m.barycentrics))allowed[cover.faces[3*m.face+j]]=true;}
    return allowed;
}
static std::vector<Provider> providers(const Side& cover,const State& state,std::atomic<bool>& cancel,double* metrics) {
    std::map<uint64_t,std::vector<Mask>> grouped;for(auto& m:material_masks(state,cover.id,cancel))grouped[m.provider].push_back(std::move(m));
    std::vector<Provider> result;
    for(auto& [id,masks]:grouped){require(!cancel,"PAIR_CANCELLED");const auto& original=state.bases.sides[state.bases.indices.at(id)];
        Provider p;p.side=base_copy(original);p.side.own=state.outputs.at(id).points;p.masks=std::move(masks);bool reused=false;
        auto cached=cached_correspondence(p.side,cover,state,cancel,reused);p.matches=cached->values;
        metrics[0]+=reused?0:cached->stats[4];metrics[1]+=cached->stats[0];metrics[2]+=cached->stats[1];
        auto allowed=allowed_vertices(cover,p.masks);for(size_t i=0;i<allowed.size();++i)if(!allowed[i])p.matches[i].face=-1;
        result.push_back(std::move(p));}return result;
}
static Mat compose(const Side& cover,const std::vector<Provider>& providers) {
    Mat delta=Mat::Zero(cover.base.size(),3);std::vector<double> score(cover.base.size(),-INFINITY);
    for(const auto& p:providers)for(int i=0;i<delta.rows();++i){const auto& match=p.matches[i];if(match.face<0)continue;
        double next=match.bonus.dot(eigen(cover.direction[i]));if(next<=score[i]+1e-10)continue;
        score[i]=next;delta.row(i)=match.bonus.transpose();}return delta;
}
static void pin_targets(Mat& target,const Layout& layout) {
    // Only exact one-hot structural pins directly constrain raw evaluated samples.
    afs::Sparse c=layout.constraints;std::set<int> fixed;
    Eigen::SparseMatrix<double,Eigen::RowMajor> rows=c;
    for(int i=0;i<rows.rows();++i){int count=0,col=-1;for(decltype(rows)::InnerIterator t(rows,i);t;++t){++count;col=t.col();}if(count==1)fixed.insert(col);}
    Eigen::SparseMatrix<double,Eigen::RowMajor> p=layout.sample;
    for(int i=0;i<p.rows();++i){bool pinned=true;for(decltype(p)::InnerIterator t(p,i);t;++t)if(!fixed.count(t.col()))pinned=false;
        if(pinned)target(i/3,i%3)=0;}
}
}

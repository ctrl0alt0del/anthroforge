#pragma once
#include <Eigen/SparseQR>
namespace af_stack_vector {
struct Layout { afs::Sparse sample,constraints;Eigen::SparseMatrix<double,Eigen::RowMajor> sample_rows;afs::Mesh mesh; };
static afs::Sparse sparse_rows(const std::vector<afs::Row>& rows,int columns) {
    std::vector<afs::Triplet> entries;
    for(int i=0;i<int(rows.size());++i)for(auto [j,w]:rows[i].terms)entries.emplace_back(i,j,w);
    afs::Sparse out(rows.size(),columns);out.setFromTriplets(entries.begin(),entries.end());return out;
}
static afs::Sparse scalar_samples(const Material& m,int count) {
    std::vector<afs::Triplet> entries;
    for(int i=0;i<count;++i)for(int j=0;j<m.width;++j){size_t k=size_t(i)*m.width+j;entries.emplace_back(i,int(m.interpolation[k]),m.weights[k]);}
    afs::Sparse out(count,m.mesh.vertices.rows());out.setFromTriplets(entries.begin(),entries.end());out.prune(0.);return out;
}
static afs::Sparse vectorize(const afs::Sparse& scalar) {
    std::vector<afs::Triplet> entries;entries.reserve(3*scalar.nonZeros());
    for(int col=0;col<scalar.outerSize();++col)for(afs::Sparse::InnerIterator t(scalar,col);t;++t)
        for(int c=0;c<3;++c)entries.emplace_back(3*t.row()+c,3*t.col()+c,t.value());
    afs::Sparse out(3*scalar.rows(),3*scalar.cols());out.setFromTriplets(entries.begin(),entries.end());return out;
}
static afs::Sparse independent_columns(const afs::Sparse& p,const afs::Sparse& c) {
    std::vector<afs::Triplet> terms;
    for(int j=0;j<p.outerSize();++j)for(afs::Sparse::InnerIterator t(p,j);t;++t)terms.emplace_back(t.row(),t.col(),t.value());
    for(int j=0;j<c.outerSize();++j)for(afs::Sparse::InnerIterator t(c,j);t;++t)terms.emplace_back(p.rows()+t.row(),t.col(),t.value());
    afs::Sparse a(p.rows()+c.rows(),p.cols());a.setFromTriplets(terms.begin(),terms.end());
    Eigen::SparseQR<afs::Sparse,Eigen::COLAMDOrdering<int>> qr;qr.compute(a);require(qr.info()==Eigen::Success,"STACK_MATERIAL_RANK_FAILURE");
    terms.clear();for(int j=0;j<qr.rank();++j)terms.emplace_back(qr.colsPermutation().indices()[j],j,1);
    afs::Sparse basis(p.cols(),qr.rank());basis.setFromTriplets(terms.begin(),terms.end());return basis;
}
static Layout layout(const Side& side,const Material& m) {
    Layout out;out.mesh.vertices=positions(side.base);out.mesh.faces.resize(side.faces.size()/3,3);
    for(int f=0;f<out.mesh.faces.rows();++f)for(int j=0;j<3;++j)out.mesh.faces(f,j)=int(side.faces[3*f+j]);
    auto rows=m.constraints;for(auto pin:m.fixed){afs::Row row;row.lower=0;row.terms={{int(pin),1}};rows.push_back(row);}
    auto p=scalar_samples(m,int(side.base.size())),c=sparse_rows(rows,int(m.mesh.vertices.rows()));
    auto basis=independent_columns(p,c);out.sample=vectorize(afs::Sparse(p*basis));out.sample_rows=out.sample;
    out.constraints=vectorize(afs::Sparse(c*basis));return out;
}
static void material_signature(std::string& key,const Material& m) {
    append_dense(key,m.mesh.vertices);append_dense(key,m.mesh.faces);append_signature(key,m.interpolation);
    append_signature(key,m.weights);append_signature(key,m.fixed);auto count=m.constraints.size();append_signature(key,&count,1);
    for(const auto& row:m.constraints){auto size=row.terms.size();append_signature(key,&size,1);
        for(auto [id,w]:row.terms){append_signature(key,&id,1);append_signature(key,&w,1);}}
}
static uint64_t sparse_bytes(const afs::Sparse& matrix) {
    return matrix.nonZeros()*(sizeof(double)+sizeof(int))+(matrix.outerSize()+1)*sizeof(int);
}
struct Prepared { Layout layout;afs::Energy energy; };
static std::shared_ptr<Prepared> prepared(const Side& side,const Material& m,const State& state) {
    std::string key="vector-material-v1";append_signature(key,side.base);append_signature(key,side.faces);material_signature(key,m);
    CacheKey id{0,side.id,0};auto out=state.vector_cache->find<Prepared>(id,key);if(out)return out;
    out=std::make_shared<Prepared>();out->layout=layout(side,m);afs::CotangentBiharmonic builder;out->energy=builder.build(out->layout.mesh);
    uint64_t bytes=sparse_bytes(out->layout.sample)*2+sparse_bytes(out->layout.constraints)+sparse_bytes(out->energy.curvature);
    bytes+=out->layout.mesh.vertices.size()*sizeof(double)+out->layout.mesh.faces.size()*sizeof(int)+out->energy.mass.size()*sizeof(double);
    require(bytes<=state.bases.settings.result_bytes,"STACK_VECTOR_MATERIAL_BUDGET");
    state.vector_cache->put(id,std::move(key),out,bytes,state.bases.settings.cache_bytes);return out;
}
static afs::Vector flatten(const Mat& values) {
    afs::Vector result(values.rows()*3);for(int i=0;i<values.rows();++i)for(int c=0;c<3;++c)result[3*i+c]=values(i,c);return result;
}
static std::vector<Vec> evaluate(const Side& side,const Layout& l,const afs::Vector& values) {
    afs::Vector delta=l.sample*values;auto result=side.own;
    for(size_t i=0;i<result.size();++i)for(int c=0;c<3;++c)(&result[i].x)[c]+=delta[3*i+c];return result;
}
}

#pragma once
namespace af_skin {
constexpr int SKIN_TILE=32,SKIN_CELLS=32768,SKIN_SAMPLES=35937;
// Uniform tiles need one value. Only varying tiles own voxel arrays.
struct SkinTileValues {
    std::vector<std::unique_ptr<float[]>> blocks;
    std::vector<float> constants;
    std::atomic<uint64_t> resident{0},peak{0};
    std::atomic<bool> exhausted{false};
    uint64_t limit=UINT64_MAX;
    size_t size() const { return blocks.size()*SKIN_CELLS; }
    uint64_t bytes() const { return resident.load()+blocks.capacity()*sizeof(void*)+constants.capacity()*sizeof(float); }
    float operator[](size_t i) const {
        size_t b=i/SKIN_CELLS; return blocks[b]?blocks[b][i%SKIN_CELLS]:constants[b];
    }
    void resize(size_t size,float value=1.e20f) {
        size_t count=size/SKIN_CELLS;
        for(size_t b=count;b<blocks.size();++b)if(blocks[b])resident-=SKIN_CELLS*sizeof(float);
        blocks.resize(count); constants.resize(count,value);
    }
    bool materialize(size_t b) {
        if(blocks[b])return true;
        uint64_t bytes=resident.fetch_add(SKIN_CELLS*sizeof(float))+SKIN_CELLS*sizeof(float);
        if(bytes>limit) { resident-=SKIN_CELLS*sizeof(float); exhausted=true; return false; }
        uint64_t previous=peak.load(); while(previous<bytes && !peak.compare_exchange_weak(previous,bytes)) {}
        try { blocks[b]=std::make_unique<float[]>(SKIN_CELLS); }
        catch(const std::bad_alloc&) { resident-=SKIN_CELLS*sizeof(float); exhausted=true; return false; }
        std::fill(blocks[b].get(),blocks[b].get()+SKIN_CELLS,constants[b]); return true;
    }
    void set(size_t i,float value) {
        size_t b=i/SKIN_CELLS;
        if(!blocks[b] && value==constants[b])return;
        if(materialize(b))blocks[b][i%SKIN_CELLS]=value;
    }
    float minimum(size_t b) const {
        return blocks[b]?*std::min_element(blocks[b].get(),blocks[b].get()+SKIN_CELLS):constants[b];
    }
    void compact(size_t b) {
        if(!blocks[b])return; const float* begin=blocks[b].get();
        float value=*begin; if(!std::all_of(begin+1,begin+SKIN_CELLS,[value](float x) { return x==value; }))return;
        constants[b]=value; blocks[b].reset(); resident-=SKIN_CELLS*sizeof(float);
    }
};
}

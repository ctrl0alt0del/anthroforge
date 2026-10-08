#pragma once
namespace af_layer {
static void validate_final(const Side& original,const std::vector<Vec>& final) {
    for(size_t f=0;f<original.faces.size();f+=3){Vec old[3],next[3];
        for(int j=0;j<3;++j){int id=int(original.faces[f+j]);old[j]=original.own[id];next[j]=final[id];require(finite(next[j]),"STACK_NONFINITE_OUTPUT");}
        Vec a=cross(sub(old[1],old[0]),sub(old[2],old[0])),b=cross(sub(next[1],next[0]),sub(next[2],next[0]));
        if(norm(a)<=1e-14)continue;require(norm(b)>1e-10*norm(a)&&dot(a,b)>0,"STACK_NEW_FOLD_OR_COLLAPSE");}
}

}

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
import numpy as np
from pair_fixture_adapter import PairDetector
from pair_fixtures import rectangle,triangle,collect,directed,area


class Detection(unittest.TestCase):
    def test_narrow_inside_triangle(self):
        r=triangle('r',[[-1,-1,0],[1,-1,0],[0,1,0]])
        p=triangle('p',[[-.1,-.1,.2],[.1,-.1,.2],[0,.1,.2]])
        result=collect([r,p]); self.assertAlmostEqual(area(result,'r','p'),.02,12)
        bary=np.array(directed(result,'r','p')[0]['polygon']['receiver'])
        self.assertTrue((bary>.1).all()); self.assertEqual(result['stats']['detected_pairs'],1)

    def test_partial_footprint(self):
        r=rectangle('r'); p=rectangle('p',(.4,1.4,-.3,.7),.2)
        result=collect([r,p]); self.assertAlmostEqual(area(result,'r','p'),.6,10)
        points=np.vstack([x['polygon']['world_receiver'] for x in directed(result,'r','p')])
        np.testing.assert_allclose(points.min(0),[.4,-.3,0],atol=1e-10)
        np.testing.assert_allclose(points.max(0),[1,.7,0],atol=1e-10)

    def test_separated_and_adjacent(self):
        r=rectangle('r'); distant=rectangle('p',height=4.)
        edge=rectangle('edge',(1,2,-1,1),.1); near=rectangle('near',(1.01,2,-1,1),.1)
        result=collect([r,distant,edge,near],.2)
        self.assertEqual(directed(result,'r','p'),[])
        self.assertEqual(directed(result,'r','edge'),[]); self.assertEqual(directed(result,'r','near'),[])

    def test_distance_clipping_crossing_first_corner(self):
        r=rectangle('r'); p=rectangle('p'); v=p.own.copy(); v[:,2]=v[:,0]+.5
        result=collect([r,replace(p,base=v,own=v)],.25)
        self.assertAlmostEqual(area(result,'r','p'),1.,10)
        for f in directed(result,'r','p'):
            self.assertGreaterEqual(f['gap_min'],-.250000001); self.assertLessEqual(f['gap_max'],.250000001)

    def test_mesh_resolution_invariance(self):
        values=[]
        for nr,np_ in [(2,2),(3,9),(9,3),(12,13)]:
            result=collect([rectangle('r',n=nr),rectangle('p',(.1,.45,-.3,.8),.2,n=np_)])
            values.append(area(result,'r','p'))
        np.testing.assert_allclose(values,.385,atol=1e-10)

    def test_cropping(self):
        r=rectangle('r',(0,1,-1,1)); p=rectangle('p',(-.8,-.2,-.5,.5),.2)
        self.assertEqual(collect([r,p])['stats']['detected_pairs'],0)
        p=rectangle('p',(-.2,.2,-.5,.5),.2)
        self.assertAlmostEqual(area(collect([r,p]),'r','p'),.2,10)

    def test_branch_layout(self):
        left=rectangle('r',(-1,-.2,-1,1)); right=rectangle('r2',(.2,1,-1,1))
        branch=replace(left,base=np.vstack([left.base,right.base]),own=np.vstack([left.own,right.own]),
                       direction=np.vstack([left.direction,right.direction]),faces=np.vstack([left.faces,right.faces+4]))
        p=rectangle('p',(-.5,.5,-.5,.5),.2)
        self.assertAlmostEqual(area(collect([branch,p]),'r','p'),.6,10)

    def test_both_inflation_sides(self):
        a=rectangle('rA',displacement=.5); b=replace(a,id='rB',side='B',direction=-a.direction)
        top=rectangle('top',height=.3); bottom=rectangle('bottom',height=-.3,direction=(0,0,-1))
        result=collect([a,b,top,bottom],.01)
        self.assertGreater(area(result,'rA','top'),3.9); self.assertGreater(area(result,'rB','bottom'),3.9)
        self.assertFalse(directed(result,'rA','bottom')); self.assertFalse(directed(result,'rB','top'))
        self.assertFalse(directed(result,'rA','rB'))

    def test_permitted_motion_and_search_bounds(self):
        r=rectangle('r',displacement=.4); p=rectangle('p',height=.65,displacement=.2)
        result=collect([r,p],.1); self.assertEqual(result['stats']['detected_pairs'],1)
        self.assertEqual(collect([replace(r,displacement=0),replace(p,displacement=0)],.1)['stats']['detected_pairs'],0)

    def test_existing_thickness_in_reach(self):
        r=rectangle('r',displacement=.4); r=replace(r,own=r.own+[0,0,.5])
        p=rectangle('p',height=.95)
        self.assertAlmostEqual(area(collect([r,p],.1),'r','p'),4,10)

    def test_rigid_transform_invariance(self):
        r=rectangle('r'); p=rectangle('p',(.2,.45,-.3,.8),.2)
        rotation=np.array([[0,0,1],[1,0,0],[0,1,0]])
        sides=[replace(s,base=s.base@rotation+1e6,own=s.own@rotation+1e6,direction=s.direction@rotation) for s in (r,p)]
        self.assertAlmostEqual(area(collect(sides),'r','p'),.275,8)

    def test_multiple_candidates_and_input_order(self):
        sides=[rectangle('r'),rectangle('p1',(-.8,-.2,-.6,.6),.2),rectangle('p2',(.2,.8,-.6,.6),.2)]
        first=collect(sides); second=collect(list(reversed(sides)))
        for name in ('p1','p2'):
            self.assertAlmostEqual(area(first,'r',name),.72,10)
            self.assertAlmostEqual(area(first,'r',name),area(second,'r',name),10)

    def test_sloped_and_nearly_edge_on(self):
        r=rectangle('r'); p=rectangle('p',(-.2,.2,-.2,.2)); v=p.own.copy(); v[:,2]=5*v[:,0]
        result=collect([r,replace(p,base=v,own=v)],.1)
        self.assertAlmostEqual(area(result,'r','p'),.016,9)

    def test_root_mirror_family_and_disabled_filters(self):
        r=rectangle('r'); others=[replace(rectangle(str(i),height=.1),**v) for i,v in enumerate([
            dict(family='r'),dict(root='other'),dict(instance='mirror'),dict(enabled=False)])]
        result=collect([r,*others]); self.assertFalse(any(f['receiver_id']=='r' for f in result['fragments']))

    def test_reversed_winding_does_not_choose_layer_order(self):
        r=rectangle('r'); p=rectangle('p',height=.2)
        result=collect([r,replace(p,faces=p.faces[:,::-1])])
        self.assertAlmostEqual(area(result,'r','p'),4,10)
        self.assertTrue(all(f['alignment']<0 for f in directed(result,'r','p')))
        self.assertEqual(result['activated_relations'],[])

    def test_broad_phase_matches_exhaustive(self):
        rng=np.random.default_rng(2017); sides=[]
        for i in range(8):
            offset=rng.uniform(-2,2,3); s=rectangle(str(i),n=3,displacement=float(rng.random()*.3))
            sides.append(replace(s,base=s.base+offset,own=s.own+offset))
        fast=collect(sides,.25); full=collect(sides,.25,True)
        for r in sides:
            for p in sides: self.assertAlmostEqual(area(fast,r.id,p.id),area(full,r.id,p.id),9)
        self.assertLess(fast['stats']['triangle_queries'],full['stats']['triangle_queries'])

    def test_bad_input_and_transactional_failure(self):
        s=rectangle('r')
        with PairDetector(fragment_limit=1) as d:
            with self.assertRaises(ValueError): d.add(replace(s,direction=s.direction*2))
            d.add(s); d.add(rectangle('p',height=.1))
            with self.assertRaisesRegex(ValueError,'budget'): d.detect()
        with self.assertRaisesRegex(ValueError,'closed'): d.detect()

    def test_snapshot_owns_arrays(self):
        s=rectangle('r'); p=rectangle('p',height=.2)
        with PairDetector() as d:
            d.add(s); d.add(p); before=d.detect(); p.own[:]=100
            after=d.detect(); self.assertEqual(before['fragments'],after['fragments'])

    def test_unprojectable_direction_is_not_silently_rejected(self):
        r=rectangle('r',direction=(1,0,0)); p=rectangle('p',direction=(1,0,0))
        result=collect([r,p]); self.assertGreater(result['stats']['projection_warnings'],0)
        self.assertEqual(result['pairs'][0]['status'],'projection_requires_review')
        self.assertFalse(result['pairs'][0]['activation_ready'])

    def test_negative_own_height_uses_zero_thickness_envelope(self):
        r=rectangle('r'); r=replace(r,own=r.own-[0,0,.2]); p=rectangle('p',height=.1)
        result=collect([r,p]); self.assertEqual(result['stats']['projection_warnings'],0)
        self.assertAlmostEqual(area(result,'r','p'),4,10)

    def test_sign_changing_own_height_has_piecewise_exact_footprint(self):
        r=rectangle('r'); own=r.own.copy(); own[:,2]=own[:,0]; r=replace(r,own=own)
        p=rectangle('p',height=.25)
        fast=collect([r,p],.1); full=collect([r,p],.1,True)
        self.assertAlmostEqual(area(fast,'r','p'),1.7,10)
        self.assertAlmostEqual(area(full,'r','p'),1.7,10)

    def test_sign_change_keeps_both_regions_without_double_counting(self):
        r=rectangle('r'); own=r.own.copy(); own[:,2]=own[:,0]; r=replace(r,own=own)
        p=rectangle('p'); v=p.own.copy(); v[:,2]=.05+.05*v[:,1]; p=replace(p,base=v,own=v)
        self.assertAlmostEqual(area(collect([r,p],.1),'r','p'),4,10)

    def test_native_array_result_lifetime(self):
        with PairDetector(.3) as d:
            d.add(rectangle('r')); d.add(rectangle('p',height=.2)); raw=d.detect(materialize=False)
        self.assertEqual(len(raw['fragment_array']),4)
        self.assertTrue(np.isfinite(raw['point_array']['world_receiver']).all())

    def test_mirrored_instances_detect_separately(self):
        a=rectangle('r'); b=rectangle('p',height=.2); flip=np.array([-1.,1.,1.])
        mirrors=[replace(s,id=s.id+'M',instance='mirror',base=s.base*flip,own=s.own*flip,
                         direction=s.direction*flip,faces=s.faces[:,::-1]) for s in (a,b)]
        result=collect([a,b,*mirrors])
        self.assertAlmostEqual(area(result,'r','p'),area(result,'rM','pM'),12)
        self.assertEqual(result['stats']['eligible_pairs'],2)

    def test_nonfinite_and_invalid_indices_are_rejected(self):
        s=rectangle('r'); bad=s.base.copy(); bad[0,0]=np.nan
        with PairDetector() as d:
            with self.assertRaises(ValueError): d.add(replace(s,base=bad))
            with self.assertRaises(ValueError): d.add(replace(s,faces=np.array([[0,1,10000]])))
            self.assertEqual(d.add(s),0)

    def test_footprint_membership_against_analytic_region(self):
        r=rectangle('r'); p=rectangle('p',(-.6,.8,-.4,.7)); v=p.own.copy(); v[:,2]=.7*v[:,0]+.1
        result=collect([r,replace(p,base=v,own=v)],.2); polygons=directed(result,'r','p')
        points=np.random.default_rng(42).uniform(-1,1,(500,2)); detected=np.zeros(500,dtype=bool)
        for f in polygons:
            poly=np.array(f['polygon']['world_receiver'])[:,:2]; edges=np.roll(poly,-1,axis=0)-poly
            delta=points[:,None,:]-poly; cross=edges[None,:,0]*delta[:,:,1]-edges[None,:,1]*delta[:,:,0]
            detected|=(cross>=-1e-10).all(axis=1)|(cross<=1e-10).all(axis=1)
        expected=(points[:,0]>=-.6)&(points[:,0]<=.8)&(points[:,1]>=-.4)&(points[:,1]<=.7)&(abs(.7*points[:,0]+.1)<=.2)
        np.testing.assert_array_equal(detected,expected)


if __name__=='__main__':
    unittest.main(verbosity=2)

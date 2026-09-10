"""Saved face identity controls attachment normals at creases and survives deformation."""
import unittest
import numpy as np
from core.authoring.attachment_binding import resolve
from core.authoring.errors import AuthoringError


def geometry():
    return dict(vertices=[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],triangles=[[0,1,2],[0,3,1]],matrix=np.eye(4))


class AuthoringBindingTests(unittest.TestCase):
    def test_vertex_at_crease_retains_selected_face_normal(self):
        data=geometry()
        point,normal=resolve(data,dict(tri_vidx=[0,1,2],tri_weights=[1,0,0]))
        other,other_normal=resolve(data,dict(tri_vidx=[0,3,1],tri_weights=[1,0,0]))
        np.testing.assert_equal(point,other)
        np.testing.assert_allclose(normal,[0,0,1])
        np.testing.assert_allclose(other_normal,[0,1,0])

    def test_vertex_preserving_deformation_moves_bound_point(self):
        data=geometry(); data['vertices'][1]=[2,0,0]
        point,normal=resolve(data,dict(tri_vidx=[0,1,2],tri_weights=[.2,.5,.3]))
        np.testing.assert_allclose(point,[1,.3,0])
        data['matrix'][0,0]=-1
        reflected,normal=resolve(data,dict(tri_vidx=[0,1,2],tri_weights=[.2,.5,.3]))
        np.testing.assert_allclose(reflected,[-1,.3,0])
        np.testing.assert_allclose(normal,[0,0,1])

    def test_invalid_topology_and_weights_are_rejected(self):
        for indices,weights,code in [([0,2,3],[1,0,0],'ATTACHMENT_TOPOLOGY_CHANGED'),
                                    ([0,1,2],[1,1,0],'ATTACHMENT_BINDING_INVALID')]:
            with self.assertRaises(AuthoringError) as raised:
                resolve(geometry(),dict(tri_vidx=indices,tri_weights=weights))
            self.assertEqual(raised.exception.code,code)

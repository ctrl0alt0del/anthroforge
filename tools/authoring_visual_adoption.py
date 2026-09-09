"""Exercise visual patch adoption, query, export and verified checkpointing."""
import json
import numpy as np
import bpy
from authoring_visual_skeleton import send, stage_regions
from anthroforge.adapters.authoring.scene import StaticScene

BASE = '/skeleton_profiles/default/'
PROOF = dict(basis='designer_authored', sources=[], note='Geometric inspection fixture; anatomical placement and axes remain unreviewed.')


def document(rows, inventory):
    profile = dict(reference_pose=inventory['reference_pose'], bindings={}, frames={}, controls={}, landmarks={}, regions={}, measurements={})
    value = dict(dsl='anthroforge.authoring', version='0.4.0', document_id='visual_regions_demo', revision=0, kind='skeleton_profile', concepts={}, entities={}, requirements={}, skeleton_profiles={'default': profile})
    for key, row in rows.items():
        value['concepts'][key] = dict(label='Geometric support '+key)
        value['entities'][key] = dict(concept='/concepts/'+key, side='unknown', label=key, evidence=PROOF)
        profile['bindings'][key] = dict(entity='/entities/'+key, scp_id=key, instance_id=row['selection']['owner'])
        profile['frames'][key] = dict(owner=BASE+'bindings/'+key, kind='box', axes=np.eye(3).tolist(), axis_labels=['local X', 'local Y', 'local Z'], evidence=PROOF)
        value['requirements'][key] = dict(target=BASE+'regions/'+key, need='region', depends_on=[BASE+'frames/'+key], consumers=[], constraints=[], required_state='resolved', evidence=PROOF)
    return value


def stage_adopt(root, folder):
    rows = stage_regions(root, folder)
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    value = document(rows, inventory)
    send(root, folder, 'draft', expect='unresolved', document_id=value['document_id'], document=value, expected_draft_revision=0, expected_scene_revision=inventory['revision'])
    results = {}
    for index, (key, row) in enumerate(rows.items()):
        results[key] = adopt_one(root, folder, value, key, row, index+1, index == len(rows)-1)
    exported = send(root, folder, 'export', document_id=value['document_id'])
    (folder/'adopted_profile.json').write_text(json.dumps(exported['document'], indent=2))
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    checkpoint = send(root, folder, 'checkpoint', document_id=value['document_id'], expected_scene_revision=inventory['revision'], expected_draft_revision=len(rows)+1)
    return dict(regions=results, checkpoint=checkpoint, document_id=value['document_id'])


def adopt_one(root, folder, document, key, row, revision, last):
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    params = dict(document_id=document['document_id'], expected_draft_revision=revision, expected_scene_revision=inventory['revision'])
    result = send(root, folder, 'propose_region', **params, selection_id=row['selection']['id'], requirement=key, frame=BASE+'frames/'+key, concept='inspection_patch', note=PROOF['note'])
    candidate = result['candidate']
    assert candidate['checks']['state'] == 'resolved', candidate
    send(root, folder, 'adopt_binding', expect='success' if last else 'unresolved', **params, candidate_id=candidate['id'], mode='resolved')
    queried = send(root, folder, 'query', document_id=document['document_id'], query=dict(kind='region', reference=BASE+'regions/'+key))
    assert abs(queried['matches'][0]['area']-row['selection']['area']) < 1e-6
    return dict(selection_area=row['selection']['area'], candidate=candidate, query=queried)

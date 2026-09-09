"""Verify reopened 0.4 native geometry without editing inflation controls."""
import json
import sys
from pathlib import Path
import bpy
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import anthroforge
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.native_scene import root_documents
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.publication import verify


def main():
    if not hasattr(bpy.types.Object, 'af_scp_system'):
        anthroforge.register()
    root = bpy.data.objects['AF_ROOT']
    port = StaticScene(root, bpy.context.scene)
    rows = [check(root, port, identity) for identity in root_documents(root)]
    assert rows, 'No published authoring document'
    result = dict(scene=bpy.data.filepath, publications=rows, verified=True)
    if '--' in sys.argv:
        Path(sys.argv[sys.argv.index('--')+1]).write_text(json.dumps(result, indent=2))
    print('SAVED_V04_GEOMETRY_PASS', json.dumps(result), flush=True)


def check(root, port, identity):
    request = dict(version='0.4.0', message_type='request', request_id='saved_check_'+identity, op='anatomy.export', params=dict(scene_id=root.name, document_id=identity))
    result = execute(request, root, bpy.context.scene)
    assert result['status'] == 'success', result
    record = json.loads(Path(result['assets'][0]['path']).read_text())
    ids = record['published']['native_ids']
    port.refresh(ids)
    verify(port, ids, record['compiled']['outputs'])
    return dict(document_id=identity, muscles=len(ids), verified=True)


if __name__ == '__main__':
    main()

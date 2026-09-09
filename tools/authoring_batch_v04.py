"""Run a JSON operation batch; authoring geometry stays in DSL documents."""
import json
import sys
from pathlib import Path
import bpy
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import anthroforge
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.scene import StaticScene


def resolve(root, template, directory, index):
    path = directory/f'{index:03}_request.json'
    if path.exists():
        return json.loads(path.read_text())
    request = json.loads(json.dumps(template))
    params = request['params']
    params['scene_id'] = root.name
    if params.get('expected_scene_revision') == 'current':
        params['expected_scene_revision'] = StaticScene(root, bpy.context.scene).capture_authoring()['revision']
    path.write_text(json.dumps(request, indent=2))
    return request


def run(root, queue, output, directory):
    directory.mkdir(parents=True, exist_ok=True)
    for index, template in enumerate(queue):
        request = resolve(root, template, directory, index)
        result = execute(request, root, bpy.context.scene)
        (directory/f'{index:03}_response.json').write_text(json.dumps(result, indent=2))
        print('AUTHORING_BATCH', request['op'], result['status'], flush=True)
        StaticScene(root, bpy.context.scene).save_copy(output)


def main():
    source, requests, output, directory = map(Path, sys.argv[sys.argv.index('--')+1:])
    assert source.resolve() != output.resolve(), 'Batch requires a separate output copy.'
    if not hasattr(bpy.types.Object, 'af_scp_system'):
        anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    queue = json.loads(requests.read_text())
    root = bpy.data.objects[queue[0]['params'].get('scene_id', 'AF_ROOT')]
    run(root, queue, output, directory)


if __name__ == '__main__':
    main()

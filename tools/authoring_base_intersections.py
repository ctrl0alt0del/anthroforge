"""blender -b body.blend -P tools/authoring_base_intersections.py -- [--root NAME] [--summary].

Print a live JSON diagnostic without writing a scene, journal or report file.
"""
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import anthroforge
from anthroforge.app.authoring.api import execute


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root'); parser.add_argument('--summary', action='store_true')
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])


def summary(response):
    if not response['entities']: return response
    report = response['entities'][0]['intersections']
    result = {k: v for k, v in report.items() if k not in ('pairs', 'surfaces')}
    result['pairs'] = [dict(first=p['first'], second=p['second'], counts=p['triangle_pair_counts'],
                            intersection=p['intersection']) for p in report['pairs']]
    return result


def main():
    args = arguments()
    if not hasattr(bpy.types.Object, 'af_scp_system'): anthroforge.register()
    roots = [o for o in bpy.context.scene.objects if len(o.af_vcp_system.muscles) and (not args.root or o.name == args.root)]
    if len(roots) != 1: raise ValueError('Select exactly one muscle root with --root NAME')
    request = dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request',
        request_id=str(uuid4()), op='muscles.base_intersections', params=dict(scene_id=roots[0].name))
    response = execute(request, roots[0], bpy.context.scene, Path(__file__).parent)
    print('BASE_INTERSECTIONS_JSON='+json.dumps(summary(response) if args.summary else response), flush=True)
    if response['status'] == 'failed' or not response['entities']: raise RuntimeError(response['diagnostics'])


if __name__ == '__main__':
    main()

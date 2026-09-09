"""Static geometry, section and provenance evidence from protocol artifacts."""
import json
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.authoring.metrics import sections
from authoring_report import render, measurements


def inventory(folder):
    paths = sorted(folder.glob('response_*.json'), key=lambda p: int(p.stem.split('_')[-1]), reverse=True)
    response = next(json.loads(p.read_text()) for p in paths if json.loads(p.read_text()).get('op') == 'anatomy.discover')
    value = json.loads(Path(response['assets'][0]['path']).read_text())
    return dict(meshes=[dict(id=key, **geometry) for key, geometry in value['geometry'].items()])


def figures(folder, entry, snapshot, bounds=None):
    result = []
    if entry.get('inventory_asset'):
        value = json.loads(Path(entry['inventory_asset']['path']).read_text())
        snapshot = dict(meshes=[dict(id=key, **geometry) for key, geometry in value['geometry'].items()])
    for asset in entry['compilation']['assets']:
        if asset['kind'] != 'geometry':
            continue
        output = json.loads(Path(asset['path']).read_text())
        if 'inflated' not in output:
            continue
        name = entry['document_id']
        render(folder, name, output, snapshot, entry['published'].get('published', False), bounds)
        result.append(dict(name=name, **measurements(output), sections=sections(output)))
    return result


def main():
    folder = Path(sys.argv[1])
    report = json.loads((folder/'exercise_report.json').read_text())
    snapshot = inventory(folder)
    bounds = paired_bounds(report['results'][0], report['variant'])
    rows = [row for entry in report['results']+[report['variant']] for row in figures(folder, entry, snapshot, bounds if 'biceps' in entry['document_id'] else None)]
    rows.extend(corrections(folder, report))
    (folder/'section_measurements.json').write_text(json.dumps(rows, indent=2))
    summary = [{k: v for k, v in row.items() if k != 'sections'} for row in rows]
    (folder/'measurements_summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def paired_bounds(first, second):
    points = []
    for entry in (first, second):
        for asset in entry['compilation']['assets']:
            if asset['kind'] == 'geometry':
                points.extend(json.loads(Path(asset['path']).read_text()).get('inflated', []))
    return (np.min(points, axis=0)-.3, np.max(points, axis=0)+.3) if points else None


def corrections(folder, report):
    rows = []
    for path in sorted((folder/'corrections_v2').glob('*_response.json')):
        result = json.loads(path.read_text())
        if result['op'] != 'anatomy.compile':
            continue
        request = json.loads(path.with_name(path.name.replace('_response', '_request')).read_text())
        name = request['params']['document_id']
        original = next(r for r in report['results'] if r['document_id'] == name)
        entry = dict(document_id=name+'_corrected_v2', compilation=result, published={}, inventory_asset=original['inventory_asset'])
        rows.extend(figures(folder, entry, {}))
    return rows


if __name__ == '__main__':
    main()

"""Build the local representative recipe package from explicit authored examples."""
import json
import hashlib
from pathlib import Path
import sys
import argparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.authoring.packages import merge
from core.authoring.validation import document

EXERCISE = Path('E:/development/WIP_models/dsl_experiment_v04')


def library():
    value = dict(dsl='anthroforge.authoring', version='0.4.0', document_id='representative_static_volumes', revision=0, kind='library', requires=['static_avatar.v1'])
    for name in ('biceps', 'pectoral', 'spinal'):
        example = json.loads((EXERCISE/('static_'+name+'.json')).read_text())
        example = corrected(example)
        content = {k: example[k] for k in ('sources', 'concepts', 'recipes', 'shape_presets', 'policies')}
        content['concepts'] = {k: v for k, v in content['concepts'].items() if k.startswith('muscle_')}
        merge(value, content, name)
    document(value)
    return value


def corrected(example):
    for path in sorted((EXERCISE/'corrections_v2').glob('*_response.json')):
        value = json.loads(path.read_text()).get('document', {})
        if value.get('document_id') == example['document_id']:
            return value
    return example


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='Directory for generated recipe examples and their lock file')
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)
    value = library()
    raw = (json.dumps(value, indent=2)+'\n').encode()
    (output/'representative_static_volumes.json').write_bytes(raw)
    lock = dict(path='representative_static_volumes.json', document_id=value['document_id'], version=value['version'], sha256=hashlib.sha256(raw).hexdigest())
    (output/'package_lock.json').write_text(json.dumps(lock, indent=2)+'\n')
    print(lock)


if __name__ == '__main__':
    main()

"""Run real torso cases in isolated Blender processes and assemble an offline gallery."""
import argparse
import html
import json
from pathlib import Path
import subprocess
import sys
import time
from blender import environment

ROOT = Path(__file__).resolve().parents[2]


def options():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blender', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    return parser.parse_args()


def memory(process):
    import psutil
    try:
        parent = psutil.Process(process.pid)
        return sum(p.memory_info().rss for p in [parent] + parent.children(recursive=True) if p.is_running())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0


def run_case(args, case, method, fixture):
    folder = args.output / (case + '-' + method.lower()); folder.mkdir(parents=True, exist_ok=True)
    command = [str(args.blender.resolve()), '-b', '--factory-startup', '--python-exit-code', '1',
               '--python', str(ROOT / 'tools/cloud/torso_validate.py'), '--', '--fixture', str(fixture.resolve()),
               '--output', str(folder.resolve()), '--case', case, '--method', method]
    started = time.monotonic(); peak = 0
    with (folder / 'execution.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment())
        while process.poll() is None:
            peak = max(peak, memory(process)); time.sleep(.25)
    result = dict(case=case, method=method, exit_code=process.returncode, peak_process_tree_rss=peak,
                  wall_seconds=time.monotonic()-started, directory=folder.name)
    (folder / 'execution.json').write_text(json.dumps(result, indent=2))
    return result


def gallery(output, rows):
    content = ['<!doctype html><meta charset="utf-8"><title>Cloud torso validation</title>',
               '<style>body{font:16px sans-serif;background:#eee}img{width:24%}section{margin:2em}</style>',
               '<h1>Cloud torso: production pipeline</h1><p>Known inherited geometry defects remain visible.</p>']
    for row in rows:
        content.append('<section><h2>' + html.escape(row['directory']) + '</h2><pre>' + html.escape(json.dumps(row, indent=2)) + '</pre>')
        for view in ('front', 'back', 'side', 'oblique'):
            content.append(f'<img alt="{view}" src="{row["directory"]}/{view}.png">')
        content.append(f'<p><a href="{row["directory"]}/debug.blend">Debug blend</a> · <a href="{row["directory"]}/report.json">Measurements</a></p></section>')
    (output / 'gallery.html').write_text('\n'.join(content), encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps(rows, indent=2))


def main(args):
    sys.path.insert(0, str(ROOT))
    if sys.platform.startswith('linux'):
        from core.linux_dependencies import ensure
        ensure()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = [run_case(args, 'baseline', 'LE', args.fixture), run_case(args, 'rebuild', 'LE', args.fixture)]
    if rows[-1]['exit_code'] == 0:
        reference = args.output / 'rebuild-le/debug.blend'
        for case in ('arc5', 'pec2'):
            for method in ('LE', 'FAST'):
                rows.append(run_case(args, case, method, reference)); gallery(args.output, rows)
    gallery(args.output, rows)
    if any(row['exit_code'] for row in rows): raise SystemExit('Torso validation failed; inspect execution logs')


if __name__ == '__main__':
    main(options())

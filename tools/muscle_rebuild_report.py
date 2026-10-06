"""Build a standalone, searchable HTML report from muscle rebuild probe runs."""
import argparse
from collections import defaultdict
import html
import json
from pathlib import Path
import statistics

PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8">
<title>AnthroForge muscle rebuild profile</title><style>
:root{color-scheme:light}body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#f3f5f7;color:#172333}
main{max-width:1300px;margin:auto;padding:36px}h1{font-size:34px;letter-spacing:-1px}h2{margin-top:40px}
h3{margin-top:30px}p{max-width:1000px}a{color:#126286}code{font-size:12px;overflow-wrap:anywhere}
.card{background:white;border:1px solid #d5dfe5;border-radius:10px;padding:20px;margin:18px 0}.scroll{overflow:auto;max-height:650px}
table{width:100%;border-collapse:collapse;font-size:13px;background:white}th,td{text-align:left;padding:9px;border-bottom:1px solid #dce4e9}
th{background:#e5edf2;position:sticky;top:0;z-index:1;cursor:pointer}td.num{text-align:right;font-variant-numeric:tabular-nums}
input,select{padding:9px;font:inherit;border:1px solid #adbfcb;border-radius:5px;min-width:220px;margin:6px 12px 12px 0}
.note{color:#4a6170;font-size:13px}.pill{padding:4px 10px;background:#ddeef0;border-radius:15px;font-size:12px}
.flow{display:flex;gap:10px;flex-wrap:wrap}.flow span{padding:10px;background:#e5edf2;border-radius:5px}
details{margin:15px 0}summary{cursor:pointer;font-weight:600}li{margin:8px 0}
</style><main><span class="pill">Blender muscle rebuild diagnostics</span>
<h1>Where muscle rebuilding spends time</h1><div id="narrative">__NARRATIVE__</div>
<h2>Run comparison</h2><p>Times below are medians of the recorded runs. Action and the following forced view-layer evaluation are separate measurements. Three repetitions describe this fixture; they are not a broad statistical benchmark.</p>
<div class="scroll"><table id="runs"></table></div>
<h2>Rebuild flow</h2><div class="flow"><span>Dependency selection</span><span>Fiber surface</span><span>Capture / validate / prepare</span><span>Inflate / clip / compose</span><span>Publish / control / material</span><span>Mirror</span><span>Blender evaluation</span></div>
<h2>Stage totals</h2><p class="note">Select one episode. Inclusive time contains descendants. Exclusive time subtracts other logged spans, but includes unwrapped work and logging overhead. Do not add inclusive rows together.</p>
<select id="episode"></select><input id="stageFilter" placeholder="Filter stage or function"><div class="scroll"><table id="stages"></table></div>
<h2>Per-muscle attribution</h2><p class="note">Capture and publication include their descendants. Numeric time counts the outermost spans carrying that muscle's identity inside the numerical batch. Shared batch overhead remains outside these rows.</p>
<div class="scroll"><table id="muscles"></table></div>
<h2>Function profile</h2><p class="note">cProfile records every executed Python function and supported C call, including unwrapped helpers. The whole-episode profiles include five seconds of settling activity. Each selection identifies whether it covers the action, settling, or both. Native internals are represented by exported API calls, not C++ line samples.</p>
<select id="profile"></select><input id="functionFilter" placeholder="Filter path or function"><div class="scroll"><table id="functions"></table></div>
<h2>Validity and source</h2><div id="validity" class="card"></div><h2>Raw evidence and reproduction</h2><div id="evidence"></div>
<p class="note">The initial failed smoke run is excluded. Instrumentation stays in tools/ and is activated only by the probe. The production rebuild implementation is unchanged by this investigation.</p>
</main><script>const DATA=__DATA__;
const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const ms=x=>Number(x).toFixed(2);
function table(id,headers,rows){document.getElementById(id).innerHTML='<thead><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')+'</tbody>';}
function stages(){let ep=document.getElementById('episode').value,q=document.getElementById('stageFilter').value.toLowerCase();let r=DATA.stages[ep]||[];table('stages',['Function','Calls','Inclusive ms','Exclusive ms','Max ms'],r.filter(x=>x.name.toLowerCase().includes(q)).map(x=>[x.name,x.calls,ms(x.total_ms),ms(x.self_ms),ms(x.max_ms)]));table('muscles',['Muscle','Name','Capture ms','Numeric ms','Publish ms','Attributed ms'],(DATA.muscles[ep]||[]).map(x=>[x.id,x.name,ms(x.capture),ms(x.numeric),ms(x.publish),ms(x.total)]));}
function profiles(){let key=document.getElementById('profile').value,q=document.getElementById('functionFilter').value.toLowerCase();table('functions',['Function / source','Calls','Self ms','Cumulative ms'],(DATA.functions[key]||[]).filter(x=>(x.file+' '+x.function).toLowerCase().includes(q)).map(x=>[x.function+' — '+x.file+':'+x.line,x.calls,ms(x.self_ms),ms(x.cumulative_ms)]));}
table('runs',['Run / scenario','N','Action ms','Range ms','Flush ms','Muscle stage ms','Mirror ms'],DATA.runs.map(x=>[x.run+' / '+x.scenario,x.n,ms(x.action_ms),x.range.map(ms).join(' – '),ms(x.flush_ms),ms(x.muscle_ms),ms(x.mirror_ms)]));
document.getElementById('episode').innerHTML=Object.keys(DATA.stages).map(x=>'<option>'+esc(x)+'</option>').join('');
document.getElementById('profile').innerHTML=Object.keys(DATA.functions).map(x=>'<option>'+esc(x)+'</option>').join('');
for(let id of ['episode','stageFilter'])document.getElementById(id).addEventListener('input',stages);
for(let id of ['profile','functionFilter'])document.getElementById(id).addEventListener('input',profiles);
document.getElementById('validity').innerHTML=DATA.validity.map(x=>'<p>'+esc(x)+'</p>').join('');
document.getElementById('evidence').innerHTML=DATA.evidence.map(x=>'<p><a href="'+esc(x.path)+'">'+esc(x.label)+'</a></p>').join('')+'<pre><code>'+esc(DATA.command)+'</code></pre>';
stages();profiles();</script></html>'''


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def median(values):
    return statistics.median(values) if values else 0


def driver(episode, name):
    return sum(r.get('driver_ms', {}).get('sync', {}).get(name, 0) for r in episode['telemetry'])


def run_rows(name, data):
    groups = defaultdict(list)
    for row in data['episodes']: groups[row['scenario']].append(row)
    return [dict(run=name, scenario=key, n=len(rows), action_ms=median([r['action_ms'] for r in rows]),
                 range=[min(r['action_ms'] for r in rows), max(r['action_ms'] for r in rows)],
                 flush_ms=median([r['flush_ms'] for r in rows]), muscle_ms=median([driver(r, 'muscle_sync_driver') for r in rows]),
                 mirror_ms=median([driver(r, 'vcp_mirror_sync_driver') for r in rows])) for key,rows in groups.items()]


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows: groups[row['name']].append(row)
    return sorted([dict(name=key, calls=len(values), total_ms=sum(v['ms'] for v in values),
                        self_ms=sum(v['self_ms'] for v in values), max_ms=max(v['ms'] for v in values))
                   for key,values in groups.items()], key=lambda row:-row['total_ms'])


def numeric_root(row, by_id, muscle_ids):
    parent = by_id.get(row['parent'])
    while parent:
        if parent['name'].endswith('.execute_muscle_work'): return True
        if parent.get('muscle') in muscle_ids: return False
        parent = by_id.get(parent['parent'])
    return False


def muscle_rows(rows, inventory):
    values = {m['id']:dict(id=m['id'], name=m['name'], capture=0., numeric=0., publish=0.) for m in inventory}
    by_id = {r['id']:r for r in rows}
    for row in rows:
        key = row.get('muscle'); stage = None
        if key not in values: continue
        if row['name'].endswith('.capture_muscle_work'): stage = 'capture'
        elif row['name'].endswith('._publish_one'): stage = 'publish'
        elif numeric_root(row, by_id, values): stage = 'numeric'
        if stage: values[key][stage] += row['ms']
    for row in values.values(): row['total'] = row['capture'] + row['numeric'] + row['publish']
    return sorted((r for r in values.values() if r['total']), key=lambda r:-r['total'])


def geometry_map(episode):
    return {r['name']:(r['digest'],r['state'],r['vertices'],r['faces']) for r in episode['after']}


def comparable_episodes(data, reference):
    if data['sha256'] != reference['sha256'] or data['code']['head'] != reference['code']['head']: return []
    if data['initial_meshes'] != reference['initial_meshes']: return []
    rows = [e for e in data['episodes'] if e['scenario'] != 'idle']
    matching = []
    for a, b in zip(rows, reference['episodes']):
        if (a['scenario'], a['repeat']) != (b['scenario'], b['repeat']): break
        matching.append(geometry_map(a) == geometry_map(b))
    return matching


def check_validity(name, data, reference):
    status = all(r['finite'] and r['state'] in ('', 'CURRENT') for e in data['episodes'] for r in e['after'])
    matching = comparable_episodes(data, reference)
    requests = [len(e['telemetry']) for e in data['episodes']]
    same = f'{sum(matching)}/{len(matching)} comparable episodes' if matching else 'not compared'
    return f'{name}: source unchanged={data.get("source_unchanged")}; finite/current geometry={status}; exact mesh parity={same}; request counts={requests}.'


def read_spans(folder, data, result):
    path = folder/'spans.jsonl'
    if not path.exists() or not path.stat().st_size: return
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    groups = defaultdict(list)
    for row in rows: groups[(row['episode'], row['phase'])].append(row)
    for (episode, phase), values in groups.items():
        key = f'{folder.name} / {episode} / {phase}'
        result['stages'][key] = aggregate(values)
        result['muscles'][key] = muscle_rows(values, data['muscles'])
    errors = sum(bool(r.get('logging_error')) for r in rows)
    result['validity'].append(f'{folder.name}: {len(rows):,} timed spans; {len(set(r["name"] for r in rows))} executed wrapped functions; {errors} logging errors.')


def read_functions(folder, result, data):
    for path in sorted(folder.glob('*.functions.json')):
        rows = load(path)
        for row in rows: row.pop('callers', None)
        key = folder.name+' / '+path.name.removesuffix('.functions.json')+' / '+data['args'].get('profile_scope', 'all')
        result['functions'][key] = sorted(rows, key=lambda r:-r['self_ms'])


def build(folder):
    reference = load(folder/'baseline/measurements.json')
    result = dict(runs=[], stages={}, muscles={}, functions={}, validity=[], evidence=[])
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or not (child/'measurements.json').exists(): continue
        data = load(child/'measurements.json')
        if not data.get('finished'): continue
        result['runs'].extend(run_rows(child.name, data)); result['validity'].append(check_validity(child.name, data, reference))
        read_spans(child, data, result); read_functions(child, result, data)
        result['evidence'].extend(evidence_rows(child))
    result['command'] = 'blender --factory-startup --addons anthroforge "'+reference['source']+'" --python "'+str(Path(__file__).with_name('muscle_rebuild_probe.py'))+'" -- --output NEW_DIRECTORY --instrument profile --repeats 3'
    return result


def evidence_rows(folder):
    return [dict(path=f'{folder.name}/{path.name}',label=f'{folder.name}: {path.name}') for path in sorted(folder.iterdir())
            if path.suffix in ('.json', '.jsonl', '.pstats', '.log') and path.stat().st_size]


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('folder'); parser.add_argument('--narrative')
    args = parser.parse_args(); folder = Path(args.folder); result = build(folder)
    narrative = Path(args.narrative).read_text(encoding='utf-8') if args.narrative else '<p>Detailed measurements and function logs.</p>'
    payload = json.dumps(result).replace('</', '<\\/')
    (folder/'report.html').write_text(PAGE.replace('__NARRATIVE__', narrative).replace('__DATA__',payload),encoding='utf-8')
    (folder/'analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(folder/'report.html')


if __name__ == '__main__': main()

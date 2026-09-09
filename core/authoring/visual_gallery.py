"""Local gallery controls emit protocol requests without changing the scene."""
import json

CONTROLS = '<p><label>Selection <select id="mode"><option value="pick">Point</option><option value="select_region">Area polygon</option></select></label> <button id="clear">Clear selection</button> <button id="copy">Copy request</button> <span id="coordinate">Click an image to address its visible surface.</span></p><pre id="request" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre>'
SCRIPT = r'''
const views = MANIFEST;
let active = null, points = [];
const output = document.getElementById('request');
function request() {
  if (!active || !points.length) return;
  const op = document.getElementById('mode').value;
  const params = {scene_id: SCENE, view_id: active, [op === 'pick' ? 'points' : 'polygon']: points};
  output.textContent = JSON.stringify({version:'0.4.0', message_type:'request', request_id:'visual-'+crypto.randomUUID(), op:'anatomy.'+op, params}, null, 2);
}
function clear() {
  points = []; output.textContent = '';
  document.querySelectorAll('svg.overlay').forEach(el => el.replaceChildren());
}
function selected(event) {
  const id = event.currentTarget.dataset.view;
  if (active !== id || document.getElementById('mode').value === 'pick') clear();
  active = id;
  const box = event.currentTarget.getBoundingClientRect();
  const point = [(event.clientX-box.left)/box.width, (event.clientY-box.top)/box.height];
  points.push(point);
  document.getElementById('coordinate').textContent = views[id]+' · '+point.map(v => v.toFixed(5)).join(', ');
  const coords = points.map(p => p.join(',')).join(' ');
  event.currentTarget.parentElement.querySelector('svg').innerHTML = '<polyline points="'+coords+'" fill="none" stroke="#ffbb41" stroke-width=".004"/>'+points.map(p => '<circle cx="'+p[0]+'" cy="'+p[1]+'" r=".007" fill="#ffbb41"/>').join('');
  request();
}
document.querySelectorAll('img[data-view]').forEach(el => el.addEventListener('click', selected));
document.getElementById('mode').addEventListener('change', clear);
document.getElementById('clear').addEventListener('click', clear);
document.getElementById('copy').addEventListener('click', () => navigator.clipboard.writeText(output.textContent));
'''


def script(views, scene_id):
    manifest = json.dumps({v['id']: v['label'] for v in views}).replace('<', '\\u003c')
    scene = json.dumps(scene_id).replace('<', '\\u003c')
    return '<script>'+SCRIPT.replace('MANIFEST', manifest).replace('SCENE', scene)+'</script>'

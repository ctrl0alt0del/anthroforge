"""Portable lossless PNG assets and a labelled HTML inspection index."""
import hashlib
import struct
import zlib
from html import escape
from .storage import atomic_write


def chunk(kind, payload):
    return struct.pack('!I', len(payload))+kind+payload+struct.pack('!I', zlib.crc32(kind+payload) & 0xffffffff)


def png(pixels):
    height, width, _ = pixels.shape
    raw = b''.join(b'\0'+row.tobytes() for row in pixels)
    header = struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', header)+chunk(b'IDAT', zlib.compress(raw))+chunk(b'IEND', b'')


def asset(store, raw, extension, kind):
    identity = hashlib.sha256(raw).hexdigest()
    path = store.directory/(identity+'.'+extension)
    atomic_write(path, raw)
    return dict(id='asset_'+identity, kind=kind, path=str(path), sha256=identity)


def image(store, pixels):
    return asset(store, png(pixels), 'png', 'image')


def index(store, views, title, scene_id='AF_ROOT'):
    from .visual_gallery import CONTROLS, script
    cards = [card(v) for v in views]
    style = 'body{background:#192028;color:#d8e0e8;font:16px system-ui;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}figure{margin:0}img{width:100%}figcaption{padding:8px}'
    body = '<!doctype html><meta charset="utf-8"><title>'+escape(title)+'</title><style>'+style+'</style><h1>'+escape(title)+'</h1><p>Local axes, not reviewed anatomical directions. Coordinates: normalized, top left. Clicks create a request to run in Blender; they do not select geometry until the response is evaluated.</p>'+CONTROLS+'<main>'+''.join(cards)+'</main>'+script(views, scene_id)
    return asset(store, body.encode(), 'html', 'inspection_index')


def card(view):
    path = escape(view['image']['path'].replace('\\', '/').split('/')[-1])
    label, identity = escape(view['label']), escape(view['id'])
    canvas = '<svg class="overlay" viewBox="0 0 1 1" preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none"></svg>'
    return '<figure><figcaption>'+label+' · '+identity[:16]+'</figcaption><div style="position:relative"><img style="display:block;cursor:crosshair" data-view="'+identity+'" src="'+path+'" alt="'+label+'">'+canvas+'</div></figure>'

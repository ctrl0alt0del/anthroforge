"""Dependency-free, persistent hexadecimal labels on inspection images only."""
import hashlib
import numpy as np

GLYPHS = dict(zip('0123456789ABCDEFOP', [
    '111101101101111', '010110010010111', '111001111100111', '111001111001111',
    '101101111001001', '111100111001111', '111100111101111', '111001010010010',
    '111101111101111', '111101111001111', '010101111101101', '110101110101110',
    '111100100100111', '110101101101110', '111100110100111', '111100110100100',
    '111101101101111', '110101110100100']))
PALETTE = [[255, 184, 76], [92, 205, 255], [235, 136, 237], [146, 226, 130], [255, 130, 117], [224, 223, 128]]


def identity(value, prefix):
    return prefix+hashlib.sha256(value.encode()).hexdigest()[:6].upper()


def color(label):
    return PALETTE[int(hashlib.sha256(label.encode()).hexdigest()[:8], 16) % len(PALETTE)]


def stamp(pixels, label, x, y):
    scale = 2 if pixels.shape[1] >= 256 else 1
    mask = np.concatenate([np.c_[np.array(list(GLYPHS[c])).reshape(5, 3) == '1', np.zeros(5, bool)] for c in label], axis=1)
    mask = np.repeat(np.repeat(mask, scale, axis=0), scale, axis=1)
    height, width = mask.shape
    x, y = int(np.clip(x, 1, pixels.shape[1]-width-1)), int(np.clip(y, 1, pixels.shape[0]-height-1))
    pixels[y-1:y+height+1, x-1:x+width+1] = [18, 24, 31]
    patch = pixels[y:y+height, x:x+width]
    patch[mask] = color(label)


def objects(pixels, buffer):
    owners = np.array([row[0] for row in buffer['identities']])
    visible = buffer['ids'] >= 0
    occupied = []
    for owner in sorted(set(owners)):
        yy, xx = np.nonzero(visible & (owners[np.maximum(buffer['ids'], 0)] == owner))
        if not len(xx):
            continue
        index = int(np.argmin((xx-np.median(xx))**2+(yy-np.median(yy))**2))
        place(pixels, identity(owner, 'O'), (xx[index], yy[index]), occupied)
    return pixels


def place(pixels, label, anchor, occupied):
    scale = 2 if pixels.shape[1] >= 256 else 1
    width, height = len(label)*4*scale+4, 5*scale+4
    candidates = [(anchor[0]+dx, anchor[1]+dy) for dy in range(0, pixels.shape[0], height) for dx in (0, -width, width)]
    candidates += [(x, y) for y in range(1, pixels.shape[0]-height, height) for x in range(1, pixels.shape[1]-width, width)]
    candidates = sorted(candidates, key=lambda p: (p[0]-anchor[0])**2+(p[1]-anchor[1])**2)
    for x, y in candidates:
        if not (1 <= x <= pixels.shape[1]-width and 1 <= y <= pixels.shape[0]-height):
            continue
        if any(x < a+w and x+width > a and y < b+h and y+height > b for a, b, w, h in occupied):
            continue
        occupied.append((x, y, width, height))
        leader(pixels, anchor, (x, y), color(label), occupied)
        stamp(pixels, label, x+2, y+2)
        return


def leader(pixels, start, end, tint, occupied=()):
    samples = max(2, int(np.linalg.norm(np.array(start)-end))+1)
    points = np.linspace(start, end, samples).astype(int)
    for x, y, width, height in occupied:
        points = points[~((points[:, 0] >= x) & (points[:, 0] < x+width) & (points[:, 1] >= y) & (points[:, 1] < y+height))]
    pixels[points[:, 1], points[:, 0]] = tint

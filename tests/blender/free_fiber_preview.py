"""Isolated preview of exported native geometry; never changes the saved scene."""
from pathlib import Path
import json
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

COLORS = ['#b53f38', '#b07818', '#246bb1', '#169a80']


def frame(ax, points, title):
    points = np.asarray(points); low, high = points.min(0), points.max(0)
    center = (low+high)/2; radius = max(high-low)*.55
    ax.set(xlim=(center[0]-radius, center[0]+radius), ylim=(center[1]-radius, center[1]+radius),
           zlim=(center[2]-radius, center[2]+radius), title=title)
    ax.set_box_aspect((1, 1, 1)); ax.set_proj_type('ortho'); ax.view_init(elev=22, azim=-52)
    ax.set_axis_off()


def curves(ax, data, mirrors=False, anchors=True):
    rows = data['display_curves'] if mirrors else [dict(fiber_id=k, points=v) for k, v in data['routes'].items()]
    for i, row in enumerate(rows):
        points = np.asarray(row['points']); color = COLORS[i % len(COLORS)]
        ax.plot(*points.T, color=color, linewidth=3., label=row['fiber_id'], zorder=20)
        if anchors:
            indices = data['anchors'][row['fiber_id']]['indices']
            ax.scatter(*points[indices].T, c='white', edgecolors=color, s=45, linewidths=1.8, depthshade=False, zorder=21)


def surface(ax, points, faces, color):
    mesh = Poly3DCollection(np.asarray(points)[np.asarray(faces)], facecolors=color, edgecolors='none', alpha=.88)
    ax.add_collection3d(mesh)


def make(path):
    data = json.loads((path / 'saved_geometry.json').read_text()); base = np.asarray(data['base'])
    fig = plt.figure(figsize=(14, 12), facecolor='white', layout='constrained')
    axes = [fig.add_subplot(2, 2, i+1, projection='3d', computed_zorder=False) for i in range(4)]
    frame(axes[0], base, 'Exact committed Free paths • shared anchors'); curves(axes[0], data)
    frame(axes[1], base, 'Native branched base • isolated'); surface(axes[1], base, data['faces'], '#b6c9d8'); curves(axes[1], data)
    frame(axes[2], base, 'Native inflated assembly • isolated'); surface(axes[2], data['inflated'], data['faces'], '#d6aba2')
    all_points = np.concatenate([row['points'] for row in data['display_curves']])
    frame(axes[3], all_points, 'Saved source and derived mirror paths'); curves(axes[3], data, mirrors=True, anchors=False)
    axes[0].legend(loc='lower left', frameon=False, fontsize=9)
    fig.suptitle('AF-24 • Native sampled path and downstream geometry', fontsize=18)
    fig.savefig(path / 'af24_free_paths.png', dpi=160); plt.close(fig)


if __name__ == '__main__': make(Path(sys.argv[1]))

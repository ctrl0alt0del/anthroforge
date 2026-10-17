"""Inspect actual saved leg-path experiments; no generated anatomical geometry."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

FOLDER = Path(__file__).resolve().parents[1] / '.artifacts/tightening'


def projection(points):
    first = points[-1]-points[0]; first /= np.linalg.norm(first)
    bow = (points-points[0]).mean(axis=0); bow -= np.dot(bow, first)*first
    bow /= np.linalg.norm(bow)
    return np.column_stack((first, bow))


def draw(row, axis, graph):
    points = np.asarray(row['points']); frame = projection(points)
    cases = [(None, 'Original', '#334155'), (0, 'One unrestricted step', '#ef6c32'), (4, 'One step, 0.5% length cap', '#119c72')]
    for index, label, color in cases:
        values = points if index is None else np.asarray(row['runs'][index]['points'])
        xy = (values-points[0])@frame; axis.plot(*xy.T, label=label, color=color, lw=2)
    axis.scatter(*((points[row['pins']]-points[0])@frame).T, color='black', s=15, zorder=5)
    axis.set_title(row['name'], fontsize=10); axis.set_aspect('equal', adjustable='datalim'); axis.grid(alpha=.2)
    runs = row['runs'][:4]; length = runs[0]['length_before']
    graph.plot([r['steps'] for r in runs], [100*r['max_displacement']/length for r in runs], 'o-', label=row['name'])


def main():
    rows = json.loads((FOLDER/'probe.json').read_text()); fig, axes = plt.subplots(3, 2, figsize=(13, 10))
    graph = axes.flat[-1]
    for row, axis in zip(rows, axes.flat): draw(row, axis, graph)
    axes.flat[0].legend(fontsize=8); graph.set(xlabel='Accepted-step budget (unrestricted)', ylabel='Maximum movement / original length (%)')
    graph.legend(fontsize=7); graph.grid(alpha=.2)
    fig.suptitle('Existing leg fibers: tightening from the same seed\nBlack dots: unchanged bone attachments; curves shown in each fiber\'s longitudinal plane')
    fig.tight_layout(); fig.savefig(FOLDER/'comparison.png', dpi=160)
    for row in rows:
        print(row['name'], [(r['steps'], r['limit'], r.get('length_reduction_fraction'), r.get('max_displacement')) for r in row['runs']])


if __name__ == '__main__': main()

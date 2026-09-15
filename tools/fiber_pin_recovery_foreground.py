"""Foreground production operators with frozen prepared mesh/binding fixture replay.

Only the disposable Blender process is changed. No union or resnap algorithm runs.
The original file is never saved. Freeze/replay is fixture setup, not production.
"""

from pathlib import Path
from types import SimpleNamespace
from time import perf_counter
import sys
import bpy
import numpy as np
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fiber_roadmap_foreground import Workflow
from anthroforge.core.visualization import fiber_refinement as refinement, sync_runner
from anthroforge.core.warnings import session as warning_session
from fiber_pin_recovery_qualification import read, bench
from anthroforge.core.vcp.fiber_pin_repair import _set_pin
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


class PreparedWorkflow(Workflow):
    def load(self):
        super().load()
        self.ready = False; self.setup_started = perf_counter(); self.job_done_at = self.planner_done_at = 0.

    def advance(self):
        if not self.ready:
            if warning_session.COORDINATOR.jobs or refinement._JOBS or sync_runner._PENDING or sync_runner._TAIL_PENDING:
                if perf_counter()-self.setup_started > 90: raise TimeoutError('fixture setup did not become idle')
                return .05
            bench.write(self.output/'setup.json', dict(elapsed_ms=1000*(perf_counter()-self.setup_started),
                warning_metrics=dict(warning_session.COORDINATOR.metrics)))
            self.ready = True
        if self.started and not refinement._JOBS and not self.job_done_at: self.job_done_at = perf_counter()
        self.note_planner()
        return super().advance()

    def note_planner(self):
        core = None if self.job is None else self.job.session.core_session
        if self.started and not self.planner_done_at and getattr(core, 'planner', None) is not None:
            self.planner_done_at = perf_counter()

    def complete(self):
        terminal = 1000*((self.job_done_at or perf_counter())-self.started)
        planned = 1000*(self.planner_done_at-self.started) if self.planner_done_at else None
        super().complete()
        self.rows[-1].update(job_terminal_ms=terminal, planner_ready_ms=planned)
        self.job_done_at = self.planner_done_at = 0.
        bench.write(self.output/'foreground.json', self.rows)


def replay_meshes(reference):
    for row in read(reference/'geometry.json')['after']:
        obj = bpy.data.objects[row['name']]
        assert obj.get('af_scp_id') == row['owner']
        mesh = bpy.data.meshes.new(obj.name+' prepared fixture')
        mesh.from_pydata(row['local'], [], row['triangles']); mesh.update()
        for material in obj.data.materials: mesh.materials.append(material)
        for modifier in obj.modifiers: modifier.show_viewport = modifier.show_render = False
        obj.data = mesh; obj.matrix_world = Matrix(row['matrix'])
    bpy.context.view_layer.update()


def replay_bindings(reference, root):
    with suppress_vcp_prop_updates():
        for fiber in root.af_vcp_system.fibers:
            path = reference/fiber.id/'union.json'
            if not path.exists(): continue
            for pin in read(path)['pins']:
                if 'new_raw' not in pin: continue
                change = SimpleNamespace(pin=SimpleNamespace(role=pin['old']['role'], index=pin['old']['authored_index']),
                    candidate=SimpleNamespace(owner=pin['owner'], raw=pin['new_raw']))
                _set_pin(fiber, change)


def check_capture(reference, root, identifier, output):
    captured, elapsed = bench.capture((root,), identifier)
    expected = read(reference/identifier/'union_request.json')
    errors = np.linalg.norm(np.asarray([a.point for a in captured.anchors])-[a['point'] for a in expected['anchors']], axis=1)
    bench.write(output/'fixture_check.json', dict(capture_ms=elapsed, pin_errors=errors,
        anchors=captured.anchors, colliders=len(captured.colliders), geometry_replay=True,
        bindings_replay=True, union=False, resnap=False))
    assert errors.max() <= captured.tolerances.pin_tolerance, errors


def main():
    source, output, identifier, reference = sys.argv[sys.argv.index('--')+1:]
    workflow = PreparedWorkflow(source, Path(output), identifier); workflow.load()
    reference = Path(reference); replay_meshes(reference); replay_bindings(reference, workflow.root)
    from anthroforge.core.vcp.fiber_pin_repair import _invalidate_preflight
    _invalidate_preflight(bpy.context.scene, workflow.root, {identifier})
    check_capture(reference, workflow.root, identifier, workflow.output)
    bpy.app.timers.register(workflow.tick, first_interval=.25)


if __name__ == '__main__': main()

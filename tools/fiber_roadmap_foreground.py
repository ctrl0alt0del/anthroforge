"""Actual foreground Recompute/Planner Preview workflow; no manual timer draining."""

from dataclasses import dataclass, field
from pathlib import Path
import sys
import traceback
from time import perf_counter
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_roadmap_qualification as q
from anthroforge.core.visualization import fiber_refinement as refinement, sync_runner
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp.runtime_state import fiber_recompute_status


@dataclass
class Workflow:
    source: str
    output: Path
    identifier: str
    root: object = None
    fiber: object = None
    phase: int = 0
    started: float = 0.0
    dispatched: float = 0.0
    deadline: float = 0.0
    previous: float = 0.0
    before: str = ''
    before_generation: int = 0
    before_persisted: str = ''
    job: object = None
    gaps: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    def tick(self):
        try: return self.advance()
        except Exception:
            q.write(self.output/'foreground_error.json', dict(error=traceback.format_exc()))
            bpy.ops.wm.quit_blender(); return None

    def advance(self):
        if self.root is None: self.load(); return .25
        if self.phase >= 3: self.finish(); return None
        if not self.started: self.launch(); return .005
        now = perf_counter(); self.gaps.append(1000*(now-self.previous)); self.previous = now
        if now > self.deadline: raise TimeoutError('foreground workflow exceeded 60 seconds')
        if refinement._JOBS or sync_runner._PENDING or sync_runner._TAIL_PENDING: return .005
        self.complete(); return .25

    def load(self):
        self.before = q.digest(self.source); roots = q.setup(self.source)
        self.root, self.fiber = next((r, f) for r in roots for f in r.af_vcp_system.fibers if f.id == self.identifier)
        for obj in bpy.context.view_layer.objects:
            if obj.select_get(): obj.select_set(False)
        self.root.select_set(True); bpy.context.view_layer.objects.active = self.root
        self.output.mkdir(parents=True, exist_ok=True)

    def launch(self):
        with suppress_vcp_prop_updates():
            self.fiber.preview_planner_route = self.phase == 0; self.fiber.use_warm_start = self.phase == 2
        proxy = self.proxy(); self.before_generation = proxy.get('af_fiber_output_generation', 0)
        self.before_persisted = proxy.get('af_fiber_points_world', '')
        self.started = self.previous = perf_counter(); self.deadline = self.started+60
        result = bpy.ops.af.recompute_fiber(fiber_id=self.identifier)
        self.dispatched = perf_counter(); self.gaps = []
        if result != {'FINISHED'}: raise RuntimeError(f'recompute operator: {result}')
        self.job = next((job for job in refinement._JOBS.values() if job.fiber_id == self.identifier), None)

    def proxy(self):
        return next(o for o in bpy.context.scene.objects if o.get('af_fiber_proxy') and
                    not o.get('af_fiber_mirror_proxy') and o.get('af_fiber_id') == self.identifier)

    def complete(self):
        proxy = self.proxy(); phase = ('PLANNER_PREVIEW', 'COLD_RECOMPUTE', 'WARM_RECOMPUTE')[self.phase]
        core = None if self.job is None else self.job.session.core_session
        row = dict(phase=phase, full_ms=1000*(perf_counter()-self.started), operator_ms=1000*(self.dispatched-self.started),
            timer_gaps_ms=self.gaps, status=fiber_recompute_status(self.fiber), background=bpy.app.background,
            output_state=proxy.get('af_fiber_output_state'), generation_before=self.before_generation,
            generation_after=proxy.get('af_fiber_output_generation'), planner=None if core is None else core.planner,
            points=[tuple(proxy.matrix_world @ point.co.xyz) for point in proxy.data.splines[0].points])
        if self.phase == 0: assert proxy.get('af_fiber_points_world', '') == self.before_persisted
        else: assert row['output_state'] == 'CURRENT' and row['generation_after'] == self.before_generation+1
        self.rows.append(row); q.write(self.output/'foreground.json', self.rows)
        print('FOREGROUND', phase, row['full_ms'], row['status'], flush=True)
        self.phase += 1; self.started = 0.0

    def finish(self):
        after = q.digest(self.source); assert after == self.before
        q.write(self.output/'source_hash.json', dict(before=self.before, after=after))
        bpy.ops.wm.quit_blender()


def main():
    values = sys.argv[sys.argv.index('--')+1:]
    workflow = Workflow(values[0], Path(values[1]), values[2] if len(values)>2 else 'FIBER_170')
    workflow.load()
    bpy.app.timers.register(workflow.tick, first_interval=.25)


if __name__ == '__main__': main()

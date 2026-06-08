def _ready(ctx):
    return ctx.root is not None and ctx.scene is not None


def emit_sync(sync_fn, ctx, request):
    if not _ready(ctx):
        return
    sync_fn(root=ctx.root, scene=ctx.scene, dirty_hints=request.dirty_hints, bake=request.bake, source=request.source, event_type=request.event_type, payload=request.payload)


def queue_runtime(ctx, request):
    if not _ready(ctx) or ctx.scheduler is None:
        return
    ctx.scheduler(ctx, request)


def run_runtime_now(ctx, request, runner):
    if not _ready(ctx):
        return
    runner(root=ctx.root, scene=ctx.scene, dirty_hints=request.dirty_hints, bake=request.bake, gate_meta=request.gate_meta())

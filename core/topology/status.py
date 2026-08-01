class TopologyCancelled(RuntimeError):
    pass


def check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise TopologyCancelled("Topology generation cancelled.")

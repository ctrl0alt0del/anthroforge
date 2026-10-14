"""Public composition port for modules that report issues or register plugins."""
_SYSTEM = None


def configure(system):
    global _SYSTEM
    _SYSTEM = system


def system():
    if _SYSTEM is None:
        raise RuntimeError("Issue system has not been initialized")
    return _SYSTEM


def report(issue):
    system().reporting.report(issue)


def register_listener(listener):
    return system().listening.register(listener)


def register_solver(solver):
    return system().resolution.register(solver)


def register_target(kind, callback):
    return system().presentation.register_target(kind, callback)

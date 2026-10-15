"""Process-local, reconstructible native preparation; durable reference stays in Blender."""
from dataclasses import replace
from .reference import DeformationSettings, canonical
from .native import PreparedSolver


class SolverCache:
    def __init__(self):
        self.entries = {}

    def acquire(self, reference, method, settings, cancel_path):
        configuration = replace(DeformationSettings(**settings),method=method)
        key = reference.signature,method,canonical(settings)
        if key not in self.entries:
            self.clear()
            self.entries[key] = PreparedSolver(reference,configuration,cancel_path)
        prepared = self.entries[key]; prepared.set_cancel_path(cancel_path)
        return prepared

    def clear(self):
        for prepared in self.entries.values(): prepared.close()
        self.entries.clear()

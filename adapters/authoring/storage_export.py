"""Scoped export backup policy; ordinary Blender preferences are restored."""
from contextlib import contextmanager
from pathlib import Path
import bpy
from ...core.authoring.storage_pool import policy


@contextmanager
def export_preferences(path):
    settings = policy(Path(path).resolve().parent)
    preferences = bpy.context.preferences.filepaths
    previous = preferences.save_version
    try:
        if settings and 'export_save_versions' in settings:
            value = int(settings['export_save_versions'])
            if not 0 <= value <= 32:
                raise ValueError('Invalid export backup count')
            preferences.save_version = value
        yield settings
    finally:
        preferences.save_version = previous

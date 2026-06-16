def attachments_enabled(scene):
    if scene is None:
        return True
    return bool(getattr(scene, "af_attachments_enabled", True))

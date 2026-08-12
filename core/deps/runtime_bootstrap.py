from .builtin_drivers import (
    BlobSyncDriver,
    FiberSyncDriver,
    MuscleSyncDriver, FiberSurfaceSyncDriver,
    RuntimeGraphDriver,
    RuntimeIntentDriver,
    SCPAttachmentCaptureDriver,
    SCPMirrorRoleDriver,
    SCPSyncDriver,
    SoftTissueSyncDriver,
    VCPMirrorSyncDriver,
)
from .drivers import register_dependency_driver


def _builtin_drivers():
    return (
        RuntimeGraphDriver(), RuntimeIntentDriver(), SCPMirrorRoleDriver(), SCPAttachmentCaptureDriver(), SCPSyncDriver(),
        FiberSyncDriver(), FiberSurfaceSyncDriver(), MuscleSyncDriver(), BlobSyncDriver(), SoftTissueSyncDriver(), VCPMirrorSyncDriver(),
    )


def register_builtin_dependency_drivers():
    for driver in _builtin_drivers():
        register_dependency_driver(driver, replace=True)

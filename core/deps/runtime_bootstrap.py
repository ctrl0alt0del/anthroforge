from .builtin_drivers import (
    BlobSyncDriver,
    FiberSyncDriver,
    MuscleSyncDriver,
    RuntimeGraphDriver,
    RuntimeIntentDriver,
    SCPAttachmentCaptureDriver,
    SCPMirrorRoleDriver,
    SCPSyncDriver,
    VCPMirrorSyncDriver,
)
from .drivers import register_dependency_driver


def _builtin_drivers():
    return (
        RuntimeGraphDriver(), RuntimeIntentDriver(), SCPMirrorRoleDriver(), SCPAttachmentCaptureDriver(), SCPSyncDriver(),
        FiberSyncDriver(), MuscleSyncDriver(), BlobSyncDriver(), VCPMirrorSyncDriver(),
    )


def register_builtin_dependency_drivers():
    for driver in _builtin_drivers():
        register_dependency_driver(driver, replace=True)

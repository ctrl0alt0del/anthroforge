from dataclasses import dataclass


@dataclass(frozen=True)
class ActionResult:
    ok: bool = False
    message: str = ""
    level: str = "ERROR"
    value: object = None


def success(message="", level="INFO", value=None):
    return ActionResult(True, str(message or ""), str(level or "INFO"), value)


def failure(message="", level="ERROR", value=None):
    return ActionResult(False, str(message or ""), str(level or "ERROR"), value)

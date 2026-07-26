class SkinCancelled(RuntimeError):
    pass


def check_cancelled(cancelled):
    if cancelled and cancelled():
        raise SkinCancelled("Draft skin generation was cancelled.")


def report(progress, stage, amount, message=""):
    if progress:
        progress(str(stage), float(amount), str(message))

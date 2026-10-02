"""Input-stage errors and request-local accepted work awaiting publication."""


class ControlApplicationFailure(RuntimeError):
    def __init__(self, value, changed, cause):
        super().__init__(f'Muscle control application failed: {cause}')
        self.value = value
        self.changed = frozenset(changed)


def remember_application_error(meta, error):
    progress = (meta or {}).get('runtime_progress')
    if progress is None:
        raise error
    progress.application_errors.append(error)
    return error.changed


def remember_accepted_work(meta, muscle_ids):
    progress = (meta or {}).get('runtime_progress')
    if progress is not None and muscle_ids:
        progress.accepted_dirty.setdefault('MUSCLE', set()).update(muscle_ids)


def record_source_publication(meta, muscle_ids):
    progress = (meta or {}).get('runtime_progress')
    if progress is not None:
        progress.published_muscles.update(muscle_ids or ())


def acknowledge_publication(meta):
    progress = (meta or {}).get('runtime_progress')
    if progress is None:
        return
    pending = progress.accepted_dirty.get('MUSCLE', set())
    pending.difference_update(progress.published_muscles)
    progress.published_muscles.clear()
    if not pending:
        progress.accepted_dirty.pop('MUSCLE', None)
    else:
        raise RuntimeError(f'Accepted Muscle work awaits publication: {sorted(pending)}')


def finish_runtime_work(meta):
    acknowledge_publication(meta)
    progress = (meta or {}).get('runtime_progress')
    errors = [] if progress is None else progress.application_errors
    if errors:
        import traceback
        for error in errors[1:]: traceback.print_exception(error)
        raise errors[0]

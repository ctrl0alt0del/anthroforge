"""Publication authority independent of solver progress and geometry caches."""
from .free_path import is_free


def token(root, fiber):
    from ..warnings import session
    return (session.EPOCH, int(root.session_uid), int(fiber.as_pointer()),
            str(getattr(fiber, 'behavior_mode', 'CONTROLLED')), int(fiber.get('af_path_authority', 0)),
            int(getattr(fiber, 'source', fiber).get('af_path_authority', 0)))


def invalidate(fiber):
    fiber['af_path_authority'] = int(fiber.get('af_path_authority', 0)) + 1
    fiber['af_fiber_request_token'] = int(fiber.get('af_fiber_request_token', 0)) + 1


def owns(root, fiber, saved):
    return root is not None and fiber is not None and not is_free(fiber) and token(root, fiber) == saved


def capture_session(session):
    session.path_authority = token(session.root, session.fiber)
    return session


def session_owned(session):
    return owns(getattr(session, 'root', None), getattr(session, 'fiber', None), getattr(session, 'path_authority', ()))

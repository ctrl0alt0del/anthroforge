"""Live native profile dispatch, revision guards and durable postcondition receipts."""
from contextlib import contextmanager
from time import perf_counter
from ...core.authoring.codec import digest, encode
from ...core.authoring.errors import require, AuthoringError
from ...core.authoring.reports import response, entity
from ...core.authoring.storage import atomic_write

KINDS = {"muscles.profile_configure": "muscle_profile_configure.v1", "muscles.create_from_surface": "muscle_from_surface.v1"}
OPS = ("muscles.profile_inspect", "muscles.profile_preview", *KINDS)


def operations():
    return dict.fromkeys(OPS, dispatch)


def dispatch(service, request, started=None):
    started = perf_counter() if started is None else started
    try:
        key = [service.inventory["root_id"] or service.inventory["scene_id"], request["request_id"]]
        _check_digest(_request_record(service, request, key), request)
        if request["op"] in KINDS:
            return _mutating(service, request, key, started)
        return _reading(service, request, key, started)
    except AuthoringError:
        raise
    except ValueError as error:
        raise AuthoringError(str(error).split(":")[0], str(error)) from error


def _check_digest(record, request):
    require(not record or record["digest"] == digest(request), "REQUEST_ID_REUSED")


def _request_record(service, request, key):
    return service.store.get("v04_requests", key) or service.scene.profile_recover_marker(request["request_id"], None)


def _target(request):
    params = request["params"]
    if "target" in params:
        return params["target"]
    return dict(muscle_id=params["muscle_id"]) if "muscle_id" in params else dict(fiber_surface_id=params["surface_id"])


def _guards(service, request, state):
    service.check(request["params"])
    require(state["base_revision"] == request["params"]["expected_base_revision"], "STALE_BASE_REVISION")


def _reading(service, request, key, started):
    state = service.scene.profile_inspect(_target(request))
    assets = []
    if request["op"] == "muscles.profile_preview":
        _guards(service, request, state)
        state, geometry = service.scene.profile_preview(_target(request), request["params"]["configuration"])
        if request["params"].get("include_geometry"):
            assets.append(service.store.asset(geometry, "muscle_profile_preview"))
    result = _response(service, request, state, started)
    result["assets"] = assets
    service.store.put("v04_requests", key, dict(digest=digest(request), response=result))
    return result


def _mutating(service, request, key, started):
    kind = KINDS[request["op"]]
    record = service.store.get("v04_profile_receipts", key) or service.scene.profile_recover_marker(request["request_id"], kind)
    if record:
        return _replay(service, request, key, record, started)
    state = service.scene.profile_inspect(_target(request))
    _guards(service, request, state)
    params, create = request["params"], request["op"] == "muscles.create_from_surface"
    config = params.get("initial_configuration") if create else params["configuration"]
    with _journal_transaction(service.store, key):
        with service.scene.profile_mutation(_target(request), config, create, params.get("name", "")) as identity:
            return _record_mutation(service, request, key, identity, started)


def _postcondition(state, kind):
    value = {name: state[name] for name in ("muscle_id", "source_id", "base_revision")}
    if kind == "muscle_profile_configure.v1":
        value["configuration"] = state["configuration"]
        value["native_state"] = state["native_state"]
    return digest(value)


def _record_mutation(service, request, key, identity, started):
    state = service.scene.profile_inspect(dict(muscle_id=identity))
    kind = KINDS[request["op"]]
    receipt = dict(kind=kind, version=1, request_id=request["request_id"], digest=digest(request), root_scope=key[0],
        muscle_id=identity, source_id=state["source_id"], base_revision=state["base_revision"], postcondition=_postcondition(state, kind))
    service.scene.profile_marker(identity, kind, receipt)
    service.identities.remember_journal(service.store.directory)
    result = _response(service, request, state, started, published=True, receipt=_descriptor(receipt))
    service.store.put("v04_profile_receipts", key, receipt)
    service.store.put("v04_requests", key, dict(digest=digest(request), response=result))
    return result


def _replay(service, request, key, receipt, started):
    _check_digest(receipt, request)
    code = "STALE_CREATION_RECEIPT" if receipt["kind"] == "muscle_from_surface.v1" else "STALE_PROFILE_RECEIPT"
    marker = service.scene.profile_marker(receipt["muscle_id"], receipt["kind"])
    require(marker == receipt and receipt["root_scope"] == key[0], code)
    state = service.scene.profile_inspect(dict(muscle_id=receipt["muscle_id"]))
    require(state["current"] and _postcondition(state, receipt["kind"]) == receipt["postcondition"], code)
    result = _response(service, request, state, started, replayed=True, receipt=_descriptor(receipt))
    with _journal_transaction(service.store, key):
        service.store.put("v04_profile_receipts", key, receipt)
        service.store.put("v04_requests", key, dict(digest=digest(request), response=result))
    return result


def _descriptor(receipt):
    return {key: receipt[key] for key in ("kind", "request_id", "muscle_id")}


def _response(service, request, state, started, **extra):
    revision = service.scene.capture_authoring()["revision"]
    result = response(request, revision)
    identity = state["muscle_id"] or state["source_id"]
    result.update(entities=[entity(identity, "muscle" if state["muscle_id"] else "fiber_surface", **{k: v for k, v in state.items() if v is not None})], **extra)
    result["cost"]["total_ms"] = (perf_counter()-started)*1000
    return result


@contextmanager
def _journal_transaction(store, key):
    previous = {category: store.get(category, key) for category in ("v04_profile_receipts", "v04_requests")}
    try:
        yield
    except BaseException:
        for category, value in previous.items():
            path = store.path(category, key)
            if value is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, encode(value).encode("utf-8"))
        raise

"""Small operation dispatcher with explicit dependencies."""
import logging
from ...core.authoring.codec import decode, digest
from ...core.authoring.validation import request as validate_request
from ...core.authoring.errors import AuthoringError, require
from ...core.authoring.reports import response
from . import native_queries as queries, commands, native_drafts as drafts


class AuthoringInterpreter:
    def __init__(self, scene, solver, store, contacts=None, warnings=None):
        from ...core.warnings.query import WarningQuery
        self.scene, self.solver, self.store = scene, solver, store
        self.warnings, self.replayed = warnings or WarningQuery(), False
        self.contacts = contacts
        self.snapshot, self.last_job = None, None

    def execute(self, payload):
        self.replayed = False
        request, result = self._respond(payload)
        return self.warnings.feedback(request, result, self.replayed)

    def _respond(self, payload):
        request = {}
        try:
            request = validate_request(decode(payload))
            return request, self._execute(request)
        except AuthoringError as error:
            return request, self._unresolved(request, error)
        except Exception:
            logging.getLogger(__name__).exception("Authoring request failed")
            result = response(request)
            result.update(status="failed",diagnostics=[AuthoringError("INTERNAL_ERROR","See the addon log; the request did not complete.").diagnostic()])
            return request, result

    def _execute(self, request):
        from .request_identity import request_scope
        with request_scope(self.scene.root, request, self.store): return self._dispatch(request)

    def _dispatch(self, request):
        if request['op'] == 'fibers.tighten_preview':
            from .native_tightening import execute
            return execute(self.scene, request)
        from . import native_free
        if request['op'] in native_free.OPERATIONS: return native_free.execute(self.scene, request, self.store)
        from . import native_branches, native_fibers
        if request['op'] in (*native_branches.OPERATIONS, *native_fibers.OPERATIONS):
            return execute_native(self, request, native_branches, native_fibers)
        if request['op'] == 'warnings.list':
            return dict(response(request, "unavailable"), warnings=self.warnings.list(request['params']))
        if request['version'] == '0.4.0':
            return execute_anatomy(self, request)
        return self._execute_compatibility(request)

    def _execute_compatibility(self, request):
        snapshot = self.snapshot = self.scene.capture(request["params"]["scene_id"])
        cached = receipt(self,request) or self.store.get("requests",[snapshot.id,request["request_id"]])
        if cached:
            self.replayed = True
            require(cached["digest"] == digest(request),"REQUEST_ID_REUSED")
            require(cached["response"]["scene_revision"] == snapshot.revision,"STALE_REVISION")
            return cached["response"]
        handlers = dict(describe=queries.describe,resolve=queries.resolve,inspect=queries.inspect,
                        export=queries.export,job_status=queries.job_status,build=commands.build,
                        patch=commands.patch,resume=commands.resume,draft=drafts.draft,
                        patch_draft=drafts.patch_draft,publish_draft=drafts.publish_draft)
        result = handlers[request["op"]](self,request,snapshot)
        cache_response(self, request, result)
        return result

    def _unresolved(self, request, error):
        result = response(request, self.snapshot.revision if self.snapshot else "unavailable")
        result.update(status="unresolved", diagnostics=[error.diagnostic()])
        if hasattr(error, "preview"):
            result["assets"].append(self.store.asset(error.preview))
            from ...core.authoring.inspection import svg
            result["assets"].append(self.store.image(svg(self.snapshot, error.preview, "unpublished preview")))
        if self.last_job:
            self.last_job["job"]["state"] = "unresolved"
            self.store.put("jobs", [self.snapshot.id, self.last_job["job"]["id"]], self.last_job)
            result["job"] = self.last_job["job"]
        return result


def cache_response(service, request, result):
    try:
        service.store.put("requests", [service.snapshot.id, request["request_id"]], dict(digest=digest(request), response=result))
    except OSError:
        logging.getLogger(__name__).exception("Could not persist request replay receipt")
        result["diagnostics"].append(dict(code="RECEIPT_WRITE_FAILED", severity="warning", message="Request completed; replay receipt unavailable."))


def execute_native(service, request, branches, fibers):
    """Identity is reserved by the facade; handlers retain their live replay."""
    handler = branches if request['op'] in branches.OPERATIONS else fibers
    return handler.execute(service.scene, request)


def receipt(service, request):
    params = request["params"]
    identity = params.get("document_id", params.get("document", {}).get("document_id"))
    value = queries.previous_document(service, service.snapshot.id, identity) if identity else None
    saved = (value or {}).get("receipt")
    return saved if saved and saved["request_id"] == request["request_id"] else None


def execute_anatomy(service, request):
    from .service import AuthoringService
    scene = service.scene
    if not hasattr(scene, 'capture_authoring'):
        from ...adapters.authoring.scene import StaticScene
        scene = StaticScene(scene.root, scene.scene)
    return AuthoringService(scene, service.solver, service.store).execute(request)

"""Shared warning extension for the pinned authoring protocol generators."""
S = dict(type="string")
I = dict(type="integer", minimum=0)


def warning_request(version):
    params = dict(scene_id=dict(S, minLength=1), offset=I, limit=dict(I, maximum=200))
    params.update({name: S for name in ("scene", "root", "entity", "kind", "code", "type", "authoring_id", "provider", "stage", "severity")})
    fields = dict(dsl=dict(enum=["anthroforge.authoring.protocol"]), version=dict(enum=[version]),
                  message_type=dict(enum=["request"]), request_id=dict(S, minLength=1), op=dict(enum=["warnings.list"]))
    fields["params"] = dict(type="object", properties=params, required=["scene_id"], additionalProperties=False)
    return dict(type="object", properties=fields, required=["version", "message_type", "request_id", "op", "params"], additionalProperties=False)


def warning_state():
    fields = {key: dict(type="object") for key in ("scope", "counts", "telemetry")}
    fields.update({key: S for key in ("epoch", "source_scene_revision", "check_token")})
    fields.update(repository_revision=I, total=I, complete=dict(type="boolean"))
    fields.update(records=dict(type="array", maxItems=200, items=dict(type="object")),
                  failures=dict(type="array"), source_generations=dict(type="array"))
    fields["discovery"] = dict(enum=["UNSCANNED", "PENDING", "CHECKING", "COMPLETE", "FAILED", "CANCELLED"])
    required = ["epoch", "repository_revision", "scope", "total", "records", "complete", "discovery", "counts",
                "source_scene_revision", "source_generations", "check_token"]
    return dict(type="object", properties=fields, required=required, additionalProperties=False)


def extend(definitions, operations, version):
    definitions.update(warning_request=warning_request(version), warning_state=warning_state())
    operations.insert(0, {"$ref": "#/$defs/warning_request"})

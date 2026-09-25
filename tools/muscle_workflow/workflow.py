"""Artifact and retrieval CLI for the AnthroForge reconstruction skill."""

import argparse
import json

from common import STAGES, read_json, reference
from contracts import validate_record, verify_artifacts
from knowledge import get_record, latest_records, reindex, remember, feature_catalogue
from runs import context, initialize
from service import client
from usage import check_usage, record_usage, usage_summary
from catalogue import catalogue_summary, save_catalogue
from build_provenance import capture_authoring


def add_command(commands, name, options):
    command = commands.add_parser(name)
    for flag, kwargs in options:
        command.add_argument(flag, **kwargs)
    return command


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    add_command(commands, "init-run", [("--name", {"required": True}),
        ("--source", {"required": True}), ("--target", {})])
    add_context_command(commands)
    add_command(commands, "remember", [("--file", {"required": True})])
    add_command(commands, "validate", [("--file", {"required": True}),
        ("--kind", {"choices": ["lesson", "feedback", "handoff", "librarian_brief", "usage"], "required": True})])
    add_command(commands, "reference", [("--file", {"required": True})])
    add_command(commands, "reindex", [])
    add_command(commands, "health", [])
    add_memory_commands(commands)
    return result


def add_context_command(commands):
    add_command(commands, "context", [("--stage", {"choices": STAGES, "required": True}),
        ("--query", {"required": True}), ("--run", {"required": True}),
        ("--inputs", {"nargs": "*", "default": []}),
        ("--features", {"nargs": "*", "default": []}),
        ("--category", {"choices": ["modeling", "engineering", "history", "all"], "default": "modeling"}),
        ("--full", {"action": "store_true"})])


def add_memory_commands(commands):
    add_command(commands, "lesson", [("--id", {"required": True}), ("--revision", {"type": int})])
    add_command(commands, "features", [("--stage", {"choices": STAGES, "required": True})])
    add_command(commands, "record-use", [("--run", {"required": True}), ("--file", {"required": True})])
    add_command(commands, "usage", [("--run", {"required": True})])
    add_command(commands, "catalogue", [("--file", {})])
    add_command(commands, "catalogue-save", [("--file", {"required": True}),
        ("--expected-revision", {"type": int, "required": True})])
    add_command(commands, "authoring-version", [])


def check_context_inputs(record, context_record):
    if context_record["run_id"] != record["run_id"]:
        raise ValueError("Context belongs to another run")
    if context_record["input_artifacts"] != record["input_artifacts"]:
        raise ValueError("Refresh the context and librarian brief for these inputs")


def check_brief_context(record):
    check_context_inputs(record, read_json(record["context_receipt"]["path"]))
    current = {item["id"]: item for item in latest_records()}
    for item in record["lessons"]:
        actual = current.get(item["id"], {})
        if actual.get("revision") != item["revision"] or actual.get("status") == "superseded":
            raise ValueError("Refresh missing or outdated lesson: " + item["id"])


def check_handoff_context(record):
    context_record = read_json(record["context_receipt"]["path"])
    brief = read_json(record["librarian_brief"]["path"])
    validate_record(brief, "librarian_brief")
    verify_artifacts(brief)
    check_brief_context(brief)
    if context_record["stage"] != record["stage"]:
        raise ValueError("Context receipt is for another stage")
    for upstream in (context_record, brief):
        check_context_inputs(record, upstream)


def validate(path, kind):
    record = validate_record(read_json(path), kind)
    verify_artifacts(record)
    if kind == "handoff":
        check_handoff_context(record)
    if kind == "librarian_brief":
        check_brief_context(record)
    if kind == "usage":
        check_usage(record)
    return {"valid": True, "kind": kind, "artifact": reference(path),
            "scope": "Record structure and file versions; not anatomical certification"}


def dispatch(args):
    if args.command == "init-run":
        return {"run": str(initialize(args.name, args.source, args.target))}
    if args.command == "context":
        return context(args.run, args.stage, args.query, args.inputs, args.features, args.category, args.full)
    if args.command == "remember":
        return remember(args.file)
    if args.command == "validate":
        return validate(args.file, args.kind)
    return dispatch_memory(args)


def dispatch_memory(args):
    actions = {
        "reference": lambda: reference(args.file), "reindex": reindex,
        "lesson": lambda: get_record(args.id, args.revision),
        "features": lambda: feature_catalogue(args.stage),
        "record-use": lambda: record_usage(args.run, args.file),
        "usage": lambda: usage_summary(args.run),
        "catalogue": lambda: catalogue_summary(args.file),
        "catalogue-save": lambda: save_catalogue(args.file, args.expected_revision),
        "authoring-version": capture_authoring,
        "health": lambda: {"heartbeat": client().heartbeat(),
                           "collections": [c.name for c in client().list_collections()]},
    }
    return actions[args.command]()


if __name__ == "__main__":
    print(json.dumps(dispatch(parser().parse_args()), indent=2, ensure_ascii=False))

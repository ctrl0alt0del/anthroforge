"""Artifact and retrieval CLI for the AnthroForge reconstruction skill."""

import argparse
import json

from common import STAGES, read_json, reference
from contracts import validate_record, verify_artifacts
from knowledge import latest_records, reindex, remember
from runs import context, initialize
from service import client


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
    add_command(commands, "context", [("--stage", {"choices": STAGES, "required": True}),
        ("--query", {"required": True}), ("--run", {"required": True}), ("--inputs", {"nargs": "*", "default": []})])
    add_command(commands, "remember", [("--file", {"required": True})])
    add_command(commands, "validate", [("--file", {"required": True}),
        ("--kind", {"choices": ["lesson", "feedback", "handoff", "librarian_brief"], "required": True})])
    add_command(commands, "reference", [("--file", {"required": True})])
    add_command(commands, "reindex", [])
    add_command(commands, "health", [])
    return result


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
    return {"valid": True, "kind": kind, "artifact": reference(path),
            "scope": "Record structure and file versions; not anatomical certification"}


def dispatch(args):
    if args.command == "init-run":
        return {"run": str(initialize(args.name, args.source, args.target))}
    if args.command == "context":
        return context(args.run, args.stage, args.query, args.inputs)
    if args.command == "remember":
        return remember(args.file)
    if args.command == "validate":
        return validate(args.file, args.kind)
    if args.command == "reference":
        return reference(args.file)
    if args.command == "reindex":
        return reindex()
    return {"heartbeat": client().heartbeat(), "collections": [c.name for c in client().list_collections()]}


if __name__ == "__main__":
    print(json.dumps(dispatch(parser().parse_args()), indent=2, ensure_ascii=False))

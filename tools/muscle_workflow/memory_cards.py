"""Small curated instructions; immutable case records remain the evidence source."""

from functools import lru_cache
from pathlib import Path

from common import DEFAULT_ROOT, configure_embeddings, reference, root

INDEX_VERSION = 2
TOKEN_LIMIT = 240
FIELDS = ("when", "do", "check", "limits", "basis")


@lru_cache(maxsize=4)
def tokenizer(path):
    from tokenizers import Tokenizer
    result = Tokenizer.from_file(str(path))
    result.no_truncation()
    result.no_padding()
    return result


def encoder():
    suffix = "runtime/embeddings/all-MiniLM-L6-v2/onnx/tokenizer.json"
    path = root() / suffix
    if not path.exists() and (Path(DEFAULT_ROOT) / suffix).exists():
        path = Path(DEFAULT_ROOT) / suffix
    if not path.exists():
        configure_embeddings()
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
        ONNXMiniLM_L6_V2()(["Initialize the local lesson tokenizer."])
    return tokenizer(path)


def card_text(card):
    values = [f"{key}: {card[key]}" for key in FIELDS]
    return "\n".join(["features: " + " ".join(card["tags"]), *values])


def token_count(text):
    return len(encoder().encode(text).ids)


def validate_size(record):
    if "card" not in record:
        raise ValueError("New lesson revisions require a curated card; legacy records remain readable")
    count = token_count(card_text(record["card"]))
    if count > TOKEN_LIMIT:
        raise ValueError(f"Lesson card has {count} tokens; shorten to {TOKEN_LIMIT}, keeping scope")


def legacy_text(record):
    pieces = []
    for key in ("action", "applicability", "limitations", "title"):
        encoded = encoder().encode(record[key], add_special_tokens=False)
        end = encoded.offsets[min(44, len(encoded.offsets) - 1)][1]
        pieces.append(key + ": " + record[key][:end])
    return "\n".join(pieces)


def index_text(record):
    return card_text(record["card"]) if "card" in record else legacy_text(record)


def record_path(record):
    return root() / "knowledge/lessons" / record["id"] / f"r{record['revision']:06d}.json"


def compact(record):
    if "card" not in record:
        return dict(record, needs_curation=True)
    keys = ("id", "revision", "kind", "status", "title", "card", "retrieval_distance")
    result = {key: record[key] for key in keys if key in record}
    result["case_record"] = reference(record_path(record))
    return result


def stages_for(stage):
    return ("base", "fibers") if stage in ("base", "fibers") else (stage,)


def category_of(record):
    return record.get("card", {}).get("category", "modeling")


def select_diverse(matches, limit, features):
    ranked = sorted(matches, key=lambda r: (
        -len(set(features).intersection(r.get("card", {}).get("tags", []))),
        r["retrieval_distance"]))
    selected, topics = [], set()
    for record in ranked:
        topic = record.get("card", {}).get("topic", record["id"])
        if topic not in topics and len(selected) < limit:
            selected.append(record)
            topics.add(topic)
    return selected

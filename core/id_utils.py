import re


def next_prefixed_id(collection, prefix):
    """
    Return next available ID like PREFIX_1, PREFIX_2, ...
    based on numeric suffixes already present in collection items.
    """
    used = set()
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    for item in collection:
        raw = str(getattr(item, "id", "") or "")
        m = pattern.match(raw)
        if m:
            used.add(int(m.group(1)))

    n = 1
    while n in used:
        n += 1
    return f"{prefix}_{n}"

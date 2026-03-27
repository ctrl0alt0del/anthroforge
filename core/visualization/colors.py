# Muted palette (RGBA)
AF_MUTED_COLORS = [
    (0.2, 0.4, 0.8, 1.0),   # bright blue
    (0.2, 0.8, 0.4, 1.0),   # bright green
    (0.8, 0.4, 0.2, 1.0),   # bright orange
    (0.8, 0.2, 0.6, 1.0),   # bright magenta
    (0.8, 0.8, 0.2, 1.0),   # bright yellow
    (0.2, 0.8, 0.8, 1.0),   # bright cyan
]

_AF_COLOR_INDEX = 0


def color_for_index(index: int):
    i = int(index) if index is not None else 0
    return AF_MUTED_COLORS[i % len(AF_MUTED_COLORS)]


def next_color(index=None):
    if index is not None:
        return color_for_index(index)

    global _AF_COLOR_INDEX
    c = AF_MUTED_COLORS[_AF_COLOR_INDEX % len(AF_MUTED_COLORS)]
    _AF_COLOR_INDEX += 1
    return c

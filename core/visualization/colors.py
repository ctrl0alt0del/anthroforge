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


def next_color():
    global _AF_COLOR_INDEX
    c = AF_MUTED_COLORS[_AF_COLOR_INDEX % len(AF_MUTED_COLORS)]
    _AF_COLOR_INDEX += 1
    return c

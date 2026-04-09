import json
import sys


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    sample = {
        "deformers": {
            "parallelepiped_bend": {
                "params": {"enabled": True, "axis": "X", "angle_deg": 30.0, "radius": 1.25}
            },
            "ellipsoid_clip": {
                "params": {
                    "enabled": True,
                    "clip1_enabled": True,
                    "clip1_normal": [1.0, 0.0, 0.0],
                    "clip1_offset": 0.1,
                    "clip1_keep_side": "POS",
                }
            },
        }
    }
    txt = json.dumps(sample, separators=(",", ":"))
    back = json.loads(txt)
    _assert(isinstance(back, dict), "roundtrip must stay dict")
    _assert("deformers" in back and isinstance(back["deformers"], dict), "missing deformers map")
    _assert("parallelepiped_bend" in back["deformers"], "missing bend state")
    _assert("ellipsoid_clip" in back["deformers"], "missing clip state")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())


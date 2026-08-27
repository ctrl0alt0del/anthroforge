"""Analyze one opt-in span-SQP iteration trace and plot its blocking evidence."""

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--plot", required=True)
    parser.add_argument("--node", type=int, default=9)
    return parser.parse_args()


def _target_span(data, node):
    for span in data["trace"]["spans"]:
        if span["first_node"] <= node <= span["last_node"]: return span, node - span["first_node"]
    raise ValueError(f"node {node} is outside every SQP span")


def _unevenness(turns, index):
    neighbors = [turns[row] for row in range(max(1, index - 2), min(len(turns) - 1, index + 3)) if row != index]
    return float(turns[index] - np.median(neighbors)) if neighbors else float(turns[index])


def _near_contacts(row, index):
    return tuple(contact for contact in row["contacts"] if index - 1 <= contact["edge"] <= index)


def _state_row(row, index):
    gradient = row["gradient"]; energy = row["energy"]
    return {"proposal": row["proposal"], "accepted": row["accepted"], "stage": row["stage"],
        "turn": row["turn_degrees"][index], "unevenness": _unevenness(row["turn_degrees"], index),
        "step": row["step_norms"][index], "trust": row["trust_radius"],
        "length_energy": energy["length"], "curvature_energy": energy["curvature"],
        "structural_gradient": gradient["structural_norms"][index],
        "contact_gradient": gradient["contact_norms"][index], "total_gradient": gradient["total_norms"][index],
        "opposition": gradient["opposition_cosine"][index], "contacts": _near_contacts(row, index)}


def _accepted_rows(iterations, index):
    useful = [row for row in iterations if row["stage"] == "SEED" or
              (row["stage"] == "DECISION" and row["decision"] == "ACCEPT")]
    return tuple(_state_row(row, index) for row in useful)


def _proposal_row(rows, proposal, index):
    by_stage = {row["stage"]: row for row in rows}
    trial = by_stage.get("TRIAL"); proposed = by_stage.get("PROPOSE"); ccd = by_stage.get("CCD")
    decision = next((row["decision"] for row in rows if row["stage"] == "DECISION"), "")
    chosen = trial or ccd or proposed; sqp = {} if proposed is None else proposed.get("sqp", {})
    return {"proposal": proposal, "decision": decision, "turn": chosen["turn_degrees"][index],
        "unevenness": _unevenness(chosen["turn_degrees"], index), "step": chosen["step_norms"][index],
        "trust": chosen["trust_radius"], "model_ratio": None if trial is None else trial.get("model_ratio"),
        "ccd_step": None if ccd is None else ccd["ccd"]["safe_step"],
        "normal_step": sqp.get("normal_norm"), "tangential_step": sqp.get("tangential_norm"),
        "condition": sqp.get("condition"), "contacts": _near_contacts(chosen, index)}


def _proposal_rows(iterations, index):
    proposals = sorted({row["proposal"] for row in iterations if row["proposal"]})
    return tuple(_proposal_row([row for row in iterations if row["proposal"] == value], value, index)
                 for value in proposals)


def _accepted_before(iterations, proposal):
    rows = [row for row in iterations if row["proposal"] < proposal and row["stage"] == "DECISION" and
            row["decision"].startswith("ACCEPT")]
    return rows[-1] if rows else next(row for row in iterations if row["stage"] == "SEED")


def _limiter(rows, edge):
    decision = next(row for row in rows if row["stage"] == "DECISION")
    values = [row for row in decision["contacts"] if row["feature"] == "LIMITING" and row["edge"] == edge]
    return values[-1] if values else None


def _contact_motion(current, candidate, contact):
    edge, factor = contact["edge"], contact["factor"]; normal = np.asarray(contact["normal"])
    delta = np.asarray(candidate["points"]) - np.asarray(current["points"])
    movement = (1.0 - factor) * delta[edge] + factor * delta[edge + 1]
    normal_value = float(movement @ normal); tangent = movement - normal_value * normal
    return normal_value, float(np.linalg.norm(tangent)), tuple(map(float, movement))


def _blocker_row(iterations, rows, proposal, index):
    ccd = next(row for row in rows if row["stage"] == "CCD"); current = _accepted_before(iterations, proposal)
    pair = ccd["ccd"]["limiting_pairs"][0]; contact = _limiter(rows, pair[0])
    normal, tangent, movement = _contact_motion(current, ccd, contact)
    return {"proposal": proposal, "limiting_pair": pair, "safe_step": ccd["ccd"]["safe_step"],
        "current_turn": current["turn_degrees"][index], "candidate_turn": ccd["turn_degrees"][index],
        "turn_reduction": current["turn_degrees"][index] - ccd["turn_degrees"][index],
        "normal_motion": normal, "tangential_motion": tangent, "contact_motion": movement,
        "contact": contact, "trust": ccd["trust_radius"], "maximum_step": ccd["maximum_step"]}


def _blockers(iterations, index):
    proposals = sorted({row["proposal"] for row in iterations if row["proposal"]})
    output = []
    for proposal in proposals:
        rows = [row for row in iterations if row["proposal"] == proposal]
        decision = next((row["decision"] for row in rows if row["stage"] == "DECISION"), "")
        ccd = next((row for row in rows if row["stage"] == "CCD"), None)
        if decision == "REJECT:INJECT_LIMITING" and ccd and ccd["ccd"]["limiting_pairs"]:
            output.append(_blocker_row(iterations, rows, proposal, index))
    return tuple(output)


def _blocker_summary(blockers):
    smooth = [row for row in blockers if row["turn_reduction"] >= 3.0]
    steps = [row["safe_step"] for row in smooth]
    pairs = sorted({tuple(row["limiting_pair"]) for row in smooth})
    return {"smoothing_attempts_blocked": len(smooth), "limiting_pairs": pairs,
        "minimum_safe_step": min(steps, default=None), "median_safe_step": float(np.median(steps)) if steps else None,
        "inward_motion_count": sum(row["normal_motion"] < 0.0 for row in smooth)}


def _span_peak(span):
    final = next(row for row in reversed(span["iterations"]) if row["stage"] == "FINISH")
    indices = range(1, len(final["turn_degrees"]) - 1)
    local = max(indices, key=lambda index: _unevenness(final["turn_degrees"], index))
    return {"span": span["span"], "global_node": span["first_node"] + local,
        "turn": final["turn_degrees"][local], "unevenness": _unevenness(final["turn_degrees"], local),
        "termination": span["termination"]}


def _span_peaks(data):
    return tuple(_span_peak(span) for span in data["trace"]["spans"]
                 if span["last_node"] - span["first_node"] >= 2)


def _first_uneven(states):
    baseline = states[0]["unevenness"]; threshold = max(3.0, baseline + 3.0)
    return next((row for row in states[1:] if row["unevenness"] >= threshold), states[-1])


def _peak_uneven(states):
    return max(states, key=lambda row: row["unevenness"])


def _summary(data, span, local, states, proposals, blockers, node):
    first = _first_uneven(states); peak = _peak_uneven(states); final = states[-1]
    rejected = tuple(row for row in proposals if row["decision"].startswith("REJECT"))
    return {"file": data["file"], "fiber": data["fiber"], "global_node": node,
        "span": span["span"], "local_node": local, "termination": span["termination"],
        "accepted_steps": span["accepted_steps"], "rejected_steps": span["rejected_steps"],
        "final_peak_by_span": _span_peaks(data),
        "first_uneven": first, "peak_uneven": peak, "final": final,
        "blocker_summary": _blocker_summary(blockers), "blocking_contacts": blockers,
        "rejected_proposals": rejected, "states": states, "proposals": proposals}


def _series(rows, key):
    return [row["accepted"] for row in rows], [row[key] for row in rows]


def _plot_geometry(axis, states):
    x, turn = _series(states, "turn"); _x, uneven = _series(states, "unevenness")
    axis.plot(x, turn, "o-", label="turn angle"); axis.plot(x, uneven, "s-", label="local excess")
    axis.set_ylabel("degrees"); axis.legend(); axis.grid(alpha=.25)


def _plot_gradients(axis, states):
    x = [row["accepted"] for row in states]
    for key, label in (("structural_gradient", "structural"), ("contact_gradient", "contact"),
                       ("total_gradient", "total")): axis.semilogy(x, [row[key] for row in states], "o-", label=label)
    axis.set_ylabel("gradient norm"); axis.legend(); axis.grid(alpha=.25)


def _plot_energy(axis, states):
    x = [row["accepted"] for row in states]
    axis.plot(x, [row["length_energy"] for row in states], "o-", label="length")
    axis.plot(x, [row["curvature_energy"] for row in states], "o-", label="curvature")
    axis.set_ylabel("energy"); axis.legend(); axis.grid(alpha=.25)


def _plot_trials(axis, proposals):
    accepted = [row for row in proposals if row["decision"] == "ACCEPT"]
    rejected = [row for row in proposals if row["decision"] != "ACCEPT"]
    axis.scatter([row["proposal"] for row in accepted], [row["unevenness"] for row in accepted], label="accepted")
    axis.scatter([row["proposal"] for row in rejected], [row["unevenness"] for row in rejected], marker="x", label="rejected")
    axis.set_ylabel("trial local excess °"); axis.set_xlabel("SQP proposal"); axis.legend(); axis.grid(alpha=.25)


def _write_plot(path, states, proposals, node):
    figure, axes = plt.subplots(4, 1, figsize=(12, 12), sharex=False)
    _plot_geometry(axes[0], states); _plot_gradients(axes[1], states)
    _plot_energy(axes[2], states); _plot_trials(axes[3], proposals)
    axes[0].set_title(f"FIBER_2 span-SQP diagnostic — global node {node}")
    figure.tight_layout(); figure.savefig(path, dpi=180); plt.close(figure)


def main():
    args = _args(); data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    span, local = _target_span(data, args.node); iterations = span["iterations"]
    states = _accepted_rows(iterations, local); proposals = _proposal_rows(iterations, local)
    blockers = _blockers(iterations, local)
    result = _summary(data, span, local, states, proposals, blockers, args.node)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    _write_plot(args.plot, states, proposals, args.node)
    print(json.dumps({key: result[key] for key in ("termination", "first_uneven", "peak_uneven", "final")}))


if __name__ == "__main__":
    main()

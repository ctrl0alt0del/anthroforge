"""Production Bi-MDF orchestration; all field optimization stays native."""
import json
import re
from pathlib import Path
import numpy as np
from .quadwild_bundle import verify_bundle
from .quadwild_io import read_obj, write_obj, read_field, write_features
from .flow_native import solve, route, select_paths
from .process import execute
from .protocol import atomic_json


class UnsupportedPatchGraph(RuntimeError):
    pass


def progress(folder, stage, amount, message):
    destination = folder.parent if folder.name == "guided" else folder
    atomic_json(destination/"progress.json", [stage, amount, message])


def trace(folder, vendor, guided=False):
    (folder/"prep.txt").write_text("do_remesh 0\nsharp_feature_thr -1\nalpha 0.02\nscaleFact 1\n")
    args = [vendor/"quadwild.exe", folder/"mesh.obj", 2, folder/"prep.txt"]
    if guided: args.append(folder/"mesh.rosy")
    if (folder/"mesh.sharp").exists(): args.append(folder/"mesh.sharp")
    stats = execute(args, folder, "trace", cwd=vendor)
    if stats["exit_code"]: raise RuntimeError(f"QuadWild tracing failed: {stats['exit_code']}; see {folder/'trace.log'}")
    erased = re.findall(r"(\d+)- NON DISK OR NON MANIF PATCH ERASED", (folder/"trace.log").read_text())
    stats["discarded_patches"] = max(map(int, erased), default=0)
    return stats


def create_field(folder, guided, samples, paths, warnings, sparse=False):
    progress(folder, "Muscle FLOW", .55, "Building native muscle directions and feature paths.")
    v, f = read_obj(folder/"mesh_rem.obj", 3); prior = read_field(folder/"mesh_rem.rosy", len(f))
    directions, info = solve(v, f, prior, samples)
    write_obj(guided/"mesh.obj", v, f)
    np.savetxt(guided/"mesh.rosy", directions, header=f"{len(f)}\n4", comments="")
    edges = []; selected = select_paths(v, paths) if sparse else paths
    for points in selected:
        try: edges.extend(route(v, f, points))
        except ValueError as error: warnings.append(str(error))
    count = write_features(guided/"mesh.sharp", f, edges)
    return dict(constrained_faces=int((info[:, 0] > 0).sum()), feature_edges=count, requested_paths=len(paths), selected_paths=len(selected))


def quantize(folder, vendor, scale, index, warnings):
    progress(folder, "Bi-MDF", .65 + index*.02, f"Quantizing guided patches, density attempt {index+1}/4.")
    config = folder/f"quantize_{index}.txt"
    config.write_text((vendor/"config/main_config/flow.txt").read_text().replace("scaleFact 1", f"scaleFact {scale:.9g}"))
    output = folder/"mesh_rem_p0_1_quadrangulation_smooth.obj"
    if output.exists(): output.unlink()
    stats = execute([vendor/"quad_from_patches.exe", folder/"mesh_rem_p0.obj", 1, config], folder, f"quantize_{index}", cwd=vendor)
    check_exit(stats, folder/f"quantize_{index}.log")
    v, f = read_obj(output, 4)
    if stats["exit_code"]: warnings.append("QuadWild completed geometry but its Windows executable exited abnormally (2147483651). Output was validated; package issue remains.")
    return v, f, stats


def check_exit(stats, log):
    if stats["exit_code"] in (0, 2147483651): return
    text = log.read_text()
    if "valence not handled:" in text: raise UnsupportedPatchGraph("Bi-MDF cannot quantize the traced patch valence.")
    raise RuntimeError(f"QuadWild quantization failed: {stats['exit_code']}; see {log}")


def guided_result(folder, guided, samples, paths, vendor, target, warnings):
    field = create_field(folder, guided, samples, paths, warnings); tracing = trace(guided, vendor, True)
    try: v, f, attempts = calibrate(guided, vendor, target, warnings)
    except UnsupportedPatchGraph:
        (guided/"trace.log").replace(guided/"trace.initial.log")
        initial = tracing; field = create_field(folder, guided, samples, paths, warnings, True)
        tracing = trace(guided, vendor, True); tracing["initial"] = initial
        warnings.append(f"Bi-MDF rejected the initial patch graph. Retried with {field['selected_paths']}/{field['requested_paths']} separated hard paths; all muscle directions remain active.")
        v, f, attempts = calibrate(guided, vendor, target, warnings)
    if tracing["discarded_patches"]: warnings.append(f"QuadWild tracing discarded {tracing['discarded_patches']} invalid patches; inspect surface coverage and openings.")
    return v, f, attempts, field, tracing


def calibrate(folder, vendor, target, warnings):
    scale, best, records = 1., None, []
    for attempt in range(4):
        v, f, stats = quantize(folder, vendor, scale, attempt, warnings)
        error = abs(len(f)-target); records.append(dict(stats, scale=scale, quads=len(f)))
        if best is None or error < best[0]: best = error, v, f
        if error <= .15*target: break
        scale *= np.sqrt(len(f)/target)
    if best[0] > .15*target: warnings.append(f"QuadWild achieved {len(best[2])} quads for requested {target} in this solved domain; patch constraints limit density.")
    return best[1], best[2], records


def run(input_path, output_path, target):
    source = Path(input_path); folder = source.parent; vendor = verify_bundle(); warnings = []
    with np.load(source, allow_pickle=False) as d:
        write_obj(folder/"mesh.obj", d["vertices"], d["faces"])
        samples = d["flow_samples"].copy(); offsets = d["flow_offsets"]; points = d["flow_points"]
        paths = [points[a:b].copy() for a, b in zip(offsets[:-1], offsets[1:])]
    progress(folder, "Preparing field", .5, "Preparing the native surface field."); baseline = trace(folder, vendor); guided = folder/"guided"; guided.mkdir()
    v, f, attempts, field, tracing = guided_result(folder, guided, samples, paths, vendor, max(64, target), warnings)
    stats = dict(backend="QUADWILD", warnings=list(dict.fromkeys(warnings)), field=field,
                 automatic_trace=baseline, guided_trace=tracing, quantization=attempts)
    np.savez(output_path, vertices=v, faces=f, statistics=np.asarray(json.dumps(stats)))

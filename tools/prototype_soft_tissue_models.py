import argparse
import json
import sys
from pathlib import Path


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from core.vcp.soft_tissue_model import (  # noqa: E402
    AttachmentMode, AttachmentSpec, BaseDomain, BaseObjectSpec, BoundaryMode,
    InflationMode, InflationSpec, MaterialSpec, RelaxationSpec, SoftTissueVCPModel,
    SolverMode, SolverSpec, TargetKind, TargetSurface, TissuePreset, model_to_dict,
    validate_model,
)


def legacy_blob_model():
    return _model("ST_PROTO_BLOB", "Legacy Blob", TissuePreset.CLOSED_BULK, BaseDomain.POINT,
                  BoundaryMode.CLOSED, InflationMode.RADIAL, SolverMode.GEOMETRIC, "")


def abdominal_pad_model():
    row = _attachment("SCP_TORSO", "BOUNDARY", AttachmentMode.FIXED)
    return _model("ST_PROTO_PAD", "Abdominal Adipose Pad", TissuePreset.LAYER, BaseDomain.SURFACE,
                  BoundaryMode.HOST_SEALED, InflationMode.NORMAL, SolverMode.GEOMETRIC,
                  "prototype://torso/abdomen", (row,))


def breast_model():
    row = _attachment("SCP_THORAX", "BOUNDARY", AttachmentMode.FIXED)
    return _model("ST_PROTO_BREAST", "Breast", TissuePreset.POUCH, BaseDomain.SURFACE,
                  BoundaryMode.HOST_SEALED, InflationMode.NORMAL, SolverMode.STATIC_PBD,
                  "prototype://thorax/breast_root", (row,))


def lip_rim_model():
    rows = (_attachment("SCP_FACE", "BACKING", AttachmentMode.FIXED),
            _attachment("SCP_FACE", "ENDPOINTS", AttachmentMode.FIXED))
    return _model("ST_PROTO_LIP", "Lip Rim", TissuePreset.RIM, BaseDomain.CURVE,
                  BoundaryMode.HOST_SEALED, InflationMode.PROFILE, SolverMode.GEOMETRIC,
                  "prototype://mouth/arc", rows)


def prototype_models():
    return legacy_blob_model(), abdominal_pad_model(), breast_model(), lip_rim_model()


def _model(tissue_id, name, preset, domain, boundary, inflation, solver, reference, attachments=()):
    base = BaseObjectSpec(domain, reference, resolution=33 if domain == BaseDomain.CURVE else 24)
    amount = 0.012 if domain == BaseDomain.CURVE else 0.2
    field = "AF_ST_INFLATION" if domain == BaseDomain.SURFACE else ""
    infl = InflationSpec(inflation, amount, field_attribute=field)
    return SoftTissueVCPModel(tissue_id, name, preset, boundary, base, infl, MaterialSpec(),
                              RelaxationSpec(), tuple(attachments), SolverSpec(solver))


def _attachment(target_id, mask, mode):
    return AttachmentSpec(TargetKind.SCP, target_id, TargetSurface.SCP_GEOMETRY, mode, 1.0, mask)


def _arguments():
    parser = argparse.ArgumentParser(description="Emit production Soft Tissue VCP reference models.")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _payload(models):
    return {"schema": "anthroforge.soft_tissue_vcp", "version": 1,
            "models": [model_to_dict(model) for model in models]}


def main():
    args = _arguments()
    models = prototype_models()
    errors = {model.id: validate_model(model) for model in models if validate_model(model)}
    if errors:
        raise ValueError(errors)
    content = json.dumps(_payload(models), indent=2)
    args.output.write_text(content + "\n", encoding="utf-8") if args.output else print(content)


if __name__ == "__main__":
    main()

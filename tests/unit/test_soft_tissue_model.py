import json
import unittest
from dataclasses import replace

from core.vcp.soft_tissue_model import BaseDomain, InflationMode, construction_mode_for_domain, model_to_dict, validate_model
from tools.prototype_soft_tissue_models import prototype_models


class SoftTissueModelTests(unittest.TestCase):
    def test_all_prototype_models_are_valid(self):
        errors = {model.id: validate_model(model) for model in prototype_models()}
        self.assertEqual(errors, {model.id: () for model in prototype_models()})

    def test_prototypes_cover_every_base_domain(self):
        domains = {model.base.domain for model in prototype_models()}
        self.assertEqual(domains, set(BaseDomain))

    def test_domain_selects_one_canonical_construction(self):
        modes = {domain: construction_mode_for_domain(domain) for domain in BaseDomain}
        self.assertEqual(modes, {BaseDomain.POINT: InflationMode.RADIAL,
                         BaseDomain.CURVE: InflationMode.PROFILE, BaseDomain.SURFACE: InflationMode.NORMAL})

    def test_models_are_json_serializable(self):
        payload = [model_to_dict(model) for model in prototype_models()]
        self.assertEqual(len(json.loads(json.dumps(payload))), 4)

    def test_point_base_rejects_normal_inflation(self):
        model = prototype_models()[0]
        invalid = replace(model.inflation, mode=InflationMode.NORMAL)
        errors = validate_model(replace(model, inflation=invalid))
        self.assertIn("NORMAL is invalid for POINT", errors)

    def test_curve_requires_reference(self):
        model = prototype_models()[3]
        errors = validate_model(replace(model, base=replace(model.base, reference="")))
        self.assertIn("curve and surface bases require a reference", errors)


if __name__ == "__main__":
    unittest.main()

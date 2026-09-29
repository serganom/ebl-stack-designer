"""Headless regressions for composition and electron transport."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ebl_transport_under_test", ROOT / "ebl_stack_designer.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CompositionTests(unittest.TestCase):
    def test_every_preset_uses_one_composition(self):
        for material in m.preset_material_library():
            with self.subTest(material=material["name"]):
                elements = material["elements"]
                mass_sum = math.fsum(e["atomic_fraction"] * m._estimate_atomic_weight(e["symbol"], e["Z"]) for e in elements)
                self.assertAlmostEqual(math.fsum(e["weight_fraction"] for e in elements), 1.0)
                self.assertAlmostEqual(math.fsum(e["atomic_fraction"] for e in elements), 1.0)
                for element in elements:
                    implied_mass = element["atomic_fraction"] * m._estimate_atomic_weight(element["symbol"], element["Z"]) / mass_sum
                    self.assertAlmostEqual(implied_mass, element["weight_fraction"], places=13)

    def test_ma_n_mass_recipe_is_preserved(self):
        material = next(x for x in m.preset_material_library() if x["name"] == "ma-N 2400 (approx.)")
        self.assertEqual([e["weight_fraction"] for e in material["elements"]], [0.65, 0.1, 0.24, 0.01])
        nitrogen = next(e for e in material["elements"] if e["symbol"] == "N")
        self.assertLess(nitrogen["atomic_fraction"], 0.005)

    def test_legacy_atomic_fractions_cannot_change_transport_properties(self):
        material = next(x for x in m.preset_material_library() if x["name"] == "ma-N 2400 (approx.)")
        legacy = copy.deepcopy(material)
        for element in legacy["elements"]:
            element["atomic_fraction"] = 1.0
        self.assertEqual(m._material_mc_properties(material), m._material_mc_properties(legacy))
        self.assertTrue(all(e["atomic_fraction"] == 1.0 for e in legacy["elements"]))

    def test_element_identity_and_mass_fractions_are_validated(self):
        material = {"elements": [{"symbol": "si", "Z": 14, "weight_fraction": 2.0}]}
        self.assertEqual(m._canonical_material_elements(material), [{"symbol": "Si", "Z": 14, "weight_fraction": 1.0, "atomic_fraction": 1.0}])
        invalid_elements = [
            {"symbol": "Si", "Z": 6, "weight_fraction": 1.0},
            {"symbol": "Unknown", "Z": 6, "weight_fraction": 1.0},
            {"symbol": "C", "Z": 6, "weight_fraction": -1.0},
            {"symbol": "C", "Z": 6, "weight_fraction": float("nan")},
            {"symbol": "C", "Z": 6, "weight_fraction": float("inf")},
            {"symbol": "C", "Z": 6, "weight_fraction": 0.0},
        ]
        for element in invalid_elements:
            with self.subTest(element=element), self.assertRaises(ValueError):
                m._canonical_material_elements({"elements": [element]})
        with self.assertRaises(ValueError):
            m._canonical_material_elements({"elements": []})
        with self.assertRaises(ValueError):
            m._canonical_material_elements({"elements": [
                {"symbol": "C", "Z": 6, "weight_fraction": 1e308},
                {"symbol": "H", "Z": 1, "weight_fraction": 1e308},
            ]})

class DummyRoot:
    def update_idletasks(self):
        pass


class FixedRng:
    def __init__(self, seed):
        pass

    def random(self):
        return 0.5

    def gauss(self, mean, sigma):
        return mean


class OpticalDepthOneRng(FixedRng):
    def random(self):
        return 1.0 - math.exp(-1.0)


def make_app(stack, energy=50.0):
    app = m.StackDesignerApp.__new__(m.StackDesignerApp)
    app.materials = [
        m._mat("carbon", "", 2.26, [("C", 6, 1.0, 1.0)]),
        m._mat("gold", "", 19.32, [("Au", 79, 1.0, 1.0)]),
    ]
    app.project = {"beam": {"energy_keV": energy, "beam_diameter_nm": 0.0}, "stack": copy.deepcopy(stack)}
    app.root = DummyRoot()
    app._set_sim_progress_text = lambda *args, **kwargs: None
    return app


def simulation_params(**changes):
    params = {
        "seed": 12345,
        "resist_layer_index": 0,
        "electrons": 1,
        "max_radius_nm": 1000,
        "min_energy_keV": 0.05,
        "max_collisions_per_electron": 4000,
    }
    params.update(changes)
    return params


class TransportTests(unittest.TestCase):
    def test_boundary_consumes_optical_depth_in_each_material(self):
        stack = [
            {"material_name": "carbon", "thickness_nm": 100.0, "role": "resist"},
            {"material_name": "gold", "thickness_nm": 1000.0, "role": "metal"},
        ]
        with patch.object(m.random, "Random", OpticalDepthOneRng), \
             patch.object(m, "_elastic_mean_free_path_nm", side_effect=lambda E, P: 1000.0 if P["zeff_af"] == 6 else 10.0) as mean_free_path, \
             patch.object(m, "_bethe_stopping_keV_per_nm", return_value=1e-6), \
             patch.object(m, "_screened_rutherford_theta", return_value=0.0):
            result = make_app(stack)._simulate_standalone_radial_distribution(simulation_params(max_collisions_per_electron=1))
        diag = result["transport_diagnostics"]
        self.assertEqual([call.args[1]["zeff_af"] for call in mean_free_path.call_args_list], [6.0, 79.0])
        self.assertAlmostEqual(diag["max_depth_nm"], 100.0 + (1.0 - 100.0 / 1000.0) * 10.0, places=10)
        self.assertEqual(diag["termination_counts"]["max_collisions"], 1)
        self.assertAlmostEqual(diag["energy_balance_error_keV"], 0.0, places=12)

    def test_changing_role_does_not_change_transport(self):
        reference = None
        for role in ["resist", "dielectric", "metal", "substrate"]:
            stack = [{"material_name": "carbon", "thickness_nm": 1000.0, "role": role}]
            result = make_app(stack, energy=2.0)._simulate_standalone_radial_distribution(simulation_params(electrons=8))
            if reference is None:
                reference = result
            else:
                self.assertTrue(m.np.array_equal(reference["evals"], result["evals"]))
                self.assertEqual(reference["transport_diagnostics"], result["transport_diagnostics"])

    def test_selecting_different_tally_layer_preserves_global_transport(self):
        stack = [
            {"material_name": "carbon", "thickness_nm": 100.0, "role": "resist"},
            {"material_name": "gold", "thickness_nm": 100.0, "role": "resist"},
            {"material_name": "carbon", "thickness_nm": 1000.0, "role": "substrate"},
        ]
        observations = []
        for selected in [0, 1]:
            with patch.object(m.random, "Random", FixedRng), \
                 patch.object(m, "_elastic_mean_free_path_nm", return_value=10.0), \
                 patch.object(m, "_bethe_stopping_keV_per_nm", return_value=0.01), \
                 patch.object(m, "_screened_rutherford_theta", return_value=0.0) as scattering:
                result = make_app(stack, energy=5.0)._simulate_standalone_radial_distribution(simulation_params(resist_layer_index=selected))
            observations.append((result["transport_diagnostics"], [call.args[:2] for call in scattering.call_args_list]))
        self.assertEqual(observations[0][1], observations[1][1])
        for field in ["deposited_energy_all_materials_keV", "escaped_energy_keV", "residual_energy_at_cutoff_keV", "termination_counts", "max_depth_nm"]:
            self.assertEqual(observations[0][0][field], observations[1][0][field])

    def test_cutoff_shortens_segment_and_prevents_a_spurious_collision(self):
        stack = [{"material_name": "carbon", "thickness_nm": 1000.0, "role": "resist"}]
        with patch.object(m.random, "Random", FixedRng), \
             patch.object(m, "_elastic_mean_free_path_nm", return_value=1000.0), \
             patch.object(m, "_bethe_stopping_keV_per_nm", return_value=0.1), \
             patch.object(m, "_screened_rutherford_theta", return_value=0.0) as scattering:
            result = make_app(stack, energy=1.0)._simulate_standalone_radial_distribution(simulation_params(min_energy_keV=0.2))
        diag = result["transport_diagnostics"]
        self.assertAlmostEqual(diag["max_depth_nm"], 8.0)
        self.assertAlmostEqual(diag["deposited_energy_all_materials_keV"], 0.8)
        self.assertAlmostEqual(diag["residual_energy_at_cutoff_keV"], 0.2)
        self.assertEqual(diag["termination_counts"]["energy_cutoff"], 1)
        self.assertEqual(result["collision_count_in_resist"], 0)
        scattering.assert_not_called()

    def test_thick_substrate_remains_finite(self):
        stack = [{"material_name": "carbon", "thickness_nm": 60000.0, "role": "substrate"}]
        with patch.object(m.random, "Random", FixedRng), \
             patch.object(m, "_elastic_mean_free_path_nm", return_value=1e6), \
             patch.object(m, "_bethe_stopping_keV_per_nm", return_value=1e-8):
            result = make_app(stack)._simulate_standalone_radial_distribution(simulation_params())
        diag = result["transport_diagnostics"]
        self.assertAlmostEqual(diag["max_depth_nm"], 60000.0)
        self.assertEqual(diag["termination_counts"]["escaped_bottom"], 1)
        self.assertAlmostEqual(diag["escaped_energy_keV"], 50.0 - 60000.0 * 1e-8)
        self.assertAlmostEqual(diag["energy_balance_error_keV"], 0.0)

    def test_backscattered_electron_can_escape_the_surface(self):
        stack = [{"material_name": "carbon", "thickness_nm": 1000.0, "role": "resist"}]
        with patch.object(m.random, "Random", FixedRng), \
             patch.object(m, "_elastic_mean_free_path_nm", return_value=10.0), \
             patch.object(m, "_bethe_stopping_keV_per_nm", return_value=0.001), \
             patch.object(m, "_screened_rutherford_theta", return_value=math.pi):
            result = make_app(stack)._simulate_standalone_radial_distribution(simulation_params())
        diag = result["transport_diagnostics"]
        self.assertEqual(diag["termination_counts"]["escaped_top"], 1)
        self.assertGreater(diag["escaped_energy_keV"], 0.0)
        self.assertAlmostEqual(diag["energy_balance_error_keV"], 0.0)

    def test_radial_truncation_is_reported_in_energy_accounting(self):
        stack = [{"material_name": "carbon", "thickness_nm": 1e6, "role": "resist"}]
        with patch.object(m.random, "Random", FixedRng), \
             patch.object(m, "_elastic_mean_free_path_nm", return_value=10000.0), \
             patch.object(m, "_bethe_stopping_keV_per_nm", return_value=1e-6), \
             patch.object(m, "_screened_rutherford_theta", return_value=math.pi / 2):
            result = make_app(stack)._simulate_standalone_radial_distribution(simulation_params())
        diag = result["transport_diagnostics"]
        self.assertEqual(diag["termination_counts"]["radial_limit"], 1)
        self.assertGreater(diag["residual_energy_radial_limit_keV"], 0.0)
        self.assertGreater(diag["deposited_energy_selected_outside_radius_keV"], 0.0)
        self.assertAlmostEqual(diag["deposited_energy_selected_in_radius_keV"], float(result["evals"].sum()))
        self.assertAlmostEqual(diag["energy_balance_error_keV"], 0.0)

    def test_energy_is_conserved_with_unmocked_transport(self):
        stack = [
            {"material_name": "carbon", "thickness_nm": 300.0, "role": "resist"},
            {"material_name": "gold", "thickness_nm": 3000.0, "role": "substrate"},
        ]
        result = make_app(stack, energy=5.0)._simulate_standalone_radial_distribution(simulation_params(electrons=20, max_radius_nm=2000))
        diag = result["transport_diagnostics"]
        self.assertEqual(sum(diag["termination_counts"].values()), 20)
        self.assertAlmostEqual(diag["incident_energy_keV"], 100.0)
        accounted = sum(diag[k] for k in ["deposited_energy_all_materials_keV", "escaped_energy_keV", "residual_energy_at_cutoff_keV", "residual_energy_max_collisions_keV", "residual_energy_radial_limit_keV"])
        self.assertAlmostEqual(accounted, 100.0, places=9)
        self.assertAlmostEqual(diag["deposited_energy_selected_in_radius_keV"], float(result["evals"].sum()), places=10)
        self.assertLessEqual(diag["deposited_energy_selected_resist_keV"], diag["deposited_energy_all_materials_keV"])

    def test_invalid_execution_inputs_are_rejected(self):
        stack = [{"material_name": "carbon", "thickness_nm": 1000.0, "role": "resist"}]
        for value in [0.0, -1.0, float("nan"), float("inf")]:
            with self.subTest(beam_energy=value), self.assertRaises(ValueError):
                make_app(stack, energy=value)._simulate_standalone_radial_distribution(simulation_params())
            bad_stack = copy.deepcopy(stack)
            bad_stack[0]["thickness_nm"] = value
            with self.subTest(thickness=value), self.assertRaises(ValueError):
                make_app(bad_stack)._simulate_standalone_radial_distribution(simulation_params())
        for value in [0.0, -1.0, 50.0, 51.0, float("nan"), float("inf")]:
            with self.subTest(energy_cutoff=value), self.assertRaises(ValueError):
                make_app(stack)._simulate_standalone_radial_distribution(simulation_params(min_energy_keV=value))
        for field in ["electrons", "max_collisions_per_electron"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                make_app(stack)._simulate_standalone_radial_distribution(simulation_params(**{field: 0}))


    def test_integer_settings_and_tally_uniqueness_are_enforced(self):
        stack = [{"material_name": "carbon", "thickness_nm": 1000.0, "role": "resist"}]
        for field in ["electrons", "max_collisions_per_electron", "seed", "max_radius_nm", "resist_layer_index"]:
            for value in [1.5, float("nan"), float("inf"), True]:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    make_app(stack)._simulate_standalone_radial_distribution(simulation_params(**{field: value}))
        for indices in [[0, 0], [0.5], [float("nan")], [float("inf")], [True], "0"]:
            with self.subTest(indices=indices), self.assertRaises(ValueError):
                make_app(stack)._simulate_standalone_radial_distribution(simulation_params(resist_layer_indices=indices))


if __name__ == "__main__":
    unittest.main()

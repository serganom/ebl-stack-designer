"""Headless regressions for project provenance, load transactions and validation."""
import copy
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ebl_state_under_test", ROOT / "ebl_stack_designer.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Var:
    def __init__(self, value=""):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


def project(name="A"):
    materials = m.preset_material_library()[:2]
    return {
        "schema_version": m.PROJECT_SCHEMA_VERSION,
        "project_name": name,
        "beam": {"energy_keV": 50.0, "beam_diameter_nm": 10.0, "current_pA": None},
        "materials": materials,
        "stack": [{"material_name": materials[0]["name"], "thickness_nm": 100.0, "role": "resist"}],
        "pec_fits": [],
    }


def new_app():
    app = m.StackDesignerApp.__new__(m.StackDesignerApp)
    app.project = project()
    app.project_path = None
    app.materials = app.project["materials"]
    app.last_fit_result = None
    for name in ("project_name", "energy", "diam", "current", "current_unit", "fit_info", "workflow_hint"):
        setattr(app, name + "_var", Var())
    app.root = SimpleNamespace(wait_window=lambda _: None)
    app.refresh_materials = lambda: None
    app.refresh_stack = lambda: None
    app.refresh_all()
    return app


def fit(width=10.0):
    np = m._ensure_numpy()
    r = np.arange(1, 101, dtype=float)
    area = m._radial_ring_area_nm2(r)
    density = np.exp(-(r / width) ** 2)
    density /= np.sum(density * area)
    return {
        "fit_model": "double_gaussian", "alpha_nm": width, "beta_nm": 3000.0,
        "eta_fit": 1.0, "eta_split": 1.0, "layer_pattern": "resist", "input_file": "test",
        "beam_energy_keV": 50.0, "resist_thickness_nm": 100.0,
        "psf_diagnostics": {"psf_integral": 1.0},
        "fit_representation": {
            "version": 1, "model": "double_gaussian", "normalization": "full_plane_area_integral_one",
            "eta_semantics": "global_component_integral_ratio", "alpha_nm": width,
            "beta_nm": 3000.0, "eta": 1.0, "amplitude": 1.0,
        },
        "plot_data": {"r_nm": r.tolist(), "fitted_density": density.tolist(), "measured_density": density.tolist()},
    }


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ebl_state_test_")
        self.addCleanup(self.temp.cleanup)
        contexts = ExitStack()
        self.addCleanup(contexts.close)
        self.errors = contexts.enter_context(patch.object(m.messagebox, "showerror"))
        contexts.enter_context(patch.object(m.messagebox, "showinfo"))
        contexts.enter_context(patch.object(m.messagebox, "showwarning"))

    def load_data(self, app, data):
        path = Path(self.temp.name) / "project.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(m.filedialog, "askopenfilename", return_value=str(path)):
            app.load_project()

    def test_switching_projects_exports_loaded_result_not_old_cache(self):
        app = new_app()
        app._store_fit_result(fit(10))
        other = new_app()
        other.project["project_name"] = "B"
        other._store_fit_result(fit(20))
        self.load_data(app, other.project)
        self.errors.assert_not_called()
        self.assertEqual(app.last_fit_result["alpha_nm"], 20)
        path = Path(self.temp.name) / "loaded.psf"
        expected_path = Path(self.temp.name) / "expected.psf"
        app._write_psf_two_column(str(expected_path), other.last_fit_result)
        with patch.object(m.filedialog, "asksaveasfilename", return_value=str(path)):
            app.export_psf_curve()
        self.errors.assert_not_called()
        self.assertEqual(path.read_bytes(), expected_path.read_bytes())
        self.load_data(app, project("empty history"))
        self.assertIsNone(app.last_fit_result)

    def test_snapshots_and_history_are_detached_and_export_provenance_is_stable(self):
        app = new_app()
        original = fit()
        current = app._store_fit_result(original)
        recorded = app.project["pec_fits"][-1]
        before = app._export_metadata(current)
        original["plot_data"]["fitted_density"][0] = 123.0
        self.assertNotEqual(current["plot_data"]["fitted_density"][0], 123.0)
        current["plot_data"]["fitted_density"][0] *= 1.1
        self.assertNotEqual(current["plot_data"]["fitted_density"][0], recorded["plot_data"]["fitted_density"][0])
        app.project["stack"][0]["thickness_nm"] = 200.0
        app.materials[0]["density_g_cm3"] = 9.99
        after = app._export_metadata(current)
        self.assertEqual(before["stack_hash"], after["stack_hash"])
        self.assertEqual(before["material_library_hash"], after["material_library_hash"])
        self.assertEqual(current["input_snapshot"]["stack"][0]["thickness_nm"], 100.0)
        self.assertEqual(recorded["input_snapshot"]["materials"][0]["density_g_cm3"], 1.19)
        # Direct low-level historical export must retain its recorded geometry.
        path = Path(self.temp.name) / "historical.lpsf"
        app._write_lpsf_archive(str(path), recorded)
        xml = ET.fromstring(zlib.decompress(path.read_bytes()))
        self.assertEqual(float(xml.find(".//m_Stack/item/second").text), 100.0)

    def test_changed_or_invalid_inputs_block_export_before_file_selection(self):
        for change in ("thickness", "density", "energy", "invalid_energy"):
            with self.subTest(change=change):
                app = new_app()
                app._store_fit_result(fit())
                if change == "thickness":
                    app.project["stack"][0]["thickness_nm"] = 200
                elif change == "density":
                    app.materials[0]["density_g_cm3"] = 2.0
                else:
                    app.energy_var.set("nan" if change == "invalid_energy" else "100")
                with patch.object(m.filedialog, "asksaveasfilename") as choose:
                    app.export_psf_curve()
                choose.assert_not_called()
                self.assertIn(app._fit_state(app.last_fit_result), ("stale", "invalid_inputs"))

    def test_legacy_results_remain_inspectable_but_cannot_claim_current_inputs(self):
        app = new_app()
        data = project()
        data["pec_fits"] = [fit()]
        data["pec_fits"][0].pop("fit_representation")
        self.load_data(app, data)
        self.errors.assert_not_called()
        self.assertEqual(app.last_fit_result["alpha_nm"], 10)
        self.assertEqual(app._fit_state(app.last_fit_result), "legacy_missing_snapshot")
        with self.assertRaisesRegex(ValueError, "snapshot"):
            app._require_exportable_fit(app.last_fit_result)
        meta = app._export_metadata(app.last_fit_result)
        self.assertIsNone(meta["stack_hash"])
        self.assertIsNone(meta["material_library_hash"])

    def test_material_edit_preserves_pending_beam_and_title(self):
        app = new_app()
        app.energy_var.set("100")
        app.diam_var.set("25")
        app.project_name_var.set("Edited title")
        app.selected_material_index = lambda: 0
        replacement = copy.deepcopy(app.materials[0])
        replacement["density_g_cm3"] = 1.3
        with patch.object(m, "MaterialDialog", return_value=SimpleNamespace(result=replacement)):
            app.edit_material()
        self.assertEqual(app.energy_var.get(), "100")
        self.assertEqual(app.diam_var.get(), "25")
        self.assertEqual(app.project_name_var.get(), "Edited title")
        self.assertEqual(app.materials[0]["density_g_cm3"], 1.3)

    def test_preset_stack_preserves_pending_beam_and_title(self):
        app = new_app()
        app.energy_var.set("100")
        app.diam_var.set("25")
        app.project_name_var.set("Edited title")
        app._single_select_dialog = lambda **_: 0
        with patch.object(m.messagebox, "askyesno", return_value=False):
            app.add_preset_stack()
        self.assertEqual(app.energy_var.get(), "100")
        self.assertEqual(app.diam_var.get(), "25")
        self.assertEqual(app.project_name_var.get(), "Edited title")

    def test_duplicate_names_are_rejected_for_add_and_rename(self):
        app = new_app()
        before = copy.deepcopy(app.materials)
        duplicate = copy.deepcopy(app.materials[0])
        duplicate["density_g_cm3"] = 9.99
        with patch.object(m, "MaterialDialog", return_value=SimpleNamespace(result=duplicate)):
            app.add_material()
            app.selected_material_index = lambda: 1
            app.edit_material()
        self.assertEqual(app.materials, before)
        self.assertEqual(self.errors.call_count, 2)

    def test_invalid_json_does_not_replace_project_or_pending_fields(self):
        app = new_app()
        app._store_fit_result(fit())
        original = app.project
        original_fit = app.last_fit_result
        app.energy_var.set("100")
        for mutation in (
            lambda p: p["stack"][0].update(thickness_nm="not-a-number"),
            lambda p: p["stack"][0].update(material_name="missing"),
            lambda p: p.update(materials={}),
            lambda p: p.update(pec_fits=[{"alpha_nm": "bad"}]),
            lambda p: p.update(schema_version=99),
        ):
            bad = copy.deepcopy(original)
            mutation(bad)
            self.load_data(app, bad)
            self.assertIs(app.project, original)
            self.assertIs(app.last_fit_result, original_fit)
            self.assertEqual(app.energy_var.get(), "100")

    def test_refresh_error_rolls_back_loaded_state(self):
        app = new_app()
        app._store_fit_result(fit())
        old = app.project
        app.energy_var.set("100")
        with patch.object(app, "refresh_all", side_effect=[RuntimeError("UI failure"), None]):
            self.load_data(app, project("B"))
        self.assertIs(app.project, old)
        self.assertEqual(app.energy_var.get(), "100")
        self.assertEqual(app.last_fit_result["alpha_nm"], 10)

    def test_invalid_physical_values_are_rejected_without_mutation(self):
        app = new_app()
        invalid_materials = []
        for density in (float("nan"), float("inf"), 0, -1):
            bad = copy.deepcopy(app.materials[0])
            bad["density_g_cm3"] = density
            invalid_materials.append(bad)
        for key, value in (("weight_fraction", -.2), ("atomic_fraction", -.2), ("weight_fraction", float("nan")), ("Z", 0), ("Z", 6.5)):
            bad = copy.deepcopy(app.materials[0])
            bad["elements"][0][key] = value
            invalid_materials.append(bad)
        for bad in invalid_materials:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m._validated_material(bad)
        for field, value in (("energy_var", "nan"), ("energy_var", "inf"), ("diam_var", "-10"), ("current_var", "-5")):
            app = new_app()
            original = copy.deepcopy(app.project)
            getattr(app, field).set(value)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                app.collect_project()
            self.assertEqual(app.project, original)

    def test_mass_fraction_canonicalization_keeps_ui_and_loaded_project_consistent(self):
        app = new_app()
        data = project()
        for element in data["materials"][0]["elements"]:
            element["atomic_fraction"] = .9
        checked, warnings = app._migrate_project_data(data)
        self.assertTrue(any("Atomic fractions were recalculated" in warning for warning in warnings))
        self.assertEqual(
            [e["weight_fraction"] for e in data["materials"][0]["elements"]],
            [e["weight_fraction"] for e in checked["materials"][0]["elements"]],
        )
        self.load_data(app, data)
        self.errors.assert_not_called()
        material = app.materials[0]
        canonical = m._canonical_material_elements(material)
        self.assertEqual(material["elements"], canonical)
        app._store_fit_result(fit())
        app.collect_project()
        self.assertEqual(app._fit_state(app.last_fit_result), "current")
        self.load_data(app, app.project)
        self.assertEqual(app._fit_state(app.last_fit_result), "current")


if __name__ == "__main__":
    unittest.main()

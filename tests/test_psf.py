"""Numerical regression tests for radius conventions and physical PSF fitting."""
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ebl_psf_test", ROOT / "ebl_stack_designer.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
np = m._ensure_numpy()


def gaussian(r, width):
    # Analytic reference density with unit integral over the two-dimensional plane.
    return np.exp(-(r / width) ** 2) / (math.pi * width ** 2)


def gaussian_ring_density(r, area, width):
    inner2 = np.maximum(r ** 2 - area / math.pi, 0.)
    return (np.exp(-inner2 / width ** 2) - np.exp(-r ** 2 / width ** 2)) / area


class PSFTests(unittest.TestCase):
    def setUp(self):
        self.app = m.StackDesignerApp.__new__(m.StackDesignerApp)

    def test_ring_assignment_and_energy_split_include_center(self):
        self.assertEqual([m._radial_bin_index(r) for r in (0, .49, .51, .999, 1, 1.51, 2)], [0, 0, 0, 0, 1, 1, 2])
        forward, back = m._radial_energy_split([1, 2, 3], [.8, .1, .1], 2)
        self.assertAlmostEqual(back / forward, 1.0 / 9.0)
        partial, rest = m._radial_energy_split([1, 2], [math.pi, 3 * math.pi], 1.5)
        self.assertAlmostEqual(partial, math.pi * 1.5 ** 2)
        self.assertAlmostEqual(partial + rest, 4 * math.pi)

    def test_global_models_integrate_to_one(self):
        radius = np.concatenate(([0.0], np.geomspace(1e-5, 1e7, 60000)))
        for model in (
            {"version": 1, "model": "double_gaussian", "alpha_nm": 8., "beta_nm": 1000., "eta": .5},
            {"version": 1, "model": "power_gaussian", "core_radius_nm": 2., "alpha_power": 3., "beta_nm": 1000., "eta": .5},
        ):
            density = m._evaluate_psf_model(model, radius)
            integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
            integral = integrate(2 * math.pi * radius * density, radius)
            self.assertAlmostEqual(float(integral), 1., delta=2e-6)
        with self.assertRaisesRegex(ValueError, "p > 2"):
            m._power_psf(np.array([0., 1.]), 2., 1.)

    def test_double_gaussian_recovers_exact_target_across_windows(self):
        # This exact candidate used to be lost by the subsequent refined grid.
        alpha, beta, eta = 11.415921324112361, 657.707002341345, .25714977682821805
        for last in (1200., 4000.):
            radius = np.geomspace(3., last, 250)
            area = m._radial_ring_area_nm2(radius)
            density = (gaussian_ring_density(radius, area, alpha) + eta * gaussian_ring_density(radius, area, beta)) / (1 + eta)
            fit = self.app._fit_double_gaussian_grid(radius, np.log10(density), area, beam_energy_keV=5.)
            self.assertLess(fit["mse"], 1e-18)
            for key, expected in (("alpha_nm", alpha), ("beta_nm", beta), ("eta_fit", eta)):
                self.assertAlmostEqual(fit[key], expected, delta=1e-10)
            np.testing.assert_allclose(m._evaluate_psf_ring_average(fit["fit_representation"], radius, area), density, rtol=1e-9)

    def test_power_gaussian_keeps_exact_candidate_and_core(self):
        radius = np.geomspace(3., 3000., 250)
        area = m._radial_ring_area_nm2(radius)
        inner2 = np.maximum(radius ** 2 - area / math.pi, 0.)
        power = ((1 + inner2) ** -.5 - (1 + radius ** 2) ** -.5) / area
        density = (power + .02 * gaussian_ring_density(radius, area, 280.)) / 1.02
        fit = self.app._fit_power_gaussian_grid(radius, np.log10(density), area, beam_energy_keV=5.)
        self.assertLess(fit["mse"], 1e-18)
        self.assertAlmostEqual(fit["alpha_power"], 3.)
        self.assertAlmostEqual(fit["eta_fit"], .02)
        np.testing.assert_allclose(m._evaluate_psf_ring_average(fit["fit_representation"], radius, area), density, rtol=1e-9)

    def test_beamer_fit_grid_invariance_and_reported_error(self):
        radius = np.arange(3., 3001.)
        area = math.pi * (radius ** 2 - (radius - 1.) ** 2)
        density = (gaussian_ring_density(radius, area, 8.) + .5 * gaussian_ring_density(radius, area, 1000.) + .2 * gaussian_ring_density(radius, area, 100.)) / 1.7
        y = np.log10(density)
        fit = self.app._fit_beamer_gaussian_grid(radius, y, area, double_gaussian_seed={"alpha_nm": 8., "beta_nm": 1000., "eta_fit": .5})
        full = self.app._beamer_gaussian_density(radius, area, fit, target_y_log10_density=y)
        subset = np.unique(np.round(np.geomspace(1, radius.size - 1, 650)).astype(int))
        sparse = self.app._beamer_gaussian_density(radius[subset], area[subset], fit, target_y_log10_density=y[subset])
        np.testing.assert_allclose(full[subset], sparse, rtol=1e-14)
        self.assertAlmostEqual(fit["mse"], float(np.mean((np.log10(full) - y) ** 2)), places=14)
        self.assertLess(fit["mse"], .002)
        for key, value in (("alpha_nm", 8.), ("beta_nm", 1000.), ("gamma1_nm", 100.), ("eta_fit", .5), ("nue1", .2)):
            self.assertLess(abs(fit[key] / value - 1), .18, key)

    def test_narrow_gaussian_recovery_from_exact_ring_energy(self):
        # One-nm histogram rings; the first two are excluded just as in the GUI.
        outer = np.arange(1., 4001.)
        inner = outer - 1.
        area = math.pi * (outer ** 2 - inner ** 2)
        for alpha in (2., 5., 10.):
            energy = (np.exp(-(inner / alpha) ** 2) - np.exp(-(outer / alpha) ** 2)
                      + .5 * (np.exp(-(inner / 1000.) ** 2) - np.exp(-(outer / 1000.) ** 2))) / 1.5
            energy /= energy.sum()
            window = self.app._prepare_fit_window(outer, energy, area, energy / area, resist_thickness_nm=100.)
            fit = self.app._fit_double_gaussian_grid(window["x_nm"], window["y_log10_density"], window["ring_area"], fit_weights=window["weights"], beam_energy_keV=5., resist_thickness_nm=100.)
            self.assertLess(abs(fit["alpha_nm"] / alpha - 1.), .06, alpha)
            self.assertLess(abs(fit["eta_fit"] / .5 - 1.), .12, alpha)
            self.assertLess(abs(fit["beta_nm"] / 1000. - 1.), .08, alpha)

    def test_ring_average_matches_energy_and_point_limit(self):
        outer = np.array([1., 2., 3., 10., 1000.])
        area = m._radial_ring_area_nm2(outer)
        averaged = m._gaussian_ring_psf(outer, area, 2.)
        self.assertAlmostEqual(float(np.sum(averaged * area)), 1., places=14)
        # Narrow rings at a fixed radius converge to the point density.
        radius = np.array([3.])
        narrow_area = np.array([math.pi * (3. ** 2 - (3. - 1e-7) ** 2)])
        self.assertAlmostEqual(float(m._gaussian_ring_psf(radius, narrow_area, 2.)[0] / gaussian(radius, 2.)[0]), 1., delta=1e-6)
        model = {"version": 1, "model": "power_gaussian", "alpha_power": 3., "core_radius_nm": 1., "beta_nm": 100., "eta": .5}
        point = m._evaluate_psf_model(model, radius)
        average = m._evaluate_psf_ring_average(model, radius, narrow_area)
        np.testing.assert_allclose(average, point, rtol=1e-6)

    def test_numerical_export_preserves_center_and_controls_tail(self):
        model = {"version": 1, "model": "double_gaussian", "alpha_nm": 2., "beta_nm": 200., "eta": .1, "amplitude": 7.}
        result = {"fit_representation": model, "fit_window_max_nm": 100., "plot_data": {"r_nm": list(range(3, 103)), "fitted_density": [1.] * 100}}
        radius, density, metadata = self.app._export_curve_data(result)
        self.assertEqual(radius[0], 0.)
        expected_center = (1 / (math.pi * 4) + .1 / (math.pi * 200 ** 2)) / 1.1
        self.assertAlmostEqual(density[0], expected_center)
        self.assertLess(metadata["omitted_tail_fraction"], m.PSF_EXPORT_TAIL_TOLERANCE)
        self.assertGreater(radius[-1], 100.)
        self.assertGreater(density[-1], 0.)
        points, meta = self.app._build_lpsf_curve_points(result)
        self.assertEqual(points[0][0], 0.)
        self.assertGreater(points[-1][1], 0.)
        self.assertAlmostEqual(points[0][1] / meta["scale"], expected_center)
        with tempfile.TemporaryDirectory() as directory:
            self.app._write_psf_two_column(str(Path(directory) / "test.psf"), result)
            data = np.loadtxt(Path(directory) / "test.psf")
            self.assertEqual(data[0, 0], 0.)
            self.assertAlmostEqual(data[0, 1] / 1e6, expected_center)

    def test_unbounded_legacy_or_excessive_power_tail_is_not_silently_exported(self):
        with self.assertRaisesRegex(ValueError, "Rerun"):
            self.app._export_curve_data({"plot_data": {"r_nm": [3., 4.], "fitted_density": [1., .5]}})
        result = {"fit_representation": {"version": 1, "model": "power_gaussian", "core_radius_nm": 1., "alpha_power": 2.01, "beta_nm": 1000., "eta": .1}}
        with self.assertRaisesRegex(ValueError, "too broad"):
            self.app._export_curve_data(result)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import pathlib
import math
import tempfile
import zlib
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "ebl_stack_designer.py"


def load_app_module():
    spec = importlib.util.spec_from_file_location("ebl_stack_designer", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_close(value, expected, tol, label):
    if abs(float(value) - float(expected)) > tol:
        raise AssertionError(f"{label}: got {value}, expected {expected} +/- {tol}")


def main():
    m = load_app_module()
    np = m._ensure_numpy()

    assert_close(m.nm_to_um(1000.0), 1.0, 1e-12, "nm_to_um")
    assert_close(m.um_to_nm(1.0), 1000.0, 1e-12, "um_to_nm")
    assert_close(m.kev_to_ev(50.0), 50000.0, 1e-12, "kev_to_ev")
    assert_close(m.ev_to_kev(50000.0), 50.0, 1e-12, "ev_to_kev")

    r = np.arange(1, 4000, dtype=float)
    area = m._radial_ring_area_nm2(r)
    gaussian = np.exp(-(r / 8.0) ** 2)
    gaussian /= max(float(np.sum(gaussian * area)), 1e-300)
    assert_close(m._density_integral(gaussian, area), 1.0, 1e-10, "Gaussian PSF integral")

    app = m.StackDesignerApp.__new__(m.StackDesignerApp)
    app.materials = m.preset_material_library()
    app.project = {
        "beam": {"energy_keV": 50.0, "beam_diameter_nm": 10.0},
        "materials": app.materials,
        "stack": [
            {"material_name": "PMMA 950k (generic)", "thickness_nm": 90.0, "role": "resist"},
            {"material_name": "PMMA 495k (generic)", "thickness_nm": 150.0, "role": "resist"},
            {"material_name": "Silicon (Si)", "thickness_nm": 4400.0, "role": "substrate"},
        ],
    }

    legacy, warnings = app._migrate_project_data({
        "project_name": "legacy",
        "beam": {"energy_keV": 50.0},
        "materials": app.materials,
        "stack": app.project["stack"],
    })
    if legacy["schema_version"] != m.PROJECT_SCHEMA_VERSION or not warnings:
        raise AssertionError("Legacy JSON migration failed.")

    inner = r - 1.0
    # Exact annular energies from globally normalized components; eta = 0.9.
    evals = (
        np.exp(-(inner / 7.0) ** 2) - np.exp(-(r / 7.0) ** 2)
        + 0.9 * (np.exp(-(inner / 3200.0) ** 2) - np.exp(-(r / 3200.0) ** 2))
    ) / 1.9
    evals /= float(np.sum(evals))
    if not np.all(np.isfinite(evals)) or np.any(evals < 0):
        raise AssertionError("Synthetic histogram is invalid.")

    res = app._fit_alpha_beta_eta_from_histogram(
        r,
        evals,
        100.0,
        source_label="smoke",
        layer_label="PMMA 950k + PMMA 495k",
        collision_count=123,
        beam_energy_keV=50.0,
        resist_thickness_nm=240.0,
        resist_material_name="PMMA bilayer",
        beam_sigma_nm=4.25,
    )
    if res["fit_model"] != "double_gaussian":
        raise AssertionError("Known double-Gaussian histogram selected the wrong family.")
    for key, expected in (("alpha_nm", 7.0), ("beta_nm", 3200.0), ("eta_fit", 0.9)):
        if abs(res[key] / expected - 1.0) > 0.15:
            raise AssertionError(f"Synthetic parameter recovery failed for {key}: {res[key]}")
    if res["fit_mse"] > 0.01:
        raise AssertionError("Synthetic PSF fit has excessive log-density error.")
    res["beamer_fwhm_um"] = 0.03
    res["simulation"] = {
        "engine": "smoke",
        "electrons": 3000,
        "seed": 12345,
        "min_energy_keV": 0.05,
        "beam_energy_keV": 50.0,
        "resist_layer_indices": [0, 1],
    }
    res["beam"] = app.project["beam"]
    res["stack_snapshot"] = app.project["stack"]

    diag = res.get("psf_diagnostics") or {}
    assert_close(diag.get("psf_integral"), 1.0, 5e-3, "Normalized PSF integral")
    if res.get("warnings"):
        raise AssertionError("Unexpected fit warnings: " + "; ".join(res["warnings"]))

    outdir = pathlib.Path(tempfile.mkdtemp(prefix="ebl_stack_designer_smoke_"))
    psf_path = outdir / "curve.psf"
    csv_path = outdir / "curve.csv"
    lpsf_path = outdir / "curve.lpsf"
    app._write_psf_two_column(str(psf_path), res)
    app._write_psf_csv(str(csv_path), res)
    app._write_lpsf_archive(str(lpsf_path), res)

    app._validate_psf_two_column_file(str(psf_path))
    app._validate_psf_csv_file(str(csv_path))
    app._validate_lpsf_file(str(lpsf_path))
    exported = np.loadtxt(psf_path)
    radius_nm = exported[:, 0] * 1000.0
    density_nm2 = exported[:, 1] / 1e6
    if radius_nm[0] != 0.0 or density_nm2[0] <= density_nm2[np.searchsorted(radius_nm, 3.0)]:
        raise AssertionError("Full numerical PSF export lost its central profile.")
    integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    integral = float(integrate(2.0 * math.pi * radius_nm * density_nm2, radius_nm))
    assert_close(integral, 1.0, 0.002, "Exported full PSF integral")
    xml_text = zlib.decompress(lpsf_path.read_bytes()).decode("utf-8")
    root = ET.fromstring(xml_text)
    points = int(root.find(".//m_PSFDataOriginal/count").text)
    if points < 100:
        raise AssertionError("LPSF export has too few points.")

    print("smoke ok")
    print(f"fit_model={res['fit_model']} beta_nm={float(res['beta_nm']):.3f} eta={float(res['eta_fit']):.6f}")
    print(f"exports={outdir}")


if __name__ == "__main__":
    main()

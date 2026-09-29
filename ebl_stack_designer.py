import json
import copy
import os
import tempfile
import hashlib
import math
import time
import random
import sys
import zlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
np = None
plt = None

PROGRAM_NAME = "EBL Stack Designer"
PROGRAM_VERSION = "0.5.0"
PROGRAM_CREATOR = "Sergei Nomoev"
PROJECT_SCHEMA_VERSION = 3
INTERNAL_LENGTH_UNIT = "nm"
BEAMER_LENGTH_UNIT = "um"
GAUSSIAN_CONVENTION = "G(r,w)=exp(-r^2/w^2)/(pi*w^2), normalized on the full radial plane"
LEGACY_GAUSSIAN_CONVENTION = "legacy: components normalized over the sampled fit window"
PSF_REPRESENTATION_VERSION = 1
PSF_EXPORT_TAIL_TOLERANCE = 1.0e-4
PSF_EXPORT_MAX_RADIUS_NM = 1.0e8
GAUSSIAN_FWHM_FACTOR = 2.0 * math.sqrt(math.log(2.0))


def nm_to_um(value):
    return float(value) * 1.0e-3


def um_to_nm(value):
    return float(value) * 1.0e3


def nm_to_cm(value):
    return float(value) * 1.0e-7


def kev_to_ev(value):
    return float(value) * 1.0e3


def ev_to_kev(value):
    return float(value) * 1.0e-3


def _dependency_install_command():
    return f'"{sys.executable}" -m pip install numpy matplotlib'


def _ensure_numpy():
    global np
    if np is None:
        try:
            import numpy as _np
            np = _np
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "NumPy is not installed for the Python interpreter running this app.\n\n"
                f"Current Python:\n{sys.executable}\n\n"
                "Install the dependencies with:\n"
                f"{_dependency_install_command()}"
            ) from exc
    return np


def _ensure_matplotlib_pyplot():
    global plt
    if plt is None:
        try:
            import matplotlib.pyplot as _plt
            plt = _plt
        except ModuleNotFoundError:
            plt = False
        except Exception:
            plt = False
    return None if plt is False else plt


def safe_float(text, default=None):
    text = (text or "").strip()
    if text == "":
        return default
    return float(text)


def _transport_diagnostic_warnings(diagnostics):
    """Surface lost trajectories instead of hiding them in PSF normalization."""
    if not diagnostics:
        return []
    warnings = []
    counts = diagnostics.get("termination_counts", {})
    for key, description in (("max_collisions", "collision limit"), ("radial_limit", "radial limit")):
        count = int(counts.get(key, 0))
        if count:
            warnings.append(f"{count} electron trajectories were stopped at the {description}; check convergence before using this PSF.")
    outside = float(diagnostics.get("deposited_energy_selected_outside_radius_keV", 0.0))
    selected = float(diagnostics.get("deposited_energy_selected_resist_keV", 0.0))
    # A reporting threshold only; it does not alter transport or PSF values.
    if selected > 0.0 and outside / selected > 0.001:
        warnings.append(f"{100.0 * outside / selected:.3g}% of selected-resist deposition is outside the histogram; increase its radius.")
    incident = float(diagnostics.get("incident_energy_keV", 0.0))
    error = float(diagnostics.get("energy_balance_error_keV", 0.0))
    if not math.isfinite(error) or abs(error) > 1e-8 * max(1.0, incident):
        warnings.append("Transport energy accounting does not balance; do not use this result until resolved.")
    return warnings


def _finite_input(value, label, *, minimum=0.0, positive=False, optional=False):
    if optional and (value is None or value == ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number.")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number) or number < minimum or (positive and number <= minimum):
        relation = ">" if positive else ">="
        raise ValueError(f"{label} must be finite and {relation} {minimum:g}.")
    return number


def _validated_material(material):
    if not isinstance(material, dict):
        raise ValueError("Each material must be an object.")
    result = copy.deepcopy(material)
    name = result.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Material name is required.")
    result["name"] = name.strip()
    result["density_g_cm3"] = _finite_input(result.get("density_g_cm3"), "Density", positive=True)
    for key in ("alias", "notes"):
        if not isinstance(result.get(key, ""), str):
            raise ValueError(f"Material {key} must be text.")
        result.setdefault(key, "")
    # Atomic fractions are derived from the canonical mass composition. Reject
    # invalid provided values, but do not require independently rounded fractions
    # to agree with one another before canonicalization.
    elements = result.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("At least one element is required.")
    for element in elements:
        if not isinstance(element, dict):
            raise ValueError("Each element must be an object.")
        if not isinstance(element.get("symbol"), str):
            raise ValueError("Element symbol must be text.")
        _finite_input(element.get("Z"), "Atomic number", positive=True)
        _finite_input(element.get("weight_fraction"), "Mass fraction")
        if "atomic_fraction" in element:
            _finite_input(element["atomic_fraction"], "Atomic fraction")
    result["elements"] = _canonical_material_elements(result)
    return result


def _validated_inputs(data):
    """Validate and detach all simulation inputs before committing them to UI state."""
    if not isinstance(data, dict):
        raise ValueError("Project inputs must be an object.")
    materials = data.get("materials")
    stack = data.get("stack")
    beam = data.get("beam")
    if not isinstance(materials, list) or not isinstance(stack, list) or not isinstance(beam, dict):
        raise ValueError("Project needs materials and stack lists and a beam object.")
    materials = [_validated_material(mat) for mat in materials]
    names = [mat["name"] for mat in materials]
    if len(names) != len(set(names)):
        raise ValueError("Material names must be unique.")
    checked_stack = []
    for i, layer in enumerate(stack):
        if not isinstance(layer, dict):
            raise ValueError(f"Layer {i + 1} must be an object.")
        entry = copy.deepcopy(layer)
        if entry.get("material_name") not in names:
            raise ValueError(f"Layer {i + 1} references an unknown material.")
        entry["thickness_nm"] = _finite_input(entry.get("thickness_nm"), f"Layer {i + 1} thickness", positive=True)
        role = entry.get("role", "other")
        if not isinstance(role, str):
            raise ValueError(f"Layer {i + 1} role must be text.")
        entry["role"] = role.strip() or "other"
        checked_stack.append(entry)
    checked_beam = copy.deepcopy(beam)
    checked_beam["energy_keV"] = _finite_input(beam.get("energy_keV"), "Beam energy", positive=True)
    checked_beam["beam_diameter_nm"] = _finite_input(beam.get("beam_diameter_nm"), "Beam diameter", optional=True)
    checked_beam["current_pA"] = _finite_input(beam.get("current_pA"), "Beam current", optional=True)
    unit = beam.get("current_input_unit", "pA")
    if unit not in ("pA", "nA"):
        raise ValueError("Current unit must be pA or nA.")
    checked_beam["current_input_unit"] = unit
    return {"beam": checked_beam, "materials": materials, "stack": checked_stack}


def _norm(vals):
    s = float(sum(vals))
    if s <= 0:
        return list(vals)
    return [float(v) / s for v in vals]


def _stable_json_hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _radial_ring_area_nm2(r_nm):
    _ensure_numpy()
    r = np.asarray(r_nm, dtype=float)
    if r.ndim != 1:
        raise ValueError("Radius array must be one-dimensional.")
    if r.size == 0:
        return np.asarray([], dtype=float)
    edges_inner = np.concatenate(([0.0], r[:-1]))
    area = math.pi * (r ** 2 - edges_inner ** 2)
    return np.where(np.isfinite(area) & (area > 0.0), area, 0.0)


def _radial_bin_index(radius_nm, bin_width_nm=1.0):
    # Bin i represents [i*dr, (i+1)*dr), with the stored radius its outer edge.
    return int(math.floor(float(radius_nm) / float(bin_width_nm)))


def _radial_energy_split(r_outer_nm, energy, cutoff_nm):
    """Split all energy, including the center, using area fractions at a cut ring."""
    _ensure_numpy()
    r = np.asarray(r_outer_nm, dtype=float)
    e = np.asarray(energy, dtype=float)
    inner = np.concatenate(([0.0], r[:-1]))
    fraction = np.clip((float(cutoff_nm) ** 2 - inner ** 2)
                       / np.maximum(r ** 2 - inner ** 2, 1e-300), 0.0, 1.0)
    if cutoff_nm <= 0:
        fraction[:] = 0.0
    forward = float(np.sum(e * fraction))
    return forward, float(np.sum(e * (1.0 - fraction)))


def _gaussian_psf(r_nm, width_nm):
    _ensure_numpy()
    width = float(width_nm)
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Gaussian width must be finite and positive.")
    r = np.asarray(r_nm, dtype=float)
    return np.exp(-(r / width) ** 2) / (math.pi * width * width)


def _power_psf(r_nm, exponent, core_radius_nm):
    _ensure_numpy()
    power, core = float(exponent), float(core_radius_nm)
    if not math.isfinite(power) or power <= 2.0:
        raise ValueError("A full-plane power PSF requires exponent p > 2.")
    if not math.isfinite(core) or core <= 0:
        raise ValueError("Power PSF core radius must be finite and positive.")
    r = np.asarray(r_nm, dtype=float)
    return (power - 2.0) / (2.0 * math.pi * core * core) * (1.0 + (r / core) ** 2) ** (-power / 2.0)


def _ring_inner_radius_squared(r_outer_nm, ring_area_nm2):
    _ensure_numpy()
    outer = np.asarray(r_outer_nm, dtype=float)
    area = np.asarray(ring_area_nm2, dtype=float)
    if (outer.shape != area.shape or np.any(~np.isfinite(outer)) or np.any(outer <= 0.0)
            or np.any(~np.isfinite(area)) or np.any(area <= 0.0)):
        raise ValueError("PSF ring areas must be positive, finite and match the radii.")
    inner2 = outer ** 2 - area / math.pi
    if np.any(inner2 < -1e-9 * np.maximum(1.0, outer ** 2)):
        raise ValueError("PSF ring area exceeds its outer circle.")
    return np.maximum(inner2, 0.0), area


def _gaussian_ring_psf(r_outer_nm, ring_area_nm2, width_nm):
    """Exact annular area average of a globally normalized Gaussian."""
    inner2, area = _ring_inner_radius_squared(r_outer_nm, ring_area_nm2)
    width = float(width_nm)
    if not math.isfinite(width) or width <= 0.0:
        raise ValueError("Gaussian width must be finite and positive.")
    width2 = width * width
    # expm1 preserves narrow-ring energy differences for a broad component.
    return np.exp(-inner2 / width2) * (-np.expm1(-area / (math.pi * width2))) / area


def _power_ring_psf(r_outer_nm, ring_area_nm2, exponent, core_radius_nm):
    """Exact annular average from differences of the analytic power tail mass."""
    inner2, area = _ring_inner_radius_squared(r_outer_nm, ring_area_nm2)
    power, core = float(exponent), float(core_radius_nm)
    if not math.isfinite(power) or power <= 2.0:
        raise ValueError("A full-plane power PSF requires exponent p > 2.")
    if not math.isfinite(core) or core <= 0.0:
        raise ValueError("Power PSF core radius must be finite and positive.")
    core2 = core * core
    exponent_tail = 1.0 - power / 2.0
    log_inner_tail = exponent_tail * np.log1p(inner2 / core2)
    log_tail_ratio = exponent_tail * np.log1p(area / (math.pi * (core2 + inner2)))
    return np.exp(log_inner_tail) * (-np.expm1(log_tail_ratio)) / area


def _evaluate_psf_ring_average(model, r_outer_nm, ring_area_nm2, include_amplitude=True):
    """Predict histogram-bin averages; numerical exports use the point evaluator."""
    if model.get("version") != PSF_REPRESENTATION_VERSION:
        raise ValueError("Unsupported or missing PSF model representation; rerun the fit.")
    eta = float(model["eta"])
    if not math.isfinite(eta) or eta < 0.0:
        raise ValueError("PSF eta must be finite and non-negative.")
    if model["model"] == "power_gaussian":
        forward = _power_ring_psf(r_outer_nm, ring_area_nm2, model["alpha_power"], model["core_radius_nm"])
    else:
        forward = _gaussian_ring_psf(r_outer_nm, ring_area_nm2, model["alpha_nm"])
    numerator = forward + eta * _gaussian_ring_psf(r_outer_nm, ring_area_nm2, model["beta_nm"])
    denominator = 1.0 + eta
    for index in (1, 2):
        weight = float(model.get(f"nue{index}", 0.0))
        if weight > 0.0:
            numerator += weight * _gaussian_ring_psf(r_outer_nm, ring_area_nm2, model[f"gamma{index}_nm"])
            denominator += weight
    amplitude = float(model.get("amplitude", 1.0)) if include_amplitude else 1.0
    return amplitude * numerator / denominator


def _evaluate_psf_model(model, r_nm, include_amplitude=True):
    """Evaluate a versioned, globally normalized model independently of sampling."""
    _ensure_numpy()
    if model.get("version") != PSF_REPRESENTATION_VERSION:
        raise ValueError("Unsupported or missing PSF model representation; rerun the fit.")
    r = np.asarray(r_nm, dtype=float)
    if np.any(~np.isfinite(r)) or np.any(r < 0):
        raise ValueError("PSF radii must be finite and non-negative.")
    eta = float(model["eta"])
    if not math.isfinite(eta) or eta < 0:
        raise ValueError("PSF eta must be finite and non-negative.")
    if model["model"] == "power_gaussian":
        forward = _power_psf(r, model["alpha_power"], model["core_radius_nm"])
    else:
        forward = _gaussian_psf(r, model["alpha_nm"])
    numerator = forward + eta * _gaussian_psf(r, model["beta_nm"])
    denominator = 1.0 + eta
    for index in (1, 2):
        weight = float(model.get(f"nue{index}", 0.0))
        if weight > 0.0:
            numerator = numerator + weight * _gaussian_psf(r, model[f"gamma{index}_nm"])
            denominator += weight
    amplitude = float(model.get("amplitude", 1.0)) if include_amplitude else 1.0
    return amplitude * numerator / denominator


def _psf_model_tail_fraction(model, radius_nm):
    """Exact remaining normalized mass outside a radius, before fit amplitude."""
    r = float(radius_nm)
    eta = float(model["eta"])
    if model["model"] == "power_gaussian":
        p = float(model["alpha_power"])
        if p <= 2.0:
            raise ValueError("A full-plane power PSF requires exponent p > 2.")
        forward = (1.0 + (r / float(model["core_radius_nm"])) ** 2) ** (1.0 - p / 2.0)
    else:
        forward = math.exp(-(r / float(model["alpha_nm"])) ** 2)
    numerator = forward + eta * math.exp(-(r / float(model["beta_nm"])) ** 2)
    denominator = 1.0 + eta
    for index in (1, 2):
        weight = float(model.get(f"nue{index}", 0.0))
        if weight > 0.0:
            numerator += weight * math.exp(-(r / float(model[f"gamma{index}_nm"])) ** 2)
            denominator += weight
    return numerator / denominator


def _fit_representation(result, amplitude=1.0, core_radius_nm=None):
    model = {
        "version": PSF_REPRESENTATION_VERSION,
        "model": result.get("fit_model", "beamer_gaussian"),
        "normalization": "full_plane_area_integral_one",
        "eta_semantics": "global_component_integral_ratio",
        "beta_nm": float(result["beta_nm"]),
        "eta": float(result["eta_fit"]),
        "amplitude": float(amplitude),
    }
    if model["model"] == "power_gaussian":
        model.update(alpha_power=float(result["alpha_power"]), core_radius_nm=float(core_radius_nm))
    else:
        model["alpha_nm"] = float(result["alpha_nm"])
    for key in ("gamma1_nm", "gamma2_nm", "nue1", "nue2"):
        if key in result:
            model[key] = float(result[key])
    return model


def _density_integral(density, ring_area):
    _ensure_numpy()
    y = np.asarray(density, dtype=float)
    area = np.asarray(ring_area, dtype=float)
    if y.size == 0 or y.size != area.size:
        return float("nan")
    mask = np.isfinite(y) & np.isfinite(area) & (y >= 0.0) & (area > 0.0)
    return float(np.sum(y[mask] * area[mask]))


def _cumulative_from_density(density, ring_area):
    _ensure_numpy()
    y = np.asarray(density, dtype=float)
    area = np.asarray(ring_area, dtype=float)
    if y.size == 0 or y.size != area.size:
        return np.asarray([], dtype=float)
    contrib = np.where(np.isfinite(y) & np.isfinite(area) & (y > 0.0) & (area > 0.0), y * area, 0.0)
    return np.cumsum(contrib)


def _canonical_material_elements(material):
    """Derive one consistent composition from the supplied mass fractions."""
    elements = material.get("elements", [])
    if not elements:
        raise ValueError("Material must contain at least one element.")
    normalized = []
    for element in elements:
        symbol = str(element.get("symbol", "")).strip().capitalize()
        expected_z = ATOMIC_NUMBERS.get(symbol)
        if expected_z is None:
            raise ValueError(f"Unknown element symbol: {symbol!r}.")
        z = float(element.get("Z", 0))
        if not math.isfinite(z) or z != expected_z:
            raise ValueError(f"Atomic number for {symbol} must be {expected_z}.")
        weight = float(element.get("weight_fraction", 0.0))
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError(f"Mass fraction for {symbol} must be finite and nonnegative.")
        normalized.append({
            "symbol": symbol,
            "Z": expected_z,
            "weight_fraction": weight,
        })
    try:
        weight_sum = math.fsum(element["weight_fraction"] for element in normalized)
    except OverflowError as exc:
        raise ValueError("Material mass fractions must have a finite positive sum.") from exc
    if not math.isfinite(weight_sum) or weight_sum <= 0.0:
        raise ValueError("Material mass fractions must have a finite positive sum.")
    atom_amounts = []
    for element in normalized:
        element["weight_fraction"] /= weight_sum
        atomic_weight = _estimate_atomic_weight(element["symbol"], element["Z"])
        atom_amounts.append(element["weight_fraction"] / atomic_weight)
    atom_sum = math.fsum(atom_amounts)
    for element, atom_amount in zip(normalized, atom_amounts):
        element["atomic_fraction"] = atom_amount / atom_sum
    return normalized


def _mat(name, alias, density, elements, notes=""):
    # Legacy preset tuples include atomic fractions; mass fractions are canonical.
    out_elems = _canonical_material_elements({"elements": [
        {"symbol": e[0], "Z": e[1], "weight_fraction": e[2]} for e in elements
    ]})
    return {
        "name": name,
        "alias": alias,
        "density_g_cm3": float(density),
        "notes": notes,
        "elements": out_elems,
    }


def preset_material_library():
    # Proprietary resist chemistries are approximate film compositions for Monte Carlo use.
    mats = []
    mats.append(_mat(
        "PMMA 950k (generic)", "PMMA 950k; PMMA",
        1.19,
        [("C", 6, 0.600, 0.333), ("H", 1, 0.080, 0.533), ("O", 8, 0.320, 0.134)],
        "Generic PMMA 950k approximation for EBL Monte Carlo."
    ))
    mats.append(_mat(
        "PMMA 495k (generic)", "PMMA 495k",
        1.19,
        [("C", 6, 0.600, 0.333), ("H", 1, 0.080, 0.533), ("O", 8, 0.320, 0.134)],
        "Generic PMMA 495k approximation (same chemistry class; molecular weight differs)."
    ))
    mats.append(_mat(
        "PMMA 450k (generic)", "PMMA 450k",
        1.19,
        [("C", 6, 0.600, 0.333), ("H", 1, 0.080, 0.533), ("O", 8, 0.320, 0.134)],
        "Generic PMMA 450k approximation (same chemistry class; molecular weight differs)."
    ))
    mats.append(_mat(
        "MMA/MAA copolymer (generic)", "MMA/MAA; PMMA copolymer; MMA",
        1.05,
        [("C", 6, 0.575, 0.330), ("H", 1, 0.082, 0.540), ("O", 8, 0.343, 0.130)],
        "Generic MMA/MAA copolymer approximation for bilayer EBL processes."
    ))
    mats.append(_mat(
        "ZEP520A (approx.)", "ZEP520A; ZEP-520A",
        1.20,
        [("C", 6, 0.52, 0.29), ("H", 1, 0.07, 0.46), ("O", 8, 0.12, 0.08), ("Cl", 17, 0.29, 0.17)],
        "Approximate chlorinated polymer composition; vendor formulation proprietary."
    ))
    mats.append(_mat(
        "ZEP530A (approx.)", "ZEP530A; ZEP-530A",
        1.20,
        [("C", 6, 0.52, 0.29), ("H", 1, 0.07, 0.46), ("O", 8, 0.12, 0.08), ("Cl", 17, 0.29, 0.17)],
        "Approximate chlorinated polymer composition; vendor formulation proprietary."
    ))
    mats.append(_mat(
        "CSAR 62 (AR-P 6200, approx.)", "CSAR 62; AR-P 6200",
        1.20,
        [("C", 6, 0.50, 0.28), ("H", 1, 0.06, 0.43), ("O", 8, 0.16, 0.10), ("Cl", 17, 0.28, 0.19)],
        "Approximate chlorinated acrylate resist film composition."
    ))
    mats.append(_mat(
        "HSQ (generic)", "HSQ; XR-1541; FOx; FOx-12; FOx-16",
        1.30,
        [("H", 1, 0.03, 0.20), ("Si", 14, 0.39, 0.20), ("O", 8, 0.58, 0.60)],
        "Generic HSQ approximation (pre/post exposure chemistry differs)."
    ))
    mats.append(_mat(
        "ma-N 2400 (approx.)", "ma-N 2400",
        1.10,
        [("C", 6, 0.65, 0.3846), ("H", 1, 0.10, 0.4615), ("O", 8, 0.24, 0.0769), ("N", 7, 0.01, 0.0769)],
        "Approximate negative novolak-based resist composition for Monte Carlo."
    ))
    mats.append(_mat(
        "mr-EBL 6000 (approx.)", "mr-EBL 6000",
        1.15,
        [("C", 6, 0.62, 0.36), ("H", 1, 0.08, 0.48), ("O", 8, 0.24, 0.10), ("N", 7, 0.06, 0.06)],
        "Approximate high-sensitivity negative resist composition; proprietary."
    ))

    mats.append(_mat(
        "Silicon (Si)", "Si",
        2.33,
        [("Si", 14, 1.0, 1.0)],
        "Bulk silicon substrate."
    ))
    mats.append(_mat(
        "Silicon Dioxide (SiO2)", "SiO2; oxide; silicon oxide",
        2.20,
        [("Si", 14, 0.4674, 1/3), ("O", 8, 0.5326, 2/3)],
        "Generic SiO2 (thermal/PECVD values may differ)."
    ))
    mats.append(_mat(
        "Silicon Nitride (Si3N4)", "Si3N4; silicon nitride",
        3.44,
        [("Si", 14, 0.6006, 3/7), ("N", 7, 0.3994, 4/7)],
        "Stoichiometric Si3N4."
    ))
    mats.append(_mat(
        "Quartz (SiO2, crystalline)", "Quartz; fused silica",
        2.65,
        [("Si", 14, 0.4674, 1/3), ("O", 8, 0.5326, 2/3)],
        "Quartz / fused silica modeled as SiO2 with quartz-like density."
    ))
    mats.append(_mat(
        "GaAs", "GaAs",
        5.32,
        [("Ga", 31, 0.482, 0.5), ("As", 33, 0.518, 0.5)],
        "Stoichiometric GaAs substrate."
    ))
    mats.append(_mat(
        "InP", "InP",
        4.81,
        [("In", 49, 0.788, 0.5), ("P", 15, 0.212, 0.5)],
        "Stoichiometric InP substrate."
    ))
    mats.append(_mat(
        "Sapphire (Al2O3)", "Sapphire; Al2O3",
        3.98,
        [("Al", 13, 0.5293, 2/5), ("O", 8, 0.4707, 3/5)],
        "Sapphire modeled as crystalline Al2O3."
    ))
    mats.append(_mat(
        "Aluminum Oxide (Al2O3, ALD approx.)", "Al2O3; alumina; aluminum oxide; ALD Al2O3",
        3.00,
        [("Al", 13, 0.5293, 2/5), ("O", 8, 0.4707, 3/5)],
        "Amorphous/ALD Al2O3 thin-film approximation."
    ))
    mats.append(_mat(
        "Graphene / Carbon (C)", "Graphene; C; carbon; graphite",
        2.26,
        [("C", 6, 1.0, 1.0)],
        "Graphene or ultrathin carbon layer approximation."
    ))
    mats.append(_mat(
        "Chromium (Cr)", "Cr",
        7.19,
        [("Cr", 24, 1.0, 1.0)],
        "Metal adhesion layer."
    ))
    mats.append(_mat(
        "Gold (Au)", "Au",
        19.32,
        [("Au", 79, 1.0, 1.0)],
        "Metal film."
    ))
    return mats


def preset_stack_templates():
    return [
        {
            "name": "Si (bulk substrate)",
            "description": "Single-layer silicon substrate.",
            "materials": ["Silicon (Si)"],
            "stack": [
                {"material_name": "Silicon (Si)", "thickness_nm": 350000.0, "role": "substrate"},
            ],
        },
        {
            "name": "SiO2/Si",
            "description": "300 nm oxide on bulk Si (edit thickness after import).",
            "materials": ["Silicon Dioxide (SiO2)", "Silicon (Si)"],
            "stack": [
                {"material_name": "Silicon Dioxide (SiO2)", "thickness_nm": 300.0, "role": "dielectric"},
                {"material_name": "Silicon (Si)", "thickness_nm": 350000.0, "role": "substrate"},
            ],
        },
        {
            "name": "Quartz",
            "description": "Quartz / fused silica substrate.",
            "materials": ["Quartz (SiO2, crystalline)"],
            "stack": [
                {"material_name": "Quartz (SiO2, crystalline)", "thickness_nm": 500000.0, "role": "substrate"},
            ],
        },
        {
            "name": "GaAs",
            "description": "Bulk GaAs substrate.",
            "materials": ["GaAs"],
            "stack": [
                {"material_name": "GaAs", "thickness_nm": 350000.0, "role": "substrate"},
            ],
        },
        {
            "name": "InP",
            "description": "Bulk InP substrate.",
            "materials": ["InP"],
            "stack": [
                {"material_name": "InP", "thickness_nm": 350000.0, "role": "substrate"},
            ],
        },
        {
            "name": "ma-N 2400 / Si3N4 / InP (example)",
            "description": "Example: ma-N 2400 500 nm / Si3N4 200 nm / InP 350 um",
            "materials": ["ma-N 2400 (approx.)", "Silicon Nitride (Si3N4)", "InP"],
            "stack": [
                {"material_name": "ma-N 2400 (approx.)", "thickness_nm": 500.0, "role": "resist"},
                {"material_name": "Silicon Nitride (Si3N4)", "thickness_nm": 200.0, "role": "dielectric"},
                {"material_name": "InP", "thickness_nm": 350000.0, "role": "substrate"},
            ],
        },
        {
            "name": "Sapphire",
            "description": "Bulk sapphire substrate.",
            "materials": ["Sapphire (Al2O3)"],
            "stack": [
                {"material_name": "Sapphire (Al2O3)", "thickness_nm": 430000.0, "role": "substrate"},
            ],
        },
        {
            "name": "Metal-coated Si (Cr/Au on SiO2/Si)",
            "description": "Example stack: Au 20 nm / Cr 3 nm / SiO2 300 nm / Si bulk.",
            "materials": ["Gold (Au)", "Chromium (Cr)", "Silicon Dioxide (SiO2)", "Silicon (Si)"],
            "stack": [
                {"material_name": "Gold (Au)", "thickness_nm": 20.0, "role": "metal"},
                {"material_name": "Chromium (Cr)", "thickness_nm": 3.0, "role": "adhesion"},
                {"material_name": "Silicon Dioxide (SiO2)", "thickness_nm": 300.0, "role": "dielectric"},
                {"material_name": "Silicon (Si)", "thickness_nm": 350000.0, "role": "substrate"},
            ],
        },
        {
            "name": "PMMA bilayer / graphene / Al2O3 / Au / SiO2 / thin Si (Sergei example)",
            "description": "50 keV PEC example: PMMA 950k 90 nm / PMMA 495k 150 nm / C 1 nm / Al2O3 100 nm / Au 70 nm / SiO2 300 nm / Si 4.4 um.",
            "materials": [
                "PMMA 950k (generic)",
                "PMMA 495k (generic)",
                "Graphene / Carbon (C)",
                "Aluminum Oxide (Al2O3, ALD approx.)",
                "Gold (Au)",
                "Silicon Dioxide (SiO2)",
                "Silicon (Si)",
            ],
            "stack": [
                {"material_name": "PMMA 950k (generic)", "thickness_nm": 90.0, "role": "resist"},
                {"material_name": "PMMA 495k (generic)", "thickness_nm": 150.0, "role": "resist"},
                {"material_name": "Graphene / Carbon (C)", "thickness_nm": 1.0, "role": "underlayer"},
                {"material_name": "Aluminum Oxide (Al2O3, ALD approx.)", "thickness_nm": 100.0, "role": "dielectric"},
                {"material_name": "Gold (Au)", "thickness_nm": 70.0, "role": "metal"},
                {"material_name": "Silicon Dioxide (SiO2)", "thickness_nm": 300.0, "role": "dielectric"},
                {"material_name": "Silicon (Si)", "thickness_nm": 4400.0, "role": "substrate"},
            ],
        },
    ]


# CIAAW Abridged Standard Atomic Weights 2024 (normal terrestrial materials).
# https://ciaaw.org/abridged-atomic-weights.htm
# Elements without a standard weight require an isotope-aware model; no A=2Z fallback.
ATOMIC_WEIGHTS = {
    "H": 1.0080, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81,
    "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974,
    "S": 32.06, "Cl": 35.45, "Ar": 39.95, "K": 39.098, "Ca": 40.078,
    "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904,
    "Kr": 83.798, "Rb": 85.468, "Sr": 87.62, "Y": 88.906, "Zr": 91.222,
    "Nb": 92.906, "Mo": 95.95, "Ru": 101.07, "Rh": 102.91, "Pd": 106.42,
    "Ag": 107.87, "Cd": 112.41, "In": 114.82, "Sn": 118.71, "Sb": 121.76,
    "Te": 127.60, "I": 126.90, "Xe": 131.29, "Cs": 132.91, "Ba": 137.33,
    "La": 138.91, "Ce": 140.12, "Pr": 140.91, "Nd": 144.24, "Sm": 150.36,
    "Eu": 151.96, "Gd": 157.25, "Tb": 158.93, "Dy": 162.50, "Ho": 164.93,
    "Er": 167.26, "Tm": 168.93, "Yb": 173.05, "Lu": 174.97, "Hf": 178.49,
    "Ta": 180.95, "W": 183.84, "Re": 186.21, "Os": 190.23, "Ir": 192.22,
    "Pt": 195.08, "Au": 196.97, "Hg": 200.59, "Tl": 204.38, "Pb": 207.2,
    "Bi": 208.98, "Th": 232.04, "Pa": 231.04, "U": 238.03,
}
# Element identity is validated independently of the available mass table.
_ELEMENT_SYMBOLS = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba "
    "La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb "
    "Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs "
    "Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
).split()
ATOMIC_NUMBERS = {symbol: index for index, symbol in enumerate(_ELEMENT_SYMBOLS, 1)}
ELECTRON_REST_ENERGY_KEV = 511.0


def _mean_excitation_energy_eV(elements):
    if not elements:
        return 75.0
    af_sum = sum(float(e.get("atomic_fraction", 0.0)) for e in elements) or 1.0
    total = 0.0
    for e in elements:
        z = max(1.0, float(e.get("Z", 1.0)))
        ai = float(e.get("atomic_fraction", 0.0)) / af_sum
        total += ai * (9.76 * z + 58.8 * (z ** -0.19))
    return max(30.0, total)


def _mean_ionization_energy_keV(z):
    z = max(1, int(round(float(z))))
    if z == 1:
        return 19.2e-3
    return (9.76 * z + 58.8 * (z ** -0.19)) * 1e-3


def _relativistic_beta2(energy_keV):
    gamma = 1.0 + max(0.0, float(energy_keV)) / ELECTRON_REST_ENERGY_KEV
    return max(1e-6, 1.0 - 1.0 / (gamma * gamma))


def _electron_range_nm(energy_keV, props):
    coeff = max(1e-6, float(props.get("ko_range_coeff_nm", 1.0)))
    return max(1.0, coeff * (max(float(energy_keV), 0.01) ** 1.67))


def _elastic_mean_free_path_nm(energy_keV, props):
    rng = _electron_range_nm(energy_keV, props)
    screening = 1.0 + 0.045 * max(1.0, float(props.get("zeff_af", 10.0))) + 0.12 * max(0.2, float(props.get("rho", 1.0)))
    return max(0.5, 0.009 * rng / screening)


def _screened_rutherford_theta(zeff, energy_keV, rng):
    alpha = 3.4e-3 * max(1.0, float(zeff)) ** 0.67 / max(float(energy_keV), 1e-3)
    rr = rng.random()
    cos_t = 1.0 - 2.0 * alpha * rr / max(1e-14, 1.0 + alpha - rr)
    return math.acos(max(-1.0, min(1.0, cos_t)))


def _bethe_stopping_keV_per_nm(energy_keV, props):
    """Legacy uncalibrated blend, not the pure modified-Bethe expression.

    The repository does not establish a literature source for 0.65/0.35 or
    0.72. Keep these visible until an independent stopping benchmark selects
    a replacement; see docs/CORRECTNESS_REVIEW.md.
    """
    e = max(float(energy_keV), 0.02)
    rho = max(0.1, float(props.get("rho", 1.0)))
    deds = 0.0
    for zi, ai, wi, ji_keV in props.get("bragg_wZ", []):
        if wi <= 0 or ai <= 0 or ji_keV <= 0 or zi <= 0:
            continue
        arg = max(1.001, 1.166 * (e + 0.85 * ji_keV) / ji_keV)
        deds += rho * wi * 7.85e-3 * zi / (ai * e) * math.log(arg)
    csda_like = 0.72 * e / max(_electron_range_nm(e, props), 1.0)
    return max(1e-7, 0.35 * csda_like + 0.65 * deds)


def _projected_backscatter_beta_nm(beam_energy_keV, substrate_zeff=None):
    e = max(5.0, float(beam_energy_keV or 0.0))
    scale = 1.0
    if substrate_zeff is not None:
        scale *= max(0.75, min(1.45, (max(1.0, float(substrate_zeff)) / 14.0) ** 0.18))
    return max(800.0, 280.0 * e * scale)


def _is_high_tension_thin_resist(beam_energy_keV, resist_thickness_nm):
    if beam_energy_keV is None or resist_thickness_nm is None:
        return False
    return float(beam_energy_keV) >= 80.0 and float(resist_thickness_nm) <= 120.0


def _estimate_atomic_weight(symbol, z):
    symbol = str(symbol).strip().capitalize()
    if symbol not in ATOMIC_WEIGHTS:
        raise ValueError(
            f"No standard atomic weight is available for {symbol!r}; "
            "an isotope-specific material model is required."
        )
    return ATOMIC_WEIGHTS[symbol]


def _material_mc_properties(material):
    elements = _canonical_material_elements(material)
    rho = float(material.get("density_g_cm3", 1.0))
    if not math.isfinite(rho) or rho <= 0.0:
        raise ValueError("Material density must be finite and > 0.")
    af_sum = sum(float(e.get("atomic_fraction", 0.0)) for e in elements) or 1.0
    wf_sum = sum(float(e.get("weight_fraction", 0.0)) for e in elements) or 1.0
    zeff_af = sum(float(e.get("atomic_fraction", 0.0)) / af_sum * float(e.get("Z", 0.0)) for e in elements)
    a_eff = sum(
        (float(e.get("atomic_fraction", 0.0)) / af_sum) * _estimate_atomic_weight(str(e.get("symbol", "")), float(e.get("Z", 0.0)))
        for e in elements
    )
    z_back = sum((float(e.get("weight_fraction", 0.0)) / wf_sum) * (float(e.get("Z", 0.0)) ** 1.35) for e in elements)
    mean_i_eV = _mean_excitation_energy_eV(elements)
    num_j = 0.0
    den_j = 0.0
    bragg_wZ = []
    for e in elements:
        wf = float(e.get("weight_fraction", 0.0)) / wf_sum
        zi = max(1, int(round(float(e.get("Z", 1.0)))))
        ai = max(1.0, _estimate_atomic_weight(str(e.get("symbol", "")), zi))
        ji_keV = _mean_ionization_energy_keV(zi)
        p = wf / ai * zi
        num_j += p * math.log(ji_keV)
        den_j += p
        bragg_wZ.append((float(zi), ai, wf, ji_keV))
    if den_j > 0:
        mean_i_eV = math.exp(num_j / den_j) * 1e3
    scatter_strength = max(1e-6, rho * (zeff_af ** 0.75))
    stop_strength = max(1e-6, rho * ((zeff_af / max(a_eff, 1.0)) ** 0.25) * (zeff_af ** 0.35))
    ko_range_coeff_nm = 27.6 * a_eff / max(1e-6, rho * (zeff_af ** 0.89))
    return {
        "rho": rho,
        "zeff_af": zeff_af,
        "z_back": z_back,
        "a_eff": a_eff,
        "scatter_strength": scatter_strength,
        "stop_strength": stop_strength,
        "mean_I_eV": mean_i_eV,
        "ko_range_coeff_nm": ko_range_coeff_nm,
        "bragg_wZ": bragg_wZ,
    }


def _normalize_vec3(v):
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z)
    if n <= 0:
        return (0.0, 0.0, 1.0)
    return (x / n, y / n, z / n)


def _scatter_direction(dir_vec, theta, phi):
    ux, uy, uz = _normalize_vec3(dir_vec)
    if abs(uz) < 0.999:
        hx, hy, hz = _normalize_vec3((-uy, ux, 0.0))
    else:
        hx, hy, hz = (1.0, 0.0, 0.0)
    vx, vy, vz = (
        uy * hz - uz * hy,
        uz * hx - ux * hz,
        ux * hy - uy * hx,
    )
    st = math.sin(theta)
    ct = math.cos(theta)
    cp = math.cos(phi)
    sp = math.sin(phi)
    nx = ct * ux + st * (cp * hx + sp * vx)
    ny = ct * uy + st * (cp * hy + sp * vy)
    nz = ct * uz + st * (cp * hz + sp * vz)
    return _normalize_vec3((nx, ny, nz))


def _configure_toplevel(win, parent=None, width=760, height=540, min_width=480, min_height=320):
    if parent is not None:
        win.transient(parent)
    win.resizable(True, True)
    win.geometry(f"{int(width)}x{int(height)}")
    win.minsize(int(min_width), int(min_height))


def _mousewheel_units(delta):
    if delta == 0:
        return 0
    if abs(delta) >= 120:
        return int(-delta / 120)
    return -1 if delta > 0 else 1


def _bind_wheel_scroll(widget, y_target, x_target=None):
    def scroll_y(units):
        if units:
            y_target.yview_scroll(units, "units")

    def scroll_x(units):
        if x_target is not None and units:
            x_target.xview_scroll(units, "units")

    def on_mousewheel(event):
        scroll_y(_mousewheel_units(getattr(event, "delta", 0)))
        return "break"

    def on_shift_mousewheel(event):
        scroll_x(_mousewheel_units(getattr(event, "delta", 0)))
        return "break"

    widget.bind("<MouseWheel>", on_mousewheel, add="+")
    widget.bind("<Shift-MouseWheel>", on_shift_mousewheel, add="+")
    widget.bind("<Button-4>", lambda e: (scroll_y(-1), "break")[1], add="+")
    widget.bind("<Button-5>", lambda e: (scroll_y(1), "break")[1], add="+")
    if x_target is not None:
        widget.bind("<Shift-Button-4>", lambda e: (scroll_x(-1), "break")[1], add="+")
        widget.bind("<Shift-Button-5>", lambda e: (scroll_x(1), "break")[1], add="+")


def _create_scrolled_body(parent, padding=10):
    shell = ttk.Frame(parent)
    shell.pack(fill="both", expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(0, weight=1)

    canvas = tk.Canvas(shell, highlightthickness=0, borderwidth=0)
    yscroll = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=yscroll.set)

    canvas.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")

    body = ttk.Frame(canvas, padding=padding)
    body_window = canvas.create_window((0, 0), window=body, anchor="nw")

    def on_body_configure(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def on_canvas_configure(event):
        canvas.itemconfigure(body_window, width=event.width)

    body.bind("<Configure>", on_body_configure)
    canvas.bind("<Configure>", on_canvas_configure)
    _bind_wheel_scroll(canvas, canvas)
    return shell, body, canvas


def _format_duration_compact(seconds):
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "--:--"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class ElementRow:
    def __init__(self, parent, remove_callback):
        self.frame = ttk.Frame(parent)
        self.symbol_var = tk.StringVar()
        self.z_var = tk.StringVar()
        self.wf_var = tk.StringVar()
        self.af_var = tk.StringVar()

        ttk.Entry(self.frame, width=8, textvariable=self.symbol_var).grid(row=0, column=0, padx=2, pady=2)
        ttk.Entry(self.frame, width=8, textvariable=self.z_var).grid(row=0, column=1, padx=2, pady=2)
        ttk.Entry(self.frame, width=12, textvariable=self.wf_var).grid(row=0, column=2, padx=2, pady=2)
        ttk.Entry(self.frame, width=12, textvariable=self.af_var, state="readonly").grid(row=0, column=3, padx=2, pady=2)
        ttk.Button(self.frame, text="Remove", command=lambda: remove_callback(self)).grid(row=0, column=4, padx=2, pady=2)

    def to_dict(self):
        symbol = self.symbol_var.get().strip()
        z = int(self.z_var.get().strip())
        wf = safe_float(self.wf_var.get(), 0.0)
        af = safe_float(self.af_var.get(), 0.0)
        if not symbol:
            raise ValueError("Element symbol is required.")
        return {"symbol": symbol, "Z": z, "weight_fraction": wf, "atomic_fraction": af}

    def set_from_dict(self, data):
        self.symbol_var.set(str(data.get("symbol", "")))
        self.z_var.set(str(data.get("Z", "")))
        self.wf_var.set(str(data.get("weight_fraction", "")))
        self.af_var.set(str(data.get("atomic_fraction", "")))


class MaterialDialog(tk.Toplevel):
    def __init__(self, master, material=None):
        super().__init__(master)
        self.title("Material Editor")
        self.result = None
        self.element_rows = []
        _configure_toplevel(self, master, width=860, height=640, min_width=620, min_height=420)

        self.name_var = tk.StringVar(value="" if material is None else material.get("name", ""))
        self.alias_var = tk.StringVar(value="" if material is None else material.get("alias", ""))
        self.density_var = tk.StringVar(value="" if material is None else str(material.get("density_g_cm3", "")))
        self.notes_var = tk.StringVar(value="" if material is None else material.get("notes", ""))

        _, top, _ = _create_scrolled_body(self, padding=10)

        ttk.Label(top, text="Name").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, width=40, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(top, text="Alias").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, width=40, textvariable=self.alias_var).grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(top, text="Density (g/cm^3)").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, width=20, textvariable=self.density_var).grid(row=2, column=1, sticky="w", padx=4, pady=2)
        ttk.Label(top, text="Notes").grid(row=3, column=0, sticky="w")
        ttk.Entry(top, width=60, textvariable=self.notes_var).grid(row=3, column=1, sticky="ew", padx=4, pady=2)

        cols = ttk.Frame(top)
        cols.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(cols, text="Element").grid(row=0, column=0, padx=2)
        ttk.Label(cols, text="Z").grid(row=0, column=1, padx=2)
        ttk.Label(cols, text="Weight frac").grid(row=0, column=2, padx=2)
        ttk.Label(cols, text="Atomic frac (derived)").grid(row=0, column=3, padx=2)

        self.rows_frame = ttk.Frame(top)
        self.rows_frame.grid(row=5, column=0, columnspan=2, sticky="nsew")

        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text="Add Element", command=self.add_element_row).pack(side="left")
        ttk.Button(btns, text="Normalize Fractions", command=self.normalize_fractions).pack(side="left", padx=6)
        ttk.Button(btns, text="Save", command=self.save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=6)

        top.columnconfigure(1, weight=1)

        if material and material.get("elements"):
            for e in material["elements"]:
                self.add_element_row(e)
        else:
            self.add_element_row()

        self.grab_set()
        self.wait_visibility()
        self.focus_set()
        self.bind("<Escape>", lambda _e: self.destroy())

    def add_element_row(self, data=None):
        row = ElementRow(self.rows_frame, self.remove_element_row)
        row.frame.pack(fill="x", anchor="w")
        if data:
            row.set_from_dict(data)
        self.element_rows.append(row)

    def remove_element_row(self, row):
        if row in self.element_rows:
            self.element_rows.remove(row)
            row.frame.destroy()

    def normalize_fractions(self):
        try:
            elements = _canonical_material_elements({"elements": [r.to_dict() for r in self.element_rows]})
            for row, element in zip(self.element_rows, elements):
                row.set_from_dict(element)
        except Exception as exc:
            messagebox.showerror("Normalize Error", str(exc), parent=self)

    def save(self):
        try:
            self.result = _validated_material({
                "name": self.name_var.get().strip(),
                "alias": self.alias_var.get().strip(),
                "density_g_cm3": self.density_var.get(),
                "notes": self.notes_var.get().strip(),
                "elements": [r.to_dict() for r in self.element_rows],
            })
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Material Error", str(exc), parent=self)


class StackDesignerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EBL Stack Designer (Python) | made by Sergei Nomoev")
        self.materials = []
        self.project_path = None
        self._current_unit_last = "pA"
        self._stack_drag_src_iid = None
        self._stack_drag_active = False
        self._sim_progress_win = None
        self._sim_progress_stage_var = tk.StringVar(value="")
        self._sim_progress_detail_var = tk.StringVar(value="")

        self.project = {
            "project_name": "New EBL Stack",
            "beam": {"energy_keV": 50.0, "beam_diameter_nm": None, "current_pA": None, "current_input_unit": "pA"},
            "materials": [],
            "stack": [],
            "pec_fits": [],
            "notes": "",
        }

        self._build_ui()
        self.refresh_all()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        main.rowconfigure(3, weight=1)

        header = ttk.LabelFrame(main, text="Project / Beam (Rutherford-Bethe-inspired PEC Simulator)")
        header.grid(row=0, column=0, sticky="ew")
        for i in range(9):
            header.columnconfigure(i, weight=0)
        header.columnconfigure(1, weight=1)

        self.project_name_var = tk.StringVar()
        self.energy_var = tk.StringVar()
        self.diam_var = tk.StringVar()
        self.current_var = tk.StringVar()
        self.current_unit_var = tk.StringVar(value="pA")
        self.sim_progress_var = tk.DoubleVar(value=0.0)
        self.workflow_hint_var = tk.StringVar(
            value="Workflow: 1) Import presets  2) Build stack  3) Rutherford/Bethe MC + adaptive PSF fit  4) Plot / Save results"
        )

        ttk.Label(header, text="Project").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(header, width=28, textvariable=self.project_name_var).grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(header, text="Energy (keV)").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(header, width=10, textvariable=self.energy_var).grid(row=0, column=3, padx=4, pady=4)
        ttk.Label(header, text="Beam diam. (nm)").grid(row=0, column=4, sticky="w", padx=4, pady=4)
        ttk.Entry(header, width=10, textvariable=self.diam_var).grid(row=0, column=5, padx=4, pady=4)
        ttk.Label(header, text="Current").grid(row=0, column=6, sticky="w", padx=4, pady=4)
        ttk.Entry(header, width=10, textvariable=self.current_var).grid(row=0, column=7, padx=4, pady=4)
        current_unit_combo = ttk.Combobox(
            header, width=5, state="readonly", textvariable=self.current_unit_var, values=("pA", "nA")
        )
        current_unit_combo.grid(row=0, column=8, padx=(0, 4), pady=4, sticky="w")
        current_unit_combo.bind("<<ComboboxSelected>>", self._on_current_unit_changed)
        ttk.Label(header, textvariable=self.workflow_hint_var, foreground="#444").grid(
            row=1, column=0, columnspan=9, sticky="w", padx=4, pady=(2, 4)
        )
        ttk.Progressbar(
            header,
            orient="horizontal",
            mode="determinate",
            maximum=100.0,
            variable=self.sim_progress_var,
        ).grid(row=2, column=0, columnspan=9, sticky="ew", padx=4, pady=(0, 4))

        actions = ttk.LabelFrame(main, text="Actions")
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        actions.columnconfigure(0, weight=1)

        mat_toolbar = ttk.Frame(actions)
        mat_toolbar.grid(row=0, column=0, sticky="w", padx=6, pady=(4, 2))
        ttk.Label(mat_toolbar, text="Materials:").pack(side="left", padx=(0, 6))
        ttk.Button(mat_toolbar, text="New Material", command=self.add_material).pack(side="left")
        ttk.Button(mat_toolbar, text="Import Preset Materials", command=self.import_preset_materials).pack(side="left", padx=4)
        ttk.Button(mat_toolbar, text="Edit Material", command=self.edit_material).pack(side="left", padx=4)
        ttk.Button(mat_toolbar, text="Delete Material", command=self.delete_material).pack(side="left")

        stack_toolbar = ttk.Frame(actions)
        stack_toolbar.grid(row=1, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(stack_toolbar, text="Stack:").pack(side="left", padx=(0, 28))
        ttk.Button(stack_toolbar, text="Add Layer", command=self.add_layer).pack(side="left")
        ttk.Button(stack_toolbar, text="Add Preset Stack", command=self.add_preset_stack).pack(side="left", padx=4)
        ttk.Button(stack_toolbar, text="Edit Layer", command=self.edit_layer).pack(side="left", padx=4)
        ttk.Button(stack_toolbar, text="Delete Layer", command=self.delete_layer).pack(side="left")
        ttk.Button(stack_toolbar, text="Move Up", command=lambda: self.move_layer(-1)).pack(side="left", padx=4)
        ttk.Button(stack_toolbar, text="Move Down", command=lambda: self.move_layer(1)).pack(side="left")

        sim_toolbar = ttk.Frame(actions)
        sim_toolbar.grid(row=2, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(sim_toolbar, text="Simulation:").pack(side="left", padx=(0, 4))
        ttk.Button(sim_toolbar, text="Run Simulation + Fit αβη", command=self.run_standalone_sim_and_fit).pack(side="left", padx=2)
        ttk.Button(sim_toolbar, text="Plot Last PEC Fit", command=self.plot_last_fit).pack(side="left", padx=4)
        ttk.Button(sim_toolbar, text="Export PSF Curve", command=self.export_psf_curve).pack(side="left", padx=4)

        file_toolbar = ttk.Frame(actions)
        file_toolbar.grid(row=3, column=0, sticky="w", padx=6, pady=(2, 4))
        ttk.Label(file_toolbar, text="Project:").pack(side="left", padx=(0, 19))
        ttk.Button(file_toolbar, text="Save JSON", command=self.save_project).pack(side="left")
        ttk.Button(file_toolbar, text="Load JSON", command=self.load_project).pack(side="left", padx=4)
        ttk.Button(file_toolbar, text="Export Project Summary", command=self.export_summary).pack(side="left")

        mat_frame = ttk.LabelFrame(main, text="Material Library (user-defined)")
        mat_frame.grid(row=2, column=0, sticky="nsew", pady=(4, 4))
        mat_frame.columnconfigure(0, weight=1)
        mat_frame.rowconfigure(0, weight=1)

        self.mat_tree = ttk.Treeview(mat_frame, columns=("density", "elements"), show="headings", height=8)
        self.mat_tree.heading("density", text="Density (g/cm^3)")
        self.mat_tree.heading("elements", text="Elements")
        self.mat_tree.column("density", width=120, anchor="center")
        self.mat_tree.column("elements", width=520)
        self.mat_tree.grid(row=0, column=0, sticky="nsew")
        mat_scroll = ttk.Scrollbar(mat_frame, orient="vertical", command=self.mat_tree.yview)
        mat_scroll.grid(row=0, column=1, sticky="ns")
        self.mat_tree.configure(yscrollcommand=mat_scroll.set)

        stack_frame = ttk.LabelFrame(main, text="Layer Stack (top -> bottom)")
        stack_frame.grid(row=3, column=0, sticky="nsew")
        stack_frame.columnconfigure(0, weight=1)
        stack_frame.columnconfigure(1, weight=1)
        stack_frame.rowconfigure(0, weight=1)

        stack_list_frame = ttk.Frame(stack_frame)
        stack_list_frame.grid(row=0, column=0, sticky="nsew")
        stack_list_frame.columnconfigure(0, weight=1)
        stack_list_frame.rowconfigure(0, weight=1)

        self.stack_tree = ttk.Treeview(
            stack_list_frame,
            columns=("material", "thickness", "topz", "bottomz", "role"),
            show="headings",
            height=8,
        )
        self.stack_tree.heading("material", text="Material")
        self.stack_tree.heading("thickness", text="Thickness (nm)")
        self.stack_tree.heading("topz", text="Top z (nm)")
        self.stack_tree.heading("bottomz", text="Bottom z (nm)")
        self.stack_tree.heading("role", text="Role")
        self.stack_tree.column("material", width=270)
        self.stack_tree.column("thickness", width=110, anchor="center")
        self.stack_tree.column("topz", width=95, anchor="center")
        self.stack_tree.column("bottomz", width=105, anchor="center")
        self.stack_tree.column("role", width=120, anchor="center")
        self.stack_tree.grid(row=0, column=0, sticky="nsew")
        stack_scroll = ttk.Scrollbar(stack_list_frame, orient="vertical", command=self.stack_tree.yview)
        stack_scroll.grid(row=0, column=1, sticky="ns")
        self.stack_tree.configure(yscrollcommand=stack_scroll.set)
        self.stack_tree.bind("<<TreeviewSelect>>", lambda e: self._on_stack_selection_changed())
        self.stack_tree.bind("<ButtonPress-1>", self._on_stack_tree_press)
        self.stack_tree.bind("<B1-Motion>", self._on_stack_tree_drag)
        self.stack_tree.bind("<ButtonRelease-1>", self._on_stack_tree_release)

        preview_frame = ttk.LabelFrame(stack_frame, text="Stack Cross-Section Preview")
        preview_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.stack_canvas = tk.Canvas(preview_frame, bg="white", width=420, height=260, highlightthickness=1, highlightbackground="#aaa")
        self.stack_canvas.grid(row=0, column=0, sticky="nsew")
        self.stack_canvas.bind("<Configure>", lambda e: self.draw_stack_preview())
        self.total_stack_var = tk.StringVar(value="Total stack thickness: 0 nm")
        self.layer_detail_var = tk.StringVar(value="Selected layer: none")
        ttk.Label(preview_frame, textvariable=self.total_stack_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(preview_frame, textvariable=self.layer_detail_var, foreground="#444").grid(row=2, column=0, sticky="w")

        footer = ttk.Frame(main)
        footer.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        footer.rowconfigure(1, weight=1)
        ttk.Label(footer, text="Selected Material Summary").pack(anchor="w")
        summary_frame = ttk.Frame(footer)
        summary_frame.pack(fill="both", expand=True)
        summary_frame.columnconfigure(0, weight=1)
        summary_frame.rowconfigure(0, weight=1)
        self.summary = tk.Text(summary_frame, height=10, wrap="word")
        self.summary.grid(row=0, column=0, sticky="nsew")
        summary_scroll = ttk.Scrollbar(summary_frame, orient="vertical", command=self.summary.yview)
        summary_scroll.grid(row=0, column=1, sticky="ns")
        self.summary.configure(yscrollcommand=summary_scroll.set)
        _bind_wheel_scroll(self.summary, self.summary)
        self.mat_tree.bind("<<TreeviewSelect>>", lambda e: self.show_selected_material_summary())
        self.last_fit_result = None
        self.fit_info_var = tk.StringVar(value="No PEC fit yet.")
        for variable in (self.energy_var, self.diam_var, self.current_var):
            variable.trace_add("write", lambda *_: self._refresh_fit_info())
        ttk.Label(footer, textvariable=self.fit_info_var).pack(anchor="w", pady=(6, 0))
        ttk.Label(footer, text="made by Sergei Nomoev", foreground="#666").pack(anchor="e", pady=(4, 0))

    def refresh_all(self):
        self.project_name_var.set(self.project.get("project_name", ""))
        beam = self.project.get("beam", {})
        self.energy_var.set("" if beam.get("energy_keV") is None else str(beam.get("energy_keV")))
        self.diam_var.set("" if beam.get("beam_diameter_nm") is None else str(beam.get("beam_diameter_nm")))
        current_unit = str(beam.get("current_input_unit", "pA"))
        if current_unit not in ("pA", "nA"):
            current_unit = "pA"
        self.current_unit_var.set(current_unit)
        current_pA = beam.get("current_pA")
        if current_pA is None:
            self.current_var.set("")
        else:
            display_current = self._convert_current_value(float(current_pA), "pA", current_unit)
            self.current_var.set(f"{display_current:g}")
        self._current_unit_last = current_unit
        self.materials = self.project.get("materials", [])
        self.project.setdefault("pec_fits", [])
        self.refresh_materials()
        self.refresh_stack()
        self._refresh_fit_info()

    def _convert_current_value(self, value, from_unit, to_unit):
        if value is None:
            return None
        if from_unit == to_unit:
            return float(value)
        if from_unit == "pA" and to_unit == "nA":
            return float(value) / 1000.0
        if from_unit == "nA" and to_unit == "pA":
            return float(value) * 1000.0
        return float(value)

    def _on_current_unit_changed(self, _event=None):
        new_unit = str(self.current_unit_var.get() or "pA")
        old_unit = str(getattr(self, "_current_unit_last", "pA") or "pA")
        if new_unit not in ("pA", "nA"):
            new_unit = "pA"
        if old_unit not in ("pA", "nA"):
            old_unit = "pA"
        if new_unit != old_unit:
            try:
                value = safe_float(self.current_var.get(), None)
                if value is not None:
                    converted = self._convert_current_value(value, old_unit, new_unit)
                    self.current_var.set(f"{converted:g}")
            except Exception:
                pass
        self._current_unit_last = new_unit

    def refresh_materials(self):
        for i in self.mat_tree.get_children():
            self.mat_tree.delete(i)
        for idx, m in enumerate(self.materials):
            elems = ", ".join(f"{e['symbol']}(Z={e['Z']})" for e in m.get("elements", []))
            self.mat_tree.insert("", "end", iid=str(idx), values=(m.get("density_g_cm3", ""), elems))

    def refresh_stack(self):
        for i in self.stack_tree.get_children():
            self.stack_tree.delete(i)
        z_top = 0.0
        total = 0.0
        for idx, layer in enumerate(self.project.get("stack", [])):
            t = float(layer.get("thickness_nm", 0) or 0)
            z_bottom = z_top + t
            self.stack_tree.insert("", "end", iid=str(idx), values=(
                layer.get("material_name", ""),
                layer.get("thickness_nm", ""),
                f"{z_top:.3f}",
                f"{z_bottom:.3f}",
                layer.get("role", ""),
            ))
            z_top = z_bottom
            total = z_bottom
        self.total_stack_var.set(f"Total stack thickness: {total:.3f} nm")
        self._update_selected_layer_detail()
        self.draw_stack_preview()
        self._refresh_fit_info()

    def selected_material_index(self):
        sel = self.mat_tree.selection()
        return None if not sel else int(sel[0])

    def selected_layer_index(self):
        sel = self.stack_tree.selection()
        return None if not sel else int(sel[0])

    def _on_stack_selection_changed(self):
        self._update_selected_layer_detail()
        self.draw_stack_preview()

    def _update_selected_layer_detail(self):
        idx = self.selected_layer_index()
        if idx is None or idx >= len(self.project.get("stack", [])):
            self.layer_detail_var.set("Selected layer: none")
            return
        layer = self.project["stack"][idx]
        z_top = 0.0
        for i, l in enumerate(self.project["stack"]):
            t = float(l.get("thickness_nm", 0) or 0)
            z_bottom = z_top + t
            if i == idx:
                self.layer_detail_var.set(
                    f"Selected layer #{idx+1}: {l.get('material_name','?')} | {t:.3f} nm | "
                    f"z={z_top:.3f}..{z_bottom:.3f} nm | role={l.get('role','')}"
                )
                return
            z_top = z_bottom

    def add_material(self):
        dlg = MaterialDialog(self.root)
        self.root.wait_window(dlg)
        if dlg.result:
            if any(m["name"] == dlg.result["name"] for m in self.materials):
                messagebox.showerror("Material Error", "A material with this name already exists.")
                return
            self.materials.append(dlg.result)
            self.project["materials"] = self.materials
            self.refresh_materials()

    def import_preset_materials(self):
        presets = preset_material_library()
        names = [m["name"] for m in presets]
        selected = self._multi_select_dialog(
            title="Import Preset Materials",
            prompt="Select preset materials to add",
            items=names,
        )
        if not selected:
            return
        added = 0
        skipped = 0
        for idx in selected:
            m = dict(presets[idx])
            if any(existing.get("name") == m["name"] for existing in self.materials):
                skipped += 1
                continue
            self.materials.append(m)
            added += 1
        self.project["materials"] = self.materials
        self.refresh_materials()
        messagebox.showinfo("Preset Materials", f"Added: {added}\nSkipped (already existed): {skipped}")

    def import_named_presets(self, names):
        presets_by_name = {m["name"]: m for m in preset_material_library()}
        added = 0
        skipped = 0
        missing = []
        for name in names:
            if name not in presets_by_name:
                missing.append(name)
                continue
            if any(existing.get("name") == name for existing in self.materials):
                skipped += 1
                continue
            self.materials.append(dict(presets_by_name[name]))
            added += 1
        self.project["materials"] = self.materials
        self.refresh_materials()
        if missing:
            messagebox.showwarning("Preset Import", f"Missing preset(s): {', '.join(missing)}")
        elif added or skipped:
            self.workflow_hint_var.set(f"Added preset materials: {added}, skipped existing: {skipped}")

    def add_preset_stack(self):
        templates = preset_stack_templates()
        names = [f"{t['name']} - {t.get('description','')}" for t in templates]
        selected = self._single_select_dialog(
            title="Add Preset Stack",
            prompt="Choose a substrate/stack template",
            items=names,
        )
        if selected is None:
            return
        tmpl = templates[selected]

        presets_by_name = {m["name"]: m for m in preset_material_library()}
        added_mats = 0
        for mat_name in tmpl.get("materials", []):
            if any(existing.get("name") == mat_name for existing in self.materials):
                continue
            if mat_name in presets_by_name:
                self.materials.append(dict(presets_by_name[mat_name]))
                added_mats += 1

        if self.project.get("stack"):
            if not messagebox.askyesno(
                "Add Preset Stack",
                "Append template layers to current stack?\n\nYes = append\nNo = replace current stack"
            ):
                self.project["stack"] = []

        for layer in tmpl.get("stack", []):
            self.project["stack"].append(dict(layer))

        self.project["materials"] = self.materials
        self.refresh_materials()
        self.refresh_stack()
        self._refresh_fit_info()
        messagebox.showinfo(
            "Preset Stack Added",
            f"Template: {tmpl['name']}\nAdded materials: {added_mats}\nLayers now in stack: {len(self.project['stack'])}"
        )

    def _multi_select_dialog(self, title, prompt, items):
        result = {"selection": None}
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        _configure_toplevel(dlg, self.root, width=760, height=520, min_width=420, min_height=300)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)
        ttk.Label(frm, text=prompt).grid(row=0, column=0, sticky="w")
        list_frame = ttk.Frame(frm)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=6)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        lb = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, width=80, height=min(16, max(6, len(items))), exportselection=False)
        lb.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(list_frame, orient="horizontal", command=lb.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        lb.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        _bind_wheel_scroll(lb, lb, lb)
        for item in items:
            lb.insert("end", item)
        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, sticky="ew")

        def select_all():
            lb.select_set(0, "end")

        def on_ok():
            result["selection"] = list(lb.curselection())
            dlg.destroy()

        ttk.Button(btns, text="Select All", command=select_all).pack(side="left")
        ttk.Button(btns, text="OK", command=on_ok).pack(side="right")
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right", padx=6)
        lb.bind("<Double-Button-1>", lambda _e: on_ok())
        self.root.wait_window(dlg)
        return result["selection"]

    def _single_select_dialog(self, title, prompt, items):
        result = {"selection": None}
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        _configure_toplevel(dlg, self.root, width=760, height=500, min_width=420, min_height=300)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)
        ttk.Label(frm, text=prompt).grid(row=0, column=0, sticky="w")
        list_frame = ttk.Frame(frm)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=6)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        lb = tk.Listbox(list_frame, selectmode=tk.SINGLE, width=90, height=min(14, max(5, len(items))), exportselection=False)
        lb.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(list_frame, orient="horizontal", command=lb.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        lb.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        _bind_wheel_scroll(lb, lb, lb)
        for item in items:
            lb.insert("end", item)
        if items:
            lb.select_set(0)
        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, sticky="ew")

        def on_ok():
            sel = lb.curselection()
            result["selection"] = None if not sel else int(sel[0])
            dlg.destroy()

        ttk.Button(btns, text="OK", command=on_ok).pack(side="right")
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right", padx=6)
        lb.bind("<Double-Button-1>", lambda _e: on_ok())
        self.root.wait_window(dlg)
        return result["selection"]

    def edit_material(self):
        idx = self.selected_material_index()
        if idx is None:
            messagebox.showinfo("Edit Material", "Select a material first.")
            return
        dlg = MaterialDialog(self.root, self.materials[idx])
        self.root.wait_window(dlg)
        if dlg.result:
            if any(i != idx and mat["name"] == dlg.result["name"] for i, mat in enumerate(self.materials)):
                messagebox.showerror("Material Error", "A material with this name already exists.")
                return
            old_name = self.materials[idx]["name"]
            self.materials[idx] = dlg.result
            new_name = dlg.result["name"]
            for layer in self.project.get("stack", []):
                if layer.get("material_name") == old_name:
                    layer["material_name"] = new_name
            self.refresh_materials()
            self.refresh_stack()
            self._refresh_fit_info()

    def delete_material(self):
        idx = self.selected_material_index()
        if idx is None:
            messagebox.showinfo("Delete Material", "Select a material first.")
            return
        name = self.materials[idx]["name"]
        used = any(l.get("material_name") == name for l in self.project.get("stack", []))
        if used:
            messagebox.showerror("Delete Material", "Material is used in the stack. Remove those layers first.")
            return
        if messagebox.askyesno("Delete Material", f"Delete material '{name}'?"):
            del self.materials[idx]
            self.project["materials"] = self.materials
            self.refresh_materials()

    def add_layer(self):
        if not self.materials:
            messagebox.showinfo("Add Layer", "Add at least one material first.")
            return
        self.edit_layer_dialog(None)

    def edit_layer(self):
        idx = self.selected_layer_index()
        if idx is None:
            messagebox.showinfo("Edit Layer", "Select a layer first.")
            return
        self.edit_layer_dialog(idx)

    def edit_layer_dialog(self, idx):
        layer = {} if idx is None else dict(self.project["stack"][idx])

        dlg = tk.Toplevel(self.root)
        dlg.title("Layer Editor")
        _configure_toplevel(dlg, self.root, width=560, height=320, min_width=420, min_height=240)
        dlg.grab_set()
        _, frm, _ = _create_scrolled_body(dlg, padding=10)

        mat_names = [m["name"] for m in self.materials]
        mat_var = tk.StringVar(value=layer.get("material_name", mat_names[0]))
        thick_var = tk.StringVar(value="" if layer.get("thickness_nm") is None else str(layer.get("thickness_nm", "")))
        role_var = tk.StringVar(value=layer.get("role", ""))

        ttk.Label(frm, text="Material").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(frm, textvariable=mat_var, values=mat_names, state="readonly", width=36).grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(frm, text="Thickness (nm)").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(frm, textvariable=thick_var, width=20).grid(row=1, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(frm, text="Role").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(frm, textvariable=role_var, values=["resist", "underlayer", "adhesion", "hard mask", "substrate", "metal", "dielectric", "other"], width=20).grid(row=2, column=1, sticky="w", padx=4, pady=4)

        def on_ok():
            try:
                t = _finite_input(thick_var.get(), "Thickness", positive=True)
                rec = {
                    "material_name": mat_var.get().strip(),
                    "thickness_nm": t,
                    "role": role_var.get().strip() or "other",
                }
                if idx is None:
                    self.project["stack"].append(rec)
                else:
                    self.project["stack"][idx] = rec
                self.refresh_stack()
                dlg.destroy()
            except Exception as exc:
                messagebox.showerror("Layer Error", str(exc), parent=dlg)

        btns = ttk.Frame(dlg, padding=(10, 0, 10, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text="OK", command=on_ok).pack(side="right")
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right", padx=6)
        self.root.wait_window(dlg)

    def delete_layer(self):
        idx = self.selected_layer_index()
        if idx is None:
            messagebox.showinfo("Delete Layer", "Select a layer first.")
            return
        del self.project["stack"][idx]
        self.refresh_stack()

    def move_layer(self, delta):
        idx = self.selected_layer_index()
        if idx is None:
            return
        new_idx = idx + delta
        self._reorder_layer(idx, new_idx)

    def _reorder_layer(self, src_idx, dst_idx):
        stack = self.project.get("stack", [])
        if not stack:
            return False
        if src_idx < 0 or src_idx >= len(stack) or dst_idx < 0 or dst_idx >= len(stack):
            return False
        if src_idx == dst_idx:
            return False
        layer = stack.pop(src_idx)
        stack.insert(dst_idx, layer)
        self.refresh_stack()
        self.stack_tree.selection_set(str(dst_idx))
        self.stack_tree.focus(str(dst_idx))
        self.stack_tree.see(str(dst_idx))
        self._on_stack_selection_changed()
        return True

    def _on_stack_tree_press(self, event):
        row_id = self.stack_tree.identify_row(event.y)
        self._stack_drag_src_iid = row_id if row_id else None
        self._stack_drag_active = False

    def _on_stack_tree_drag(self, event):
        if not self._stack_drag_src_iid:
            return
        row_id = self.stack_tree.identify_row(event.y)
        if row_id:
            self._stack_drag_active = True
            self.stack_tree.selection_set(row_id)
            self.stack_tree.focus(row_id)
            self.stack_tree.see(row_id)

    def _on_stack_tree_release(self, event):
        try:
            src_id = self._stack_drag_src_iid
            if src_id and self._stack_drag_active:
                dst_id = self.stack_tree.identify_row(event.y)
                if not dst_id:
                    children = self.stack_tree.get_children("")
                    if children:
                        dst_id = children[-1] if event.y >= self.stack_tree.winfo_height() else children[0]
                if dst_id:
                    self._reorder_layer(int(src_id), int(dst_id))
                    return
            self.draw_stack_preview()
        finally:
            self._stack_drag_src_iid = None
            self._stack_drag_active = False

    def draw_stack_preview(self):
        if not hasattr(self, "stack_canvas"):
            return
        c = self.stack_canvas
        c.delete("all")
        w = max(c.winfo_width(), 240)
        h = max(c.winfo_height(), 180)
        left, right, top, bottom = 25, 25, 15, 20
        pw = w - left - right
        ph = h - top - bottom
        c.create_rectangle(left, top, left + pw, top + ph, outline="#444")
        c.create_text(left + 6, top - 2, text="z = 0 nm (surface)", anchor="sw", fill="#555", font=("Helvetica", 9))

        layers = self.project.get("stack", [])
        if not layers:
            c.create_text(w / 2, h / 2, text="No layers in stack", fill="#666")
            return

        thicknesses = [max(float(l.get("thickness_nm", 0) or 0), 0.0) for l in layers]
        total_phys = sum(thicknesses)
        # Visual compression for thick substrates: log-like weighting keeps all layers visible.
        vis = [math.log10(t + 10.0) for t in thicknesses]
        vis_sum = sum(vis) if sum(vis) > 0 else float(len(layers))
        y = top
        z_top = 0.0
        colors = {
            "resist": "#f4d35e",
            "dielectric": "#90caf9",
            "substrate": "#b0bec5",
            "metal": "#cfd8dc",
            "adhesion": "#ffe082",
            "underlayer": "#c5e1a5",
            "hard mask": "#bcaaa4",
        }
        selected_idx = self.selected_layer_index()

        for i, layer in enumerate(layers):
            tnm = thicknesses[i]
            z_bottom = z_top + tnm
            vh = max(14.0, ph * (vis[i] / vis_sum))
            if i == len(layers) - 1:
                y2 = top + ph
            else:
                y2 = min(top + ph, y + vh)
            role = str(layer.get("role", "other")).lower()
            fill = colors.get(role, "#e0e0e0")
            c.create_rectangle(left + 1, y, left + pw - 1, y2, fill=fill, outline="#888")
            if selected_idx is not None and i == selected_idx:
                c.create_rectangle(left + 2, y + 1, left + pw - 2, y2 - 1, outline="#d32f2f", width=2)

            label = f"{layer.get('material_name','?')} | {tnm:.3f} nm"
            if (y2 - y) >= 18:
                c.create_text(left + 8, (y + y2) / 2, text=label, anchor="w", font=("Helvetica", 10))
            else:
                # Put external label if layer is visually thin
                c.create_line(left + pw + 2, (y + y2) / 2, left + pw + 12, (y + y2) / 2, fill="#666")
                c.create_text(left + pw + 16, (y + y2) / 2, text=label, anchor="w", font=("Helvetica", 9))

            # Depth labels on left edge for layer boundaries (sparse)
            if i == 0 or i == len(layers) - 1 or (y2 - y) >= 20:
                c.create_text(left - 4, y, text=f"{z_top:.0f}", anchor="e", fill="#555", font=("Helvetica", 8))
                c.create_text(left - 4, y2, text=f"{z_bottom:.0f}", anchor="e", fill="#555", font=("Helvetica", 8))
            y = y2
            z_top = z_bottom

        c.create_text(left + pw / 2, h - 8, text=f"Top → Bottom (visual thickness compressed) | Physical total = {total_phys:.3f} nm", fill="#555", font=("Helvetica", 9))

    def _beam_from_fields(self):
        current_value = safe_float(self.current_var.get(), None)
        current_unit = str(self.current_unit_var.get() or "pA")
        return {
            "energy_keV": safe_float(self.energy_var.get()),
            "beam_diameter_nm": safe_float(self.diam_var.get(), None),
            "current_pA": None if current_value is None else self._convert_current_value(current_value, current_unit, "pA"),
            "current_input_unit": current_unit,
        }

    def collect_project(self):
        candidate = dict(self.project)
        candidate["project_name"] = self.project_name_var.get().strip() or "Untitled"
        candidate["beam"] = self._beam_from_fields()
        candidate["materials"] = self.materials
        inputs = _validated_inputs(candidate)
        candidate.update(inputs)
        candidate["schema_version"] = PROJECT_SCHEMA_VERSION
        candidate["program"] = {
            "name": PROGRAM_NAME,
            "version": PROGRAM_VERSION,
            "creator": PROGRAM_CREATOR,
        }
        self.project = candidate
        self.materials = candidate["materials"]
        return self.project

    def save_project(self):
        try:
            data = self.collect_project()
            path = filedialog.asksaveasfilename(
                title="Save EBL Stack Project",
                defaultextension=".json",
                filetypes=[("JSON", "*.json")],
            )
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.project_path = path
            messagebox.showinfo("Saved", f"Saved project to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    def load_project(self):
        path = filedialog.askopenfilename(title="Load EBL Stack Project", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data, migration_warnings = self._migrate_project_data(data)
            previous = (self.project, self.project_path, self.materials, self.last_fit_result)
            field_names = ("project_name_var", "energy_var", "diam_var", "current_var", "current_unit_var")
            previous_fields = {name: getattr(self, name).get() for name in field_names}
            try:
                self.project = data
                self.project_path = path
                self.materials = data["materials"]
                fits = data.get("pec_fits", [])
                self.last_fit_result = copy.deepcopy(fits[-1]) if fits else None
                self.refresh_all()
            except Exception:
                self.project, self.project_path, self.materials, self.last_fit_result = previous
                try:
                    self.refresh_all()
                finally:
                    for name, value in previous_fields.items():
                        getattr(self, name).set(value)
                raise
            extra = "" if not migration_warnings else "\n\n" + "\n".join(migration_warnings)
            messagebox.showinfo("Loaded", f"Loaded project:\n{path}{extra}")
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def _validated_fit_record(self, fit):
        if not isinstance(fit, dict):
            raise ValueError("Each stored fit must be an object.")
        result = copy.deepcopy(fit)
        model = result.get("fit_model", "double_gaussian")
        if model not in ("double_gaussian", "power_gaussian"):
            raise ValueError("Unknown stored PSF model.")
        result["fit_model"] = model
        for name in ("beta_nm", "eta_fit"):
            result[name] = _finite_input(result.get(name), f"Fit {name}", positive=name == "beta_nm")
        forward = "alpha_power" if model == "power_gaussian" else "alpha_nm"
        result[forward] = _finite_input(result.get(forward), f"Fit {forward}", positive=True)
        for name in ("layer_pattern", "input_file"):
            if not isinstance(result.get(name, ""), str):
                raise ValueError(f"Fit {name} must be text.")
        for key in ("simulation", "psf_diagnostics", "fit_diagnostics", "fit_candidates", "beamer_gaussian"):
            if key in result and not isinstance(result[key], dict):
                raise ValueError(f"Fit {key} must be an object.")
        if "warnings" in result and (not isinstance(result["warnings"], list) or any(not isinstance(w, str) for w in result["warnings"])):
            raise ValueError("Fit warnings must be a list of text messages.")
        if "input_snapshot" in result:
            result["input_snapshot"] = _validated_inputs(result["input_snapshot"])
        if "plot_data" in result:
            curves = result["plot_data"]
            if not isinstance(curves, dict):
                raise ValueError("Fit plot_data must be an object.")
            radii = curves.get("r_nm", [])
            if not isinstance(radii, list):
                raise ValueError("Fit radii must be a list.")
            checked_r = [_finite_input(r, "Fit radius", positive=True) for r in radii]
            if any(right <= left for left, right in zip(checked_r, checked_r[1:])):
                raise ValueError("Fit radii must be strictly increasing.")
            for key in ("measured_density", "fitted_density", "beamer_gaussian_density", "log10_residual"):
                if key not in curves:
                    continue
                values = curves[key]
                if not isinstance(values, list) or len(values) != len(radii):
                    raise ValueError(f"Fit {key} must have one value per radius.")
                minimum = -float("inf") if key == "log10_residual" else 0.0
                for value in values:
                    _finite_input(value, f"Fit {key}", minimum=minimum)
        return result

    def _migrate_project_data(self, data):
        if not isinstance(data, dict):
            raise ValueError("Invalid project file.")
        data = copy.deepcopy(data)
        version = _finite_input(data.get("schema_version", 1), "Project schema version", positive=True)
        if version != int(version) or version > PROJECT_SCHEMA_VERSION:
            raise ValueError("Unsupported project schema version.")
        warnings = []
        if version < PROJECT_SCHEMA_VERSION:
            warnings.append("Legacy JSON project detected: missing optional fields were filled with defaults.")
        checked_inputs = _validated_inputs(data)
        composition_changed = any(
            "atomic_fraction" not in original
            or abs(float(original["atomic_fraction"]) - checked["atomic_fraction"]) > 1e-6
            for original_mat, checked_mat in zip(data["materials"], checked_inputs["materials"])
            for original, checked in zip(original_mat["elements"], checked_mat["elements"])
        )
        if composition_changed:
            warnings.append("Atomic fractions were recalculated from the supplied mass composition; old independently specified atomic fractions were not used.")
        data.update(checked_inputs)
        for key in ("project_name", "notes"):
            default = "Untitled" if key == "project_name" else ""
            if not isinstance(data.get(key, default), str):
                raise ValueError(f"Project {key} must be text.")
            data.setdefault(key, default)
        if "program" in data and not isinstance(data["program"], dict):
            raise ValueError("Project program metadata must be an object.")
        data.setdefault("program", {"name": PROGRAM_NAME, "version": PROGRAM_VERSION, "creator": PROGRAM_CREATOR})
        fits = data.get("pec_fits", [])
        if not isinstance(fits, list):
            raise ValueError("Project pec_fits must be a list.")
        data["pec_fits"] = [self._validated_fit_record(fit) for fit in fits]
        if any("input_snapshot" not in fit for fit in data["pec_fits"]):
            warnings.append("Stored legacy fits have no complete input snapshot. Run Simulation + Fit again before exporting them.")
        data["schema_version"] = PROJECT_SCHEMA_VERSION
        return data, warnings

    def export_summary(self):
        try:
            data = self.collect_project()
            if not data["stack"]:
                raise ValueError("Stack is empty.")
            lines = []
            lines.append(f"Project: {data['project_name']}")
            lines.append("made by Sergei Nomoev")
            lines.append(f"Beam energy: {data['beam']['energy_keV']} keV")
            if data["beam"].get("beam_diameter_nm") is not None:
                lines.append(f"Beam diameter: {data['beam']['beam_diameter_nm']} nm")
            if data["beam"].get("current_pA") is not None:
                export_unit = str(data["beam"].get("current_input_unit", "pA"))
                if export_unit not in ("pA", "nA"):
                    export_unit = "pA"
                current_display = self._convert_current_value(float(data["beam"]["current_pA"]), "pA", export_unit)
                lines.append(f"Beam current: {current_display:g} {export_unit} ({data['beam']['current_pA']:.6g} pA)")
            if self.last_fit_result:
                lines.append("")
                lines.append(f"Last PEC fit result (input state: {self._fit_state(self.last_fit_result)})")
                lines.append(f"Model: {self._fit_model_display_name(self.last_fit_result)}")
                lines.append(f"Layer: {self.last_fit_result.get('layer_pattern')}")
                lines.append(f"Source: {self.last_fit_result.get('input_file')}")
                if self.last_fit_result.get("fit_model") == "power_gaussian":
                    lines.append(f"forward power alpha_p: {self.last_fit_result.get('alpha_power', float('nan')):.4f}")
                else:
                    lines.append(f"alpha (nm): {self.last_fit_result.get('alpha_nm', float('nan')):.4f}")
                lines.append(f"beta (nm): {self.last_fit_result.get('beta_nm'):.4f}")
                lines.append(f"eta (fit): {self.last_fit_result.get('eta_fit'):.6f}")
                lines.append(f"eta (split): {self.last_fit_result.get('eta_split'):.6f}")
                diag = self.last_fit_result.get("psf_diagnostics") or {}
                fit_diag = self.last_fit_result.get("fit_diagnostics") or {}
                if diag:
                    lines.append(f"PSF integral: {float(diag.get('psf_integral', float('nan'))):.6f}")
                    lines.append(f"Total deposited energy in selected resist: {float(diag.get('total_deposited_energy_keV', float('nan'))):.6g} keV")
                if fit_diag:
                    lines.append(f"Unweighted fit MSE (log10 density): {float(fit_diag.get('fit_unweighted_mse_log10', float('nan'))):.6g}")
                lines.append(f"PEC guidance: {self.last_fit_result.get('pec_guidance', '')}")
                warnings = self.last_fit_result.get("warnings") or []
                if warnings:
                    lines.append("Warnings:")
                    for warning in warnings:
                        lines.append(f"   - {warning}")
            fits = data.get("pec_fits", [])
            if fits:
                lines.append("")
                lines.append(f"PEC fit history ({len(fits)} stored)")
                for i, fit in enumerate(fits[-5:], start=max(1, len(fits)-4)):
                    alpha_txt = (
                        f"alpha_p={fit.get('alpha_power', float('nan')):.4f}"
                        if fit.get("fit_model") == "power_gaussian"
                        else f"alpha={fit.get('alpha_nm', float('nan')):.4f} nm"
                    )
                    lines.append(
                        f"{i}. model={self._fit_model_display_name(fit)} | "
                        f"layer={fit.get('layer_pattern')} | "
                        f"{alpha_txt} | "
                        f"beta={fit.get('beta_nm', float('nan')):.4f} nm | "
                        f"eta={fit.get('eta_fit', float('nan')):.6f} | "
                        f"file={fit.get('input_file')}"
                    )
            lines.append("")
            lines.append("STACK (top -> bottom)")
            for i, layer in enumerate(data["stack"], start=1):
                mat = self.get_material(layer["material_name"])
                lines.append(f"{i}. {layer['material_name']} | {layer['thickness_nm']} nm | role={layer.get('role','')}")
                lines.append(f"   density = {mat['density_g_cm3']} g/cm^3")
                for e in mat["elements"]:
                    lines.append(
                        f"   - {e['symbol']} (Z={e['Z']}), wf={e['weight_fraction']:.6f}, af={e['atomic_fraction']:.6f}"
                    )
            text = "\n".join(lines)
            path = filedialog.asksaveasfilename(title="Export Summary", defaultextension=".txt", filetypes=[("Text", "*.txt")])
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            messagebox.showinfo("Exported", f"Exported summary to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def export_psf_curve(self):
        try:
            res = self.last_fit_result
            if not res:
                fits = self.project.get("pec_fits", [])
                res = fits[-1] if fits else None
            if not res:
                raise ValueError("No PEC fit available. Run Simulation + Fit first.")
            self._require_exportable_fit(res)
            plot_data = res.get("plot_data") or {}
            r_nm = plot_data.get("r_nm") or []
            y_fit = plot_data.get("fitted_density") or []
            if not r_nm or not y_fit:
                raise ValueError("Last PEC fit does not contain PSF curve data.")

            default_name = "ebl_psf_curve.lpsf"
            path = filedialog.asksaveasfilename(
                title="Export PSF Curve",
                defaultextension=".lpsf",
                initialfile=default_name,
                filetypes=[
                    ("BEAMER LPSF archive", "*.lpsf"),
                    ("BEAMER-style PSF two-column", "*.psf"),
                    ("CSV table", "*.csv"),
                    ("Text", "*.txt"),
                    ("All files", "*.*"),
                ],
            )
            if not path:
                return

            ext = path.lower().rsplit(".", 1)[-1] if "." in path else "psf"
            if ext == "lpsf":
                self._write_lpsf_archive(path, res)
                message = (
                    "Exported BEAMER LPSF archive.\n\n"
                    "Format: zlib-compressed LPSF_2012 XML, compatible with BEAMER-style "
                    "numerical PSF import. The curve is the selected physical fitted PSF."
                )
            elif ext == "csv":
                self._write_psf_csv(path, res)
                message = (
                    "Exported PSF CSV table.\n\n"
                    "Columns include radius_um, measured density, selected physical fit, "
                    "and BEAMER Gaussian fit when available."
                )
            else:
                self._write_psf_two_column(path, res)
                message = (
                    "Exported BEAMER-style PSF curve.\n\n"
                    "Format: radius_um  selected_fit_density_per_um2\n"
                    "No header is written for maximum compatibility with numerical PSF import."
                )
            messagebox.showinfo("PSF Exported", f"{message}\n\n{path}")
        except Exception as exc:
            messagebox.showerror("Export PSF Error", str(exc))

    def _write_psf_two_column(self, path, fit_result):
        _ensure_numpy()
        self._validate_export_source_curve(fit_result)
        r_nm, y_fit, curve_metadata = self._export_curve_data(fit_result)
        radius_um = r_nm * 1.0e-3
        density_per_um2 = y_fit * 1.0e6
        lines = [
            f"{x_um:.9g} {val:.12e}"
            for x_um, val in zip(radius_um, density_per_um2)
        ]
        self._atomic_write_text(path, "\n".join(lines) + "\n", self._validate_psf_two_column_file)

    def _write_psf_csv(self, path, fit_result):
        _ensure_numpy()
        self._validate_export_source_curve(fit_result)
        plot_data = fit_result.get("plot_data") or {}
        r_nm = np.asarray(plot_data.get("r_nm", []), dtype=float)
        y_meas = np.asarray(plot_data.get("measured_density", []), dtype=float)
        y_fit = np.asarray(plot_data.get("fitted_density", []), dtype=float)
        y_beamer = np.asarray(plot_data.get("beamer_gaussian_density", []), dtype=float)
        log_resid = np.asarray(plot_data.get("log10_residual", []), dtype=float)
        if r_nm.size == 0 or y_fit.size != r_nm.size:
            raise ValueError("Invalid PSF curve data.")
        if y_meas.size != r_nm.size:
            y_meas = np.full_like(r_nm, float("nan"))
        if y_beamer.size != r_nm.size:
            y_beamer = np.full_like(r_nm, float("nan"))
        if log_resid.size != r_nm.size:
            log_resid = np.full_like(r_nm, float("nan"))
        radius_um = r_nm * 1.0e-3
        stored_area = np.asarray(plot_data.get("ring_area_nm2", []), dtype=float)
        area = stored_area if stored_area.size == r_nm.size else _radial_ring_area_nm2(r_nm)
        cumulative_meas = _cumulative_from_density(y_meas, area)
        cumulative_fit = _cumulative_from_density(y_fit, area)
        metadata = self._export_metadata(fit_result)
        lines = [
            "# EBL Stack Designer PSF export",
            f"# program_name,{metadata['program_name']}",
            f"# program_version,{metadata['program_version']}",
            f"# creator,{metadata['creator']}",
            f"# export_time,{metadata['export_time']}",
            f"# python_version,{metadata['python_version']}",
            f"# schema_version,{metadata['schema_version']}",
            f"# stack_hash,{metadata['stack_hash']}",
            f"# material_library_hash,{metadata['material_library_hash']}",
            f"# beam_energy_keV,{metadata['beam_energy_keV']}",
            f"# number_of_electrons,{metadata['number_of_electrons']}",
            f"# random_seed,{metadata['random_seed']}",
            f"# selected_resist_layers,{metadata['selected_resist_layers']}",
            f"# model,{self._fit_model_display_name(fit_result)}",
            f"# gaussian_convention,{fit_result.get('gaussian_convention', LEGACY_GAUSSIAN_CONVENTION)}",
            f"# internal_length_unit,{INTERNAL_LENGTH_UNIT}",
            f"# beamer_length_unit,{BEAMER_LENGTH_UNIT}",
            f"# psf_normalization,{metadata['psf_normalization']}",
            f"# psf_integral,{metadata['psf_integral']}",
            f"# short_range_parameter_nm,{metadata['short_range_parameter_nm']}",
            f"# short_range_fwhm_nm,{metadata['short_range_fwhm_nm']}",
            f"# short_range_fwhm_um,{metadata['short_range_fwhm_um']}",
            f"# fit_weighted_mse_log10,{metadata['fit_weighted_mse_log10']}",
            f"# fit_unweighted_mse_log10,{metadata['fit_unweighted_mse_log10']}",
            f"# warnings,{metadata['warnings']}",
            "# curve_domain,fit_window (diagnostic data; numerical PSF/LPSF exports use the full model)",
            f"# sample_representation,{plot_data.get('sample_representation', 'legacy_outer_radius_point_approximation')}",
            "# density columns are converted from 1/nm^2 to 1/um^2",
            "radius_um,measured_density_per_um2,selected_fit_density_per_um2,beamer_gaussian_density_per_um2,cumulative_measured,cumulative_selected_fit,log10_residual_selected_minus_measured",
        ]
        for row in zip(
            radius_um,
            y_meas * 1.0e6,
            y_fit * 1.0e6,
            y_beamer * 1.0e6,
            cumulative_meas,
            cumulative_fit,
            log_resid,
        ):
            lines.append(",".join(f"{float(v):.12e}" for v in row))
        self._atomic_write_text(path, "\n".join(lines) + "\n", self._validate_psf_csv_file)

    def _write_lpsf_archive(self, path, fit_result):
        self._validate_export_source_curve(fit_result)
        points, curve_meta = self._build_lpsf_curve_points(fit_result)
        snapshot = self._fit_input_snapshot(fit_result) or {}
        stack = snapshot.get("stack", fit_result.get("stack_snapshot", []))
        stack = copy.deepcopy(stack)
        sim = fit_result.get("simulation") or {}

        beam = copy.deepcopy(snapshot.get("beam", fit_result.get("beam", {})))
        energy_keV = fit_result.get("beam_energy_keV") or sim.get("beam_energy_keV") or beam.get("energy_keV") or 0.0
        try:
            energy_keV = float(energy_keV)
        except Exception:
            energy_keV = 0.0
        try:
            electrons = int(float(sim.get("electrons", 0) or 0))
        except Exception:
            electrons = 0
        try:
            beam_diam_nm = float(beam.get("beam_diameter_nm", 0.0) or 0.0)
        except Exception:
            beam_diam_nm = 0.0
        injection_radius_nm = max(0.0, beam_diam_nm / 2.355) if beam_diam_nm > 0 else 0.0
        try:
            min_energy_eV = float(sim.get("min_energy_keV", 0.0) or 0.0) * 1000.0
        except Exception:
            min_energy_eV = 0.0
        try:
            resist_thickness_nm = float(fit_result.get("resist_thickness_nm", 0.0) or 0.0)
        except Exception:
            resist_thickness_nm = 0.0
        z_position_um = max(0.0, resist_thickness_nm / 2000.0)
        mesh_z_size_nm = 10.0
        mesh_z_count = max(1, int(math.ceil(resist_thickness_nm / mesh_z_size_nm)) + 1) if resist_thickness_nm > 0 else 1
        metadata = self._export_metadata(fit_result)

        comments = self._lpsf_comment_lines(
            stack=stack,
            point_count=len(points),
            mesh_z_count=mesh_z_count,
            mesh_z_size_nm=mesh_z_size_nm,
            energy_keV=energy_keV,
            injection_radius_nm=injection_radius_nm,
            min_energy_eV=min_energy_eV,
            electrons=electrons,
            curve_meta=curve_meta,
            fit_result=fit_result,
            metadata=metadata,
        )

        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
            '<!DOCTYPE boost_serialization>',
            '<boost_serialization signature="serialization::archive" version="8">',
            '<LPSF_2012 class_id="0" tracking_level="0" version="1">',
            '\t<m_Comments class_id="1" tracking_level="0" version="0">',
            f'\t\t<count>{len(comments)}</count>',
            '\t\t<item_version>0</item_version>',
        ]
        for item in comments:
            lines.append(f'\t\t<item>{xml_escape(str(item))}</item>')
        lines.extend([
            '\t</m_Comments>',
            '\t<m_PSFDataOriginal class_id="2" tracking_level="0" version="0">',
            f'\t\t<count>{len(points)}</count>',
            '\t\t<item_version>0</item_version>',
        ])
        for i, (x_nm, y_val) in enumerate(points):
            item_open = (
                '\t\t<item class_id="3" tracking_level="0" version="0">'
                if i == 0 else
                '\t\t<item>'
            )
            lines.extend([
                item_open,
                f'\t\t\t<m_x>{self._lpsf_num(x_nm)}</m_x>',
                f'\t\t\t<m_y>{self._lpsf_num(y_val)}</m_y>',
                '\t\t</item>',
            ])
        lines.extend([
            '\t</m_PSFDataOriginal>',
            '\t<m_bGaussFitted>0</m_bGaussFitted>',
            f'\t<m_lBeam_Energy_kV>{self._lpsf_num(energy_keV)}</m_lBeam_Energy_kV>',
            f'\t<m_dZ_Position>{self._lpsf_num(z_position_um)}</m_dZ_Position>',
            f'\t<m_lElectrons>{electrons}</m_lElectrons>',
            '\t<m_sSimulator>EBL Stack Designer standalone_mc</m_sSimulator>',
            '\t<m_Stack class_id="4" tracking_level="0" version="0">',
            f'\t\t<count>{len(stack)}</count>',
            '\t\t<item_version>0</item_version>',
        ])
        for i, layer in enumerate(stack):
            item_open = (
                '\t\t<item class_id="5" tracking_level="0" version="0">'
                if i == 0 else
                '\t\t<item>'
            )
            material = str(layer.get("material_name", "Unknown"))
            thickness_nm = float(layer.get("thickness_nm", 0.0) or 0.0)
            lines.extend([
                item_open,
                f'\t\t\t<first>{xml_escape(material)}</first>',
                f'\t\t\t<second>{self._lpsf_num(thickness_nm)}</second>',
                '\t\t</item>',
            ])
        lines.extend([
            '\t</m_Stack>',
            '</LPSF_2012>',
            '</boost_serialization>',
            '',
        ])

        xml_text = "\n".join(lines)
        payload = zlib.compress(xml_text.encode("utf-8"), level=6)
        self._atomic_write_bytes(path, payload, self._validate_lpsf_file)

    def _validate_export_source_curve(self, fit_result):
        _ensure_numpy()
        plot_data = fit_result.get("plot_data") or {}
        r_nm = np.asarray(plot_data.get("r_nm", []), dtype=float)
        y_fit = np.asarray(plot_data.get("fitted_density", []), dtype=float)
        if r_nm.size == 0 or y_fit.size != r_nm.size:
            raise ValueError("No valid selected physical fit curve is available for export.")
        mask = np.isfinite(r_nm) & np.isfinite(y_fit) & (r_nm > 0.0) & (y_fit > 0.0)
        if np.count_nonzero(mask) < 10:
            raise ValueError("Export PSF curve has too few positive finite points.")
        psf_diag = fit_result.get("psf_diagnostics") or {}
        psf_integral = psf_diag.get("psf_integral")
        if psf_integral is not None:
            psf_integral = float(psf_integral)
            if not math.isfinite(psf_integral) or abs(psf_integral - 1.0) > 0.05:
                raise ValueError(f"Refusing export: normalized PSF integral is {psf_integral:.6g}, expected approximately 1.")

    def _export_metadata(self, fit_result):
        snapshot = self._fit_input_snapshot(fit_result) or {}
        stack = snapshot.get("stack", fit_result.get("stack_snapshot"))
        materials = snapshot.get("materials", fit_result.get("materials_snapshot"))
        sim = fit_result.get("simulation") or {}
        psf_diag = fit_result.get("psf_diagnostics") or {}
        fit_diag = fit_result.get("fit_diagnostics") or {}
        selected_layers = sim.get("resist_layer_indices")
        if selected_layers is None:
            selected_layers = [sim.get("resist_layer_index")] if sim.get("resist_layer_index") is not None else []
        try:
            fwhm_um = float(fit_result.get("beamer_fwhm_um", sim.get("beamer_fwhm_um", 0.03)) or 0.0)
        except Exception:
            fwhm_um = 0.0
        short_range_parameter_um = fwhm_um / GAUSSIAN_FWHM_FACTOR if fwhm_um > 0.0 else 0.0
        return {
            "program_name": PROGRAM_NAME,
            "program_version": sim.get("program_version", "unknown"),
            "exporter_version": PROGRAM_VERSION,
            "creator": PROGRAM_CREATOR,
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "python_version": sys.version.split()[0],
            "schema_version": PROJECT_SCHEMA_VERSION,
            "stack_hash": _stable_json_hash(stack) if stack is not None else None,
            "material_library_hash": _stable_json_hash(materials) if materials is not None else None,
            "input_state_status": self._fit_state(fit_result),
            "beam_energy_keV": fit_result.get("beam_energy_keV", sim.get("beam_energy_keV")),
            "number_of_electrons": sim.get("electrons"),
            "random_seed": sim.get("seed"),
            "selected_resist_layers": selected_layers,
            "internal_length_unit": INTERNAL_LENGTH_UNIT,
            "beamer_output_length_unit": BEAMER_LENGTH_UNIT,
            "psf_normalization": psf_diag.get("normalization", "area_density_integral_1"),
            "psf_integral": psf_diag.get("psf_integral"),
            "gaussian_convention": fit_result.get("gaussian_convention", LEGACY_GAUSSIAN_CONVENTION),
            "transport_diagnostics": copy.deepcopy(fit_result.get("transport_diagnostics", {})),
            "stopping_model": sim.get("stopping_model", "unknown"),
            "short_range_parameter_nm": um_to_nm(short_range_parameter_um),
            "short_range_fwhm_nm": um_to_nm(fwhm_um),
            "short_range_fwhm_um": fwhm_um,
            "fit_model": self._fit_model_display_name(fit_result),
            "fit_weighted_mse_log10": fit_result.get("fit_mse"),
            "fit_unweighted_mse_log10": fit_diag.get("fit_unweighted_mse_log10"),
            "warnings": fit_result.get("warnings") or [],
        }

    def _atomic_write_text(self, path, text, validator):
        directory = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".ebl_export_", suffix=".tmp", dir=directory, text=True)
        os.close(fd)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(text)
            validator(tmp_path)
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _atomic_write_bytes(self, path, payload, validator):
        directory = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".ebl_export_", suffix=".tmp", dir=directory)
        os.close(fd)
        try:
            with open(tmp_path, "wb") as f:
                f.write(payload)
            validator(tmp_path)
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _validate_psf_two_column_file(self, path):
        count = 0
        last_r = -1.0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                parts = stripped.split()
                if len(parts) != 2:
                    raise ValueError("PSF text export validation failed: expected two columns.")
                r_um, value = float(parts[0]), float(parts[1])
                if not (math.isfinite(r_um) and math.isfinite(value) and r_um >= 0.0 and value > 0.0):
                    raise ValueError("PSF text export validation failed: non-positive or non-finite value.")
                if r_um <= last_r:
                    raise ValueError("PSF text export validation failed: radii are not strictly increasing.")
                last_r = r_um
                count += 1
        if count < 10:
            raise ValueError("PSF text export validation failed: too few points.")

    def _validate_psf_csv_file(self, path):
        required = {
            "radius_um",
            "measured_density_per_um2",
            "selected_fit_density_per_um2",
            "beamer_gaussian_density_per_um2",
            "cumulative_measured",
            "cumulative_selected_fit",
            "log10_residual_selected_minus_measured",
        }
        header = None
        count = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                header = [part.strip() for part in line.strip().split(",")]
                break
            if header is None or not required.issubset(set(header)):
                raise ValueError("CSV export validation failed: required columns are missing.")
            for line in f:
                if not line.strip():
                    continue
                parts = line.strip().split(",")
                if len(parts) != len(header):
                    raise ValueError("CSV export validation failed: row length mismatch.")
                values = [float(v) for v in parts]
                if not all(math.isfinite(v) or math.isnan(v) for v in values):
                    raise ValueError("CSV export validation failed: invalid numeric value.")
                count += 1
        if count < 10:
            raise ValueError("CSV export validation failed: too few data rows.")

    def _validate_lpsf_file(self, path):
        with open(path, "rb") as f:
            xml_text = zlib.decompress(f.read()).decode("utf-8")
        root = ET.fromstring(xml_text)
        data = root.find(".//m_PSFDataOriginal")
        if data is None:
            raise ValueError("LPSF export validation failed: missing m_PSFDataOriginal.")
        count_node = data.find("count")
        expected = int(count_node.text) if count_node is not None and count_node.text else 0
        xs = []
        ys = []
        for item in data.findall("item"):
            x_node = item.find("m_x")
            y_node = item.find("m_y")
            if x_node is None or y_node is None:
                raise ValueError("LPSF export validation failed: malformed point.")
            xs.append(float(x_node.text))
            ys.append(float(y_node.text))
        if expected != len(xs) or len(xs) < 10:
            raise ValueError("LPSF export validation failed: point count mismatch.")
        for i, (x_val, y_val) in enumerate(zip(xs, ys)):
            if not (math.isfinite(x_val) and math.isfinite(y_val)):
                raise ValueError("LPSF export validation failed: non-finite point.")
            if x_val < 0.0 or y_val < 0.0:
                raise ValueError("LPSF export validation failed: negative point.")
            if i > 0 and x_val <= xs[i - 1]:
                raise ValueError("LPSF export validation failed: radii are not strictly increasing.")

    def _export_curve_data(self, fit_result):
        """Full normalized PSF, with analytically bounded omitted tail mass."""
        _ensure_numpy()
        model = fit_result.get("fit_representation")
        if not model or model.get("version") != PSF_REPRESENTATION_VERSION:
            raise ValueError("This saved fit predates the full PSF representation. Rerun the simulation before numerical PSF export.")
        tolerance = PSF_EXPORT_TAIL_TOLERANCE
        radius = max(1.0, float(model["beta_nm"]), float(model.get("alpha_nm", 0.0)), float(model.get("core_radius_nm", 0.0)))
        radius = min(radius, PSF_EXPORT_MAX_RADIUS_NM)
        while _psf_model_tail_fraction(model, radius) > tolerance and radius < PSF_EXPORT_MAX_RADIUS_NM:
            radius = min(2.0 * radius, PSF_EXPORT_MAX_RADIUS_NM)
        tail = _psf_model_tail_fraction(model, radius)
        if tail > tolerance:
            raise ValueError(
                f"The fitted PSF retains {tail:.3g} of its energy beyond {radius:.3g} nm. "
                "Its power tail is too broad for controlled numerical export; increase simulation coverage or use another fit."
            )
        short_width = float(model.get("core_radius_nm", model.get("alpha_nm", 1.0)))
        first_radius = max(1e-6, min(0.01, short_width / 100.0))
        count = max(100, int(math.ceil(math.log10(radius / first_radius) * 80.0)) + 1)
        grid_r = np.concatenate(([0.0], np.geomspace(first_radius, radius, count)))
        density = _evaluate_psf_model(model, grid_r, include_amplitude=False)
        return grid_r, density, {
            "normalization": "full_plane_area_integral_one",
            "omitted_tail_fraction": tail,
            "tail_tolerance": tolerance,
            "r_max_nm": radius,
            "fit_amplitude": float(model.get("amplitude", 1.0)),
            "extrapolated_beyond_fit_window": radius > float(fit_result.get("fit_window_max_nm", 0.0)),
        }

    def _build_lpsf_curve_points(self, fit_result):
        grid_r, density, metadata = self._export_curve_data(fit_result)
        integrand = 2.0 * math.pi * grid_r * density
        integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
        integral = float(integrate(integrand, grid_r))
        if not math.isfinite(integral) or integral <= 0.0:
            raise ValueError("Exported PSF has an invalid radial integral.")
        scale = 1.0e9 / integral
        points = [(float(x), float(y * scale)) for x, y in zip(grid_r, density)]
        # Do not append a fabricated zero. The endpoint has a bounded omitted mass.
        metadata.update(points_per_decade=80, scale=scale, scaled_integral=integral * scale)
        return points, metadata

    def _lpsf_comment_lines(
        self,
        stack,
        point_count,
        mesh_z_count,
        mesh_z_size_nm,
        energy_keV,
        injection_radius_nm,
        min_energy_eV,
        electrons,
        curve_meta,
        fit_result,
        metadata=None,
    ):
        metadata = metadata or self._export_metadata(fit_result)
        now_txt = time.strftime("%Y-%b-%d %H:%M:%S")
        comments = [
            f"## PSF ARCHIVED on {now_txt}",
            "   EBL Stack Designer standalone export",
            "   made by Sergei Nomoev",
            f"   ProgramVersion: {metadata.get('program_version')}",
            f"   PythonVersion: {metadata.get('python_version')}",
            f"   SchemaVersion: {metadata.get('schema_version')}",
            f"   StackHash: {metadata.get('stack_hash')}",
            f"   MaterialLibraryHash: {metadata.get('material_library_hash')}",
            "#   Data Management  -------------------------------------------",
            "",
            "    RadialMode:                                      exponential",
            f"    MeshRZNumberR:   {point_count}",
            f"    MeshRZNumberZ:   {mesh_z_count}",
            f"    AllocSizeRZ:     {point_count * max(1, mesh_z_count)}",
            "    MeshRZR0/nm:     1",
            f"    MeshRZSpD:       {int(curve_meta.get('points_per_decade', 50))}",
            f"    MeshRZSizeZ/nm:  {self._lpsf_num(mesh_z_size_nm)}",
            f"    ExportScale:     {self._lpsf_num(curve_meta.get('scale', 0.0))}",
            f"    PSFOmittedTailFraction: {self._lpsf_num(curve_meta.get('omitted_tail_fraction', 0.0))}",
            f"    PSFTailTolerance: {self._lpsf_num(curve_meta.get('tail_tolerance', 0.0))}",
            f"    PSFModelNormalization: {curve_meta.get('normalization', '')}",
            f"    PSFFitAmplitude: {self._lpsf_num(curve_meta.get('fit_amplitude', 1.0))}",
            f"    InternalLengthUnit: {INTERNAL_LENGTH_UNIT}",
            f"    BeamerLengthUnit:   {BEAMER_LENGTH_UNIT}",
            f"    PSFNormalization:   {metadata.get('psf_normalization')}",
            f"    PSFIntegral:        {self._lpsf_num(metadata.get('psf_integral', 0.0))}",
            "#",
            "#   Material Stack  --------------------------------------------",
            "",
            "    StackDescriptor:                                    EBL Stack Designer",
            f"    NumberOfLayers:  {len(stack)}",
            "",
        ]
        for layer in stack:
            material = str(layer.get("material_name", "Unknown"))
            thickness_nm = float(layer.get("thickness_nm", 0.0) or 0.0)
            role = str(layer.get("role", ""))
            lay_flag = 1 if role.lower() == "resist" else 0
            comments.extend([
                f"    MaterialDescriptor: {material}",
                f"    Thickness/nm:       {self._lpsf_num(thickness_nm)}",
                f"    LayFlag:            {lay_flag}",
                "",
            ])
        comments.extend([
            "#",
            "#   Simulation Parameters  -------------------------------------",
            "",
            f"    Injection Energy/eV:          {self._lpsf_num(float(energy_keV) * 1000.0)}",
            f"    Gaussian Injection Radius/nm: {self._lpsf_num(injection_radius_nm)}",
            f"    SE Cutoff Energy/eV:          {self._lpsf_num(min_energy_eV)}",
            f"    Random Seed:                  {metadata.get('random_seed')}",
            f"    Selected Resist Layers:       {metadata.get('selected_resist_layers')}",
            "    Simulator:                    EBL Stack Designer standalone_mc",
            "#",
            "#   PEC Fit  ----------------------------------------------------",
            "",
            f"    FitModel:                     {self._fit_model_display_name(fit_result)}",
            f"    LayerPattern:                 {fit_result.get('layer_pattern', '')}",
            f"    GaussianConvention:           {GAUSSIAN_CONVENTION}",
            f"    Beta/nm:                      {self._lpsf_num(fit_result.get('beta_nm', 0.0))}",
            f"    Eta:                          {self._lpsf_num(fit_result.get('eta_fit', 0.0))}",
            f"    FitWindowMax/nm:              {self._lpsf_num(fit_result.get('fit_window_max_nm', 0.0))}",
            f"    FitWeightedMSELog10:          {self._lpsf_num(metadata.get('fit_weighted_mse_log10', 0.0))}",
            f"    FitUnweightedMSELog10:        {self._lpsf_num(metadata.get('fit_unweighted_mse_log10', 0.0))}",
            f"    ShortRangeParameter/nm:       {self._lpsf_num(metadata.get('short_range_parameter_nm', 0.0))}",
            f"    ShortRangeFWHM/nm:            {self._lpsf_num(metadata.get('short_range_fwhm_nm', 0.0))}",
            f"    ShortRangeFWHM/um:            {self._lpsf_num(metadata.get('short_range_fwhm_um', 0.0))}",
            "#",
            "#   Simulation Status & Statistics  ----------------------------",
            "",
            "    Traced Electrons",
            f"      - primary:  {electrons}",
            f"    Scaled PSF integral: {self._lpsf_num(curve_meta.get('scaled_integral', 0.0))}",
            f"    Warnings: {metadata.get('warnings')}",
            "",
            "#   Data Section  ----------------------------------------------",
        ])
        return comments

    def _lpsf_num(self, value):
        try:
            val = float(value)
        except Exception:
            return "0"
        if not math.isfinite(val):
            return "0"
        if abs(val) < 1e-300:
            return "0"
        return f"{val:.17g}"

    def get_material(self, name):
        for m in self.materials:
            if m["name"] == name:
                return m
        raise ValueError(f"Material not found in library: {name}")

    def show_selected_material_summary(self):
        self.summary.delete("1.0", "end")
        idx = self.selected_material_index()
        if idx is None:
            return
        m = self.materials[idx]
        lines = [
            f"Name: {m.get('name','')}",
            f"Alias: {m.get('alias','')}",
            f"Density: {m.get('density_g_cm3','')} g/cm^3",
            f"Notes: {m.get('notes','')}",
            "",
            "Material composition (for simulation):",
        ]
        wf_sum = 0.0
        af_sum = 0.0
        for e in m.get("elements", []):
            wf_sum += float(e.get("weight_fraction", 0.0))
            af_sum += float(e.get("atomic_fraction", 0.0))
            lines.append(
                f"- {e.get('symbol')} | Z={e.get('Z')} | weight_fraction={e.get('weight_fraction')} | atomic_fraction={e.get('atomic_fraction')}"
            )
        lines.append("")
        lines.append(f"Sum(weight_fraction) = {wf_sum:.6f}")
        lines.append(f"Sum(atomic_fraction) = {af_sum:.6f}")
        self.summary.insert("1.0", "\n".join(lines))

    def run_standalone_sim_and_fit(self):
        try:
            self.collect_project()
            if not self.project.get("stack"):
                raise ValueError("Stack is empty. Add layers first.")
            if not self.materials:
                raise ValueError("Material library is empty. Import/add materials first.")
        except Exception as exc:
            messagebox.showerror("Standalone Sim + Fit", str(exc))
            return

        resist_selection = self._choose_resist_layer_index()
        if resist_selection is None:
            return
        resist_indices = list(resist_selection) if isinstance(resist_selection, (list, tuple)) else [int(resist_selection)]

        defaults = {
            "electrons": "3000",
            "max_radius_nm": "50000",
            "forward_nm": "100",
            "beamer_fwhm_um": "0.030",
            "seed": "12345",
            "max_collisions_per_electron": "4000",
            "min_energy_keV": "0.05",
        }
        dlg = tk.Toplevel(self.root)
        dlg.title("Standalone Monte Carlo Simulation + PEC Fit")
        _configure_toplevel(dlg, self.root, width=760, height=480, min_width=520, min_height=320)
        dlg.grab_set()
        _, frm, _ = _create_scrolled_body(dlg, padding=10)
        frm.columnconfigure(1, weight=1)

        if len(resist_indices) == 1:
            layer = self.project["stack"][resist_indices[0]]
            resist_label = f"Resist layer: #{resist_indices[0]+1} {layer.get('material_name')}"
        else:
            parts = []
            total_t = 0.0
            for idx in resist_indices:
                layer = self.project["stack"][idx]
                total_t += float(layer.get("thickness_nm", 0.0) or 0.0)
                parts.append(f"#{idx+1} {layer.get('material_name')}")
            resist_label = f"Combined resist layers: {' + '.join(parts)} | total {total_t:.3f} nm"
        ttk.Label(frm, text=resist_label).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 8)
        )

        vars_ = {k: tk.StringVar(value=v) for k, v in defaults.items()}
        rows = [
            ("Electrons (N)", "electrons"),
            ("Max radius for histogram (nm)", "max_radius_nm"),
            ("Forward split radius for eta (nm)", "forward_nm"),
            ("BEAMER short-range FWHM (um)", "beamer_fwhm_um"),
            ("Random seed", "seed"),
            ("Max collisions / electron", "max_collisions_per_electron"),
            ("Min energy stop (keV)", "min_energy_keV"),
        ]
        for r, (label, key) in enumerate(rows, start=1):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", padx=4, pady=3)
            ttk.Entry(frm, textvariable=vars_[key], width=20).grid(row=r, column=1, sticky="w", padx=4, pady=3)

        note = (
            "This built-in simulator uses screened Rutherford-like elastic scattering, "
            "Bethe-inspired continuous energy loss, and then fits the PSF with an adaptive "
            "double-Gaussian or power-Gaussian model depending on the exposure regime."
        )
        ttk.Label(frm, text=note, wraplength=700, justify="left", foreground="#555").grid(
            row=len(rows) + 1, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 4)
        )

        def on_run():
            try:
                params = {
                    "resist_layer_index": resist_indices[0],
                    "resist_layer_indices": resist_indices,
                    "electrons": int(float(vars_["electrons"].get())),
                    "max_radius_nm": int(float(vars_["max_radius_nm"].get())),
                    "forward_nm": float(vars_["forward_nm"].get()),
                    "beamer_fwhm_um": float(vars_["beamer_fwhm_um"].get()),
                    "seed": int(float(vars_["seed"].get())),
                    "max_collisions_per_electron": int(float(vars_["max_collisions_per_electron"].get())),
                    "min_energy_keV": float(vars_["min_energy_keV"].get()),
                }
                if params["electrons"] <= 0:
                    raise ValueError("Electrons must be > 0.")
                if params["max_radius_nm"] < 1000:
                    raise ValueError("Max radius must be >= 1000 nm.")
                _finite_input(params["forward_nm"], "Forward split radius", positive=True)
                _finite_input(params["beamer_fwhm_um"], "BEAMER short-range FWHM")
                _finite_input(params["min_energy_keV"], "Stopping energy", positive=True)
                if params["min_energy_keV"] >= self.project["beam"]["energy_keV"]:
                    raise ValueError("Stopping energy must be below the beam energy.")
                if params["max_collisions_per_electron"] <= 0:
                    raise ValueError("Max collisions / electron must be > 0.")
                dlg.destroy()
                self._run_standalone_mc_job(params)
            except Exception as exc:
                messagebox.showerror("Standalone Sim + Fit", str(exc), parent=dlg)

        btns = ttk.Frame(dlg, padding=(10, 0, 10, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text="Run", command=on_run).pack(side="right")
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right", padx=6)
        self.root.wait_window(dlg)

    def _choose_resist_layer_index(self):
        stack = self.project.get("stack", [])
        if not stack:
            return None
        candidates = [i for i, l in enumerate(stack) if str(l.get("role", "")).lower() == "resist"]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) == 0:
            names = [
                f"#{i+1}: {l.get('material_name','?')} ({l.get('thickness_nm','?')} nm, role={l.get('role','')})"
                for i, l in enumerate(stack)
            ]
            idx = self._single_select_dialog(
                title="Select Resist Layer",
                prompt="No layer is marked as role='resist'. Choose which layer to analyze as resist.",
                items=names,
            )
            return idx

        total_t = sum(float(stack[i].get("thickness_nm", 0.0) or 0.0) for i in candidates)
        names = [
            "Combined all resist layers: "
            + " + ".join(f"#{i+1} {stack[i].get('material_name','?')}" for i in candidates)
            + f" ({total_t:.3f} nm total)"
        ]
        names.extend(
            f"#{i+1}: {stack[i].get('material_name','?')} ({stack[i].get('thickness_nm','?')} nm)"
            for i in candidates
        )
        local_idx = self._single_select_dialog(
            title="Select Resist Layer",
            prompt="Multiple layers are marked as 'resist'. Choose combined bilayer analysis or one layer.",
            items=names,
        )
        if local_idx is None:
            return None
        if local_idx == 0:
            return candidates
        return candidates[local_idx - 1]

    def _run_standalone_mc_job(self, params):
        old_cursor = self.root.cget("cursor")
        t0 = time.time()
        self.sim_progress_var.set(0.0)
        self._open_sim_progress_window(params["electrons"])
        self._set_sim_progress_text(
            "Running standalone Monte Carlo simulation...",
            0,
            params["electrons"],
            t0,
            collision_count=0,
        )
        try:
            self.root.config(cursor="watch")
            self.root.update_idletasks()
            sim = self._simulate_standalone_radial_distribution(params)
            self.sim_progress_var.set(100.0)
            self._set_sim_progress_message("Standalone simulation done. Fitting αβη...")
            self.workflow_hint_var.set("Standalone simulation done. Fitting αβη...")
            self.root.update_idletasks()
            res = self._fit_alpha_beta_eta_from_histogram(
                sim["rvals_nm"],
                sim["evals"],
                params["forward_nm"],
                source_label=f"standalone_mc:{int(time.time())}",
                layer_label=sim["resist_layer_name"],
                collision_count=sim["collision_count_in_resist"],
                beam_energy_keV=self.project.get("beam", {}).get("energy_keV"),
                resist_thickness_nm=sim.get("resist_thickness_nm"),
                resist_material_name=sim.get("resist_layer_name"),
                beam_sigma_nm=sim.get("beam_sigma_nm"),
            )
            res["beamer_fwhm_um"] = float(params.get("beamer_fwhm_um", 0.03))
            res["simulation"] = {
                "engine": "approximate_mc_material_local_v2",
                "program_version": PROGRAM_VERSION,
                "stopping_model": "legacy_0.65_JoyLuo_plus_0.35_range_0.72",
                "transport_validation": "numerical_consistency_only_not_physically_calibrated",
                "electrons": params["electrons"],
                "seed": params["seed"],
                "elapsed_s": time.time() - t0,
                "max_collisions_per_electron": params["max_collisions_per_electron"],
                "max_radius_nm": params["max_radius_nm"],
                "min_energy_keV": params["min_energy_keV"],
                "beamer_fwhm_um": float(params.get("beamer_fwhm_um", 0.03)),
                "beam_energy_keV": self.project.get("beam", {}).get("energy_keV"),
                "resist_layer_index": params["resist_layer_index"],
                "resist_layer_indices": params.get("resist_layer_indices", [params["resist_layer_index"]]),
                "collision_count_in_resist": sim["collision_count_in_resist"],
                "segments_in_resist": sim["segments_in_resist"],
            }
            res["transport_diagnostics"] = copy.deepcopy(sim.get("transport_diagnostics", {}))
            diagnostic_warnings = _transport_diagnostic_warnings(res["transport_diagnostics"])
            res["warnings"] = list(dict.fromkeys((res.get("warnings") or []) + diagnostic_warnings))
            res = self._store_fit_result(res)
            self._refresh_fit_info()
            self._show_fit_result_dialog(res)
            forward_txt = self._fit_forward_parameter_text(res, short=True)
            self.workflow_hint_var.set(
                f"Standalone MC + PEC fit complete (N={params['electrons']}, {forward_txt}, β={res['beta_nm']:.1f} nm, η={res['eta_fit']:.3f})"
            )
        except Exception as exc:
            messagebox.showerror("Standalone Sim + Fit", str(exc))
            self.workflow_hint_var.set("Standalone simulation failed.")
            self._set_sim_progress_message("Standalone simulation failed.")
            self.sim_progress_var.set(0.0)
        finally:
            self._close_sim_progress_window()
            self.root.config(cursor=old_cursor)
            self.root.update_idletasks()

    def _simulate_standalone_radial_distribution(self, params):
        _ensure_numpy()

        def integer_param(value, label, minimum=None):
            if isinstance(value, bool):
                raise ValueError(f"{label} must be a finite integer.")
            if isinstance(value, int):
                result = value
            else:
                try:
                    number = float(value)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(f"{label} must be a finite integer.") from exc
                if not math.isfinite(number) or not number.is_integer():
                    raise ValueError(f"{label} must be a finite integer.")
                result = int(number)
            if minimum is not None and result < minimum:
                raise ValueError(f"{label} must be >= {minimum}.")
            return result

        rng = random.Random(integer_param(params["seed"], "Random seed"))
        stack = self.project.get("stack", [])
        if not stack:
            raise ValueError("Stack is empty.")

        # All entered layers remain finite; their roles do not change transport.
        layers = []
        z = 0.0
        for i, layer in enumerate(stack):
            t = float(layer.get("thickness_nm", 0) or 0.0)
            if not math.isfinite(t) or t <= 0.0:
                raise ValueError(f"Thickness in layer {i+1} must be finite and > 0.")
            mat = self.get_material(layer["material_name"])
            props = _material_mc_properties(mat)
            layers.append({
                "index": i,
                "name": layer.get("material_name", f"Layer{i+1}"),
                "role": str(layer.get("role", "")),
                "z0": z,
                "z1": z + t,
                "thickness_nm": t,
                "material": mat,
                "props": props,
            })
            z += t
        total_stack_nm = z
        if not math.isfinite(total_stack_nm):
            raise ValueError("Total stack thickness must be finite.")

        resist_indices_raw = params.get("resist_layer_indices")
        if resist_indices_raw is None:
            resist_indices = [integer_param(params["resist_layer_index"], "Resist layer index", 0)]
        else:
            if not isinstance(resist_indices_raw, (list, tuple)):
                raise ValueError("Resist layer indices must be a list of integers.")
            resist_indices = [integer_param(i, "Resist layer index", 0) for i in resist_indices_raw]
        if not resist_indices:
            raise ValueError("No resist layer selected.")
        if len(set(resist_indices)) != len(resist_indices):
            raise ValueError("Resist layer indices must be unique.")
        for resist_idx in resist_indices:
            if resist_idx < 0 or resist_idx >= len(layers):
                raise ValueError("Invalid resist layer index.")
        resist_layers = [layers[i] for i in resist_indices]
        resist_intervals = [(L["z0"], L["z1"]) for L in resist_layers]
        resist_thickness_nm = sum(float(L["thickness_nm"]) for L in resist_layers)
        resist_layer_name = " + ".join(L["name"] for L in resist_layers)

        max_radius_nm = integer_param(params["max_radius_nm"], "Max radius (nm)", 1000)
        rvals = np.arange(1, max_radius_nm + 1, dtype=float)
        evals = np.zeros_like(rvals)

        beam = self.project.get("beam", {})
        E0 = float(beam.get("energy_keV") or 0.0)
        if not math.isfinite(E0) or E0 <= 0.0:
            raise ValueError("Beam energy (keV) must be finite and > 0.")
        beam_diam_nm = float(beam.get("beam_diameter_nm") or 0.0)
        if not math.isfinite(beam_diam_nm) or beam_diam_nm < 0.0:
            raise ValueError("Beam diameter (nm) must be finite and >= 0.")
        beam_sigma_nm = beam_diam_nm / 2.355

        ne = integer_param(params["electrons"], "Electrons", 1)
        try:
            incident_energy_keV = ne * E0
        except OverflowError as exc:
            raise ValueError("Total incident energy must be finite.") from exc
        if not math.isfinite(incident_energy_keV):
            raise ValueError("Total incident energy must be finite.")
        min_energy_keV = float(params["min_energy_keV"])
        if not math.isfinite(min_energy_keV) or not 0.0 < min_energy_keV < E0:
            raise ValueError("Min energy must be finite and satisfy 0 < E_cut < beam energy.")
        max_coll = integer_param(params["max_collisions_per_electron"], "Max collisions per electron", 1)

        collision_count_in_resist = 0
        segments_in_resist = 0
        deposited_all_keV = 0.0
        deposited_selected_keV = 0.0
        deposited_selected_in_radius_keV = 0.0
        termination_counts = {reason: 0 for reason in (
            "energy_cutoff", "escaped_top", "escaped_bottom", "max_collisions", "radial_limit"
        )}
        terminal_energy_keV = dict.fromkeys(termination_counts, 0.0)
        max_depth_nm = 0.0
        max_radius_reached_nm = 0.0
        dr = 1.0
        progress_t0 = time.time()
        update_every = max(1, min(200, ne // 40))

        def layer_at_z(zv):
            for li, L in enumerate(layers):
                if zv >= L["z0"] and zv < L["z1"]:
                    return li
            return None

        def deposit_in_resist(x0, y0, x1, y1, zmid, dE, collision_flag=False):
            nonlocal collision_count_in_resist, segments_in_resist
            nonlocal deposited_selected_keV, deposited_selected_in_radius_keV
            if not any(zmid >= z0 and zmid < z1 for z0, z1 in resist_intervals):
                return
            if dE > 0:
                deposited_selected_keV += dE
                lateral_len = math.hypot(x1 - x0, y1 - y0)
                sub_segments = min(8, max(1, int(lateral_len / 15.0)))
                share = dE / sub_segments
                for j in range(sub_segments):
                    frac = (j + 0.5) / sub_segments
                    rx = x0 + (x1 - x0) * frac
                    ry = y0 + (y1 - y0) * frac
                    idx = _radial_bin_index(math.hypot(rx, ry), dr)
                    if 0 <= idx < len(evals):
                        evals[idx] += share
                        deposited_selected_in_radius_keV += share
                segments_in_resist += 1
            if collision_flag:
                collision_count_in_resist += 1

        for ie in range(ne):
            # Beam starts at surface z=0 and travels downward.
            if beam_sigma_nm > 0:
                x = rng.gauss(0.0, beam_sigma_nm)
                y = rng.gauss(0.0, beam_sigma_nm)
            else:
                x = 0.0
                y = 0.0
            zpos = 0.0
            direction = (0.0, 0.0, 1.0)
            E = E0
            termination = None
            max_radius_reached_nm = max(max_radius_reached_nm, math.hypot(x, y))

            for _ in range(max_coll):
                li = layer_at_z(zpos)
                if li is None:
                    termination = "escaped_top" if zpos < 0 else "escaped_bottom"
                    break
                L = layers[li]
                P = L["props"]

                # Sample optical depth, not a distance tied to the launch layer.
                remaining_optical_depth = -math.log(max(1e-12, 1.0 - rng.random()))
                while remaining_optical_depth > 0.0:
                    mfp_nm = _elastic_mean_free_path_nm(E, P)
                    remaining_step = remaining_optical_depth * mfp_nm
                    ux, uy, uz = direction
                    if uz > 1e-12:
                        boundary_z = L["z1"]
                        dist_to_boundary = (boundary_z - zpos) / uz
                    elif uz < -1e-12:
                        boundary_z = L["z0"]
                        dist_to_boundary = (boundary_z - zpos) / uz
                    else:
                        boundary_z = zpos
                        dist_to_boundary = float("inf")
                    dist_to_boundary = max(0.0, dist_to_boundary)
                    geometric_step = min(remaining_step, dist_to_boundary)

                    # Freeze stopping within this segment, and shorten the segment
                    # when its available energy is exhausted before the next event.
                    stopping = _bethe_stopping_keV_per_nm(E, P) * (0.92 + 0.16 * rng.random())
                    cutoff_step = (E - min_energy_keV) / stopping if stopping > 0.0 else float("inf")
                    reaches_cutoff = cutoff_step <= geometric_step
                    reaches_boundary = dist_to_boundary <= geometric_step and not reaches_cutoff
                    step = min(geometric_step, cutoff_step)
                    x0, y0, z0 = x, y, zpos
                    x += ux * step
                    y += uy * step
                    zpos += uz * step
                    dE = E - min_energy_keV if reaches_cutoff else stopping * step
                    E -= dE
                    deposited_all_keV += dE
                    zmid = 0.5 * (z0 + zpos)
                    deposit_in_resist(x0, y0, x, y, zmid, dE, collision_flag=False)
                    max_depth_nm = max(max_depth_nm, zpos)
                    max_radius_reached_nm = max(max_radius_reached_nm, math.hypot(x, y))
                    remaining_optical_depth = max(0.0, remaining_optical_depth - step / mfp_nm)

                    if reaches_cutoff:
                        E = min_energy_keV
                        termination = "energy_cutoff"
                        break

                    if reaches_boundary:
                        # A one-ULP nudge avoids skipping an ultrathin neighboring layer.
                        zpos = math.nextafter(boundary_z, math.inf if uz > 0 else -math.inf)
                        next_li = layer_at_z(zpos)
                        if next_li is None:
                            termination = "escaped_top" if uz < 0 else "escaped_bottom"
                            break
                        li = next_li
                        L = layers[li]
                        P = L["props"]
                        continue

                    # An elastic event occurs after consuming the sampled optical depth.
                    deposit_in_resist(x0, y0, x, y, zpos, 0.0, collision_flag=True)
                    theta = _screened_rutherford_theta(P["zeff_af"], E, rng)
                    phi = 2.0 * math.pi * rng.random()
                    direction = _scatter_direction(direction, theta, phi)
                    remaining_optical_depth = 0.0

                if termination is not None:
                    break
                if math.hypot(x, y) > max_radius_nm * 4:
                    termination = "radial_limit"
                    break

            if termination is None:
                termination = "max_collisions"
            termination_counts[termination] += 1
            terminal_energy_keV[termination] += E
            done = ie + 1
            if done % update_every == 0 or ie == ne - 1:
                self._set_sim_progress_text(
                    "Standalone MC",
                    done,
                    ne,
                    progress_t0,
                    collision_count=collision_count_in_resist,
                )
                self.root.update_idletasks()

        if float(evals.sum()) <= 0:
            raise ValueError(
                "Standalone simulation produced zero deposited energy in the selected resist layer. "
                "Check stack order/role and resist thickness."
            )

        transport_diagnostics = {
            "incident_energy_keV": incident_energy_keV,
            "deposited_energy_all_materials_keV": deposited_all_keV,
            "deposited_energy_selected_resist_keV": deposited_selected_keV,
            "deposited_energy_selected_in_radius_keV": deposited_selected_in_radius_keV,
            "deposited_energy_selected_outside_radius_keV": max(0.0, deposited_selected_keV - deposited_selected_in_radius_keV),
            "escaped_energy_keV": terminal_energy_keV["escaped_top"] + terminal_energy_keV["escaped_bottom"],
            "residual_energy_at_cutoff_keV": terminal_energy_keV["energy_cutoff"],
            "residual_energy_max_collisions_keV": terminal_energy_keV["max_collisions"],
            "residual_energy_radial_limit_keV": terminal_energy_keV["radial_limit"],
            "energy_balance_error_keV": incident_energy_keV - deposited_all_keV - math.fsum(terminal_energy_keV.values()),
            "termination_counts": termination_counts,
            "max_depth_nm": max_depth_nm,
            "max_radius_reached_nm": max_radius_reached_nm,
        }
        return {
            "rvals_nm": rvals,
            "evals": evals,
            "resist_layer_index": resist_indices[0],
            "resist_layer_indices": resist_indices,
            "resist_layer_name": resist_layer_name,
            "collision_count_in_resist": int(collision_count_in_resist),
            "segments_in_resist": int(segments_in_resist),
            "resist_thickness_nm": float(resist_thickness_nm),
            "beam_sigma_nm": float(beam_sigma_nm),
            "transport_diagnostics": transport_diagnostics,
        }

    def _histogram_psf_diagnostics(self, rvals_nm, evals, ring_area_nm2, psf_density):
        _ensure_numpy()
        r = np.asarray(rvals_nm, dtype=float)
        e = np.asarray(evals, dtype=float)
        area = np.asarray(ring_area_nm2, dtype=float)
        density = np.asarray(psf_density, dtype=float)
        finite_density = np.isfinite(density)
        nonzero = (e > 0.0) & np.isfinite(e)
        integral = _density_integral(density, area)
        cumulative = _cumulative_from_density(density, area)
        warnings = []
        if not np.all(np.isfinite(e)):
            warnings.append("Raw histogram contains NaN/inf values.")
        if np.any(e < 0.0):
            warnings.append("Raw histogram contains negative energy bins.")
        if not np.all(finite_density):
            warnings.append("Normalized PSF contains NaN/inf values.")
        if np.any(density[finite_density] < 0.0):
            warnings.append("Normalized PSF contains negative values.")
        if not math.isfinite(integral) or abs(integral - 1.0) > 5.0e-3:
            warnings.append(f"Normalized PSF integral is {integral:.6g}, expected approximately 1.")
        return {
            "normalization": "area_density_integral_1",
            "internal_length_unit": INTERNAL_LENGTH_UNIT,
            "density_unit": "1/nm^2",
            "total_deposited_energy_keV": float(np.sum(e[np.isfinite(e)])),
            "psf_integral": integral,
            "cumulative_energy_r_max": float(cumulative[-1]) if cumulative.size else float("nan"),
            "r_max_nm": float(r[-1]) if r.size else float("nan"),
            "radial_bin_count": int(r.size),
            "nonzero_bin_count": int(np.count_nonzero(nonzero)),
            "warnings": warnings,
        }

    def _fit_curve_diagnostics(self, r_nm, measured_density, fitted_density, weights=None, ring_area_nm2=None):
        _ensure_numpy()
        r = np.asarray(r_nm, dtype=float)
        measured = np.asarray(measured_density, dtype=float)
        fitted = np.asarray(fitted_density, dtype=float)
        if r.size == 0 or measured.size != r.size or fitted.size != r.size:
            return {
                "fit_unweighted_mse_log10": float("nan"),
                "fit_max_abs_log10_residual": float("nan"),
                "selected_fit_integral_window": float("nan"),
                "measured_integral_window": float("nan"),
                "warnings": ["Fit curve diagnostics could not be computed."],
            }
        if ring_area_nm2 is None:
            area = _radial_ring_area_nm2(r)
        else:
            area = np.asarray(ring_area_nm2, dtype=float)
            if area.size != r.size:
                area = _radial_ring_area_nm2(r)
        mask = (
            np.isfinite(measured)
            & np.isfinite(fitted)
            & (measured > 0.0)
            & (fitted > 0.0)
        )
        warnings = []
        if np.count_nonzero(mask) < max(10, int(0.1 * r.size)):
            warnings.append("Too few positive finite bins for robust residual diagnostics.")
        log_resid = np.zeros_like(r, dtype=float)
        if np.any(mask):
            log_resid[mask] = np.log10(fitted[mask]) - np.log10(measured[mask])
        unweighted = float(np.mean(log_resid[mask] ** 2)) if np.any(mask) else float("nan")
        if weights is not None:
            w = np.asarray(weights, dtype=float)
            if w.size == r.size and np.any(mask):
                w_mask = np.clip(w[mask], 0.0, None)
                weighted = float(np.sum(w_mask * log_resid[mask] ** 2) / max(float(np.sum(w_mask)), 1e-300))
            else:
                weighted = float("nan")
        else:
            weighted = float("nan")
        selected_integral = _density_integral(fitted, area)
        measured_integral = _density_integral(measured, area)
        if not math.isfinite(selected_integral) or selected_integral <= 0.0:
            warnings.append("Selected physical fit integral is invalid in the fit window.")
        if np.any(fitted[np.isfinite(fitted)] < 0.0):
            warnings.append("Selected physical fit contains negative values.")
        return {
            "fit_unweighted_mse_log10": unweighted,
            "fit_weighted_mse_log10_check": weighted,
            "fit_max_abs_log10_residual": float(np.max(np.abs(log_resid[mask]))) if np.any(mask) else float("nan"),
            "selected_fit_integral_window": selected_integral,
            "measured_integral_window": measured_integral,
            "log10_residual": log_resid.tolist(),
            "warnings": warnings,
        }

    def _fit_parameter_warnings(self, physical_fit, beamer_fit):
        warnings = []

        def finite_positive(name, value, allow_zero=False):
            try:
                val = float(value)
            except Exception:
                warnings.append(f"{name} is not numeric.")
                return float("nan")
            if not math.isfinite(val):
                warnings.append(f"{name} is not finite.")
            elif val < 0.0 or (val == 0.0 and not allow_zero):
                warnings.append(f"{name} must be positive.")
            return val

        beta = finite_positive("Physical beta_nm", physical_fit.get("beta_nm"))
        eta = finite_positive("Physical eta", physical_fit.get("eta_fit"), allow_zero=True)
        if str(physical_fit.get("fit_model", "")) == "double_gaussian":
            alpha = finite_positive("Physical alpha_nm", physical_fit.get("alpha_nm"))
            if math.isfinite(alpha) and math.isfinite(beta) and beta <= alpha:
                warnings.append("Physical double-Gaussian beta is not larger than alpha.")
        elif str(physical_fit.get("fit_model", "")) == "power_gaussian":
            finite_positive("Physical alpha_power", physical_fit.get("alpha_power"))
        if math.isfinite(eta) and eta > 50.0:
            warnings.append("Physical eta is very large; PEC fit may be boundary/noise dominated.")

        alpha_b = finite_positive("BEAMER alpha_nm", beamer_fit.get("alpha_nm"))
        gamma1 = finite_positive("BEAMER gamma1_nm", beamer_fit.get("gamma1_nm"), allow_zero=True)
        gamma2 = finite_positive("BEAMER gamma2_nm", beamer_fit.get("gamma2_nm"), allow_zero=True)
        beta_b = finite_positive("BEAMER beta_nm", beamer_fit.get("beta_nm"))
        finite_positive("BEAMER eta", beamer_fit.get("eta_fit"), allow_zero=True)
        finite_positive("BEAMER nue1", beamer_fit.get("nue1"), allow_zero=True)
        finite_positive("BEAMER nue2", beamer_fit.get("nue2"), allow_zero=True)
        if math.isfinite(alpha_b) and math.isfinite(gamma1) and gamma1 > 0.0 and gamma1 <= alpha_b:
            warnings.append("BEAMER gamma1 is not larger than alpha.")
        if math.isfinite(gamma2) and gamma2 > 0.0:
            if math.isfinite(gamma1) and gamma2 <= gamma1:
                warnings.append("BEAMER gamma2 is not larger than gamma1.")
            if math.isfinite(beta_b) and beta_b <= gamma2:
                warnings.append("BEAMER beta is not larger than gamma2.")
        elif math.isfinite(gamma1) and gamma1 > 0.0 and math.isfinite(beta_b) and beta_b <= gamma1:
            warnings.append("BEAMER beta is not larger than gamma1.")
        return warnings

    def _fit_alpha_beta_eta_from_histogram(
        self,
        rvals,
        evals,
        forward_nm,
        source_label,
        layer_label,
        collision_count,
        beam_energy_keV=None,
        resist_thickness_nm=None,
        resist_material_name=None,
        beam_sigma_nm=None,
    ):
        _ensure_numpy()
        rvals = np.asarray(rvals, dtype=float)
        evals = np.asarray(evals, dtype=float).copy()
        if rvals.ndim != 1 or evals.ndim != 1 or len(rvals) != len(evals):
            raise ValueError("Invalid histogram arrays.")
        if len(rvals) < 10:
            raise ValueError("Histogram is too short.")

        total_e = float(evals.sum())
        if total_e <= 0:
            raise ValueError("No energy in histogram.")
        ev = evals / total_e
        ring_area = _radial_ring_area_nm2(rvals)
        ed = np.zeros_like(ev, dtype=float)
        np.divide(ev, ring_area, out=ed, where=ring_area > 0)
        psf_diagnostics = self._histogram_psf_diagnostics(rvals, evals, ring_area, ed)
        if psf_diagnostics["warnings"]:
            severe = [w for w in psf_diagnostics["warnings"] if "integral" in w or "negative" in w or "NaN/inf" in w]
            if severe:
                raise ValueError("Invalid normalized PSF: " + "; ".join(severe))
        fit_window = self._prepare_fit_window(
            rvals,
            ev,
            ring_area,
            ed,
            beam_energy_keV=beam_energy_keV,
            resist_thickness_nm=resist_thickness_nm,
        )
        x = fit_window["x_nm"]
        y = fit_window["y_log10_density"]
        fit_ring_area = fit_window["ring_area"]
        fit_weights = fit_window["weights"]

        best_dg = self._fit_double_gaussian_grid(
            x,
            y,
            fit_ring_area,
            fit_weights=fit_weights,
            beam_energy_keV=beam_energy_keV,
            resist_thickness_nm=resist_thickness_nm,
        )
        best_pg = self._fit_power_gaussian_grid(
            x,
            y,
            fit_ring_area,
            fit_weights=fit_weights,
            beam_energy_keV=beam_energy_keV,
            resist_thickness_nm=resist_thickness_nm,
            beam_sigma_nm=beam_sigma_nm,
            resist_material_name=resist_material_name,
        )
        beamer_fit = self._fit_beamer_gaussian_grid(
            x,
            y,
            fit_ring_area,
            fit_weights=fit_weights,
            double_gaussian_seed=best_dg,
        )
        beamer_plot_density = self._beamer_gaussian_density(
            x,
            fit_ring_area,
            beamer_fit,
            target_y_log10_density=y,
            fit_weights=fit_weights,
        )

        prefer_pg = _is_high_tension_thin_resist(beam_energy_keV, resist_thickness_nm)
        if prefer_pg:
            best = best_pg if best_pg["mse"] <= best_dg["mse"] * 1.10 else best_dg
        else:
            best = best_pg if best_pg["mse"] < best_dg["mse"] * 0.90 else best_dg

        fit_diag = self._fit_curve_diagnostics(
            best["plot_r_nm"],
            best["plot_measured_density"],
            best["plot_fitted_density"],
            weights=fit_weights,
            ring_area_nm2=fit_ring_area,
        )
        warnings = []
        warnings.extend(psf_diagnostics.get("warnings", []))
        warnings.extend(fit_diag.get("warnings", []))
        warnings.extend(self._fit_parameter_warnings(best, beamer_fit))

        fwd, back = _radial_energy_split(rvals, ev, float(forward_nm))
        eta_split = back / fwd if fwd > 0 else float("nan")

        out = {
            "input_file": source_label,
            "layer_pattern": layer_label,
            "layer_collision_count": int(collision_count),
            "forward_range_nm": float(forward_nm),
            "fit_model": best["fit_model"],
            "fit_model_display": self._fit_model_display_name(best),
            "beta_nm": best["beta_nm"],
            "eta_fit": best["eta_fit"],
            "eta_split": eta_split,
            "fit_mse": best["mse"],
            "fit_unweighted_mse_log10": fit_diag["fit_unweighted_mse_log10"],
            "fit_max_abs_log10_residual": fit_diag["fit_max_abs_log10_residual"],
            "fit_representation": dict(best["fit_representation"]),
            "plot_data": {
                "r_nm": best["plot_r_nm"],
                "ring_area_nm2": fit_ring_area.tolist(),
                "sample_representation": "annular_area_average_at_outer_radius",
                "measured_density": best["plot_measured_density"],
                "fitted_density": best["plot_fitted_density"],
                "beamer_gaussian_density": beamer_plot_density.tolist(),
                "log10_residual": fit_diag["log10_residual"],
            },
            "psf_diagnostics": psf_diagnostics,
            "fit_diagnostics": {k: v for k, v in fit_diag.items() if k not in ("log10_residual", "warnings")},
            "warnings": warnings,
            "fit_candidates": {
                "double_gaussian": {
                    "mse": best_dg["mse"],
                    "alpha_nm": best_dg["alpha_nm"],
                    "beta_nm": best_dg["beta_nm"],
                    "eta_fit": best_dg["eta_fit"],
                },
                "power_gaussian": {
                    "mse": best_pg["mse"],
                    "alpha_power": best_pg["alpha_power"],
                    "beta_nm": best_pg["beta_nm"],
                    "eta_fit": best_pg["eta_fit"],
                },
                "beamer_gaussian": dict(beamer_fit),
            },
            "beamer_gaussian": dict(beamer_fit),
            "beam_energy_keV": None if beam_energy_keV is None else float(beam_energy_keV),
            "resist_thickness_nm": None if resist_thickness_nm is None else float(resist_thickness_nm),
            "resist_material_name": resist_material_name,
            "fit_window_max_nm": fit_window["fit_window_max_nm"],
            "fit_point_count": fit_window["fit_point_count"],
            "fit_excluded_bin_count": int(len(rvals) - fit_window["fit_point_count"]),
            "fit_weighting": fit_window["weighting_description"],
            "gaussian_convention": GAUSSIAN_CONVENTION,
            "internal_length_unit": INTERNAL_LENGTH_UNIT,
            "beamer_length_unit": BEAMER_LENGTH_UNIT,
        }
        if best["fit_model"] == "power_gaussian":
            out["alpha_power"] = best["alpha_power"]
            out["alpha_nm"] = float("nan")
        else:
            out["alpha_nm"] = best["alpha_nm"]
            out["alpha_power"] = None
        out["pec_guidance"] = self._pec_guidance_from_fit(out)
        return out

    def _fit_model_display_name(self, fit_result):
        if str(fit_result.get("fit_model", "")) == "power_gaussian":
            return "Power-Gaussian composite"
        return "Double-Gaussian"

    def _fit_forward_parameter_text(self, fit_result, short=False):
        if str(fit_result.get("fit_model", "")) == "power_gaussian":
            value = float(fit_result.get("alpha_power", float("nan")))
            return f"alpha_p={value:.3f}" if short else f"Forward power αp: {value:.4f}"
        value = float(fit_result.get("alpha_nm", float("nan")))
        return f"alpha={value:.2f} nm" if short else f"Alpha (nm): {value:.4f}"

    def _pec_guidance_from_fit(self, fit_result):
        beta_um = float(fit_result.get("beta_nm", 0.0)) / 1000.0
        eta = float(fit_result.get("eta_split", fit_result.get("eta_fit", 0.0)) or 0.0)
        if beta_um >= 8.0 or eta >= 0.35:
            return "Boundary-sensitive regime: edge-focused PEC is important."
        if beta_um >= 4.0 or eta >= 0.15:
            return "Moderate boundary sensitivity: layout edges will dominate correction error."
        return "Mostly local blur regime: forward scattering dominates over long-range backscatter."

    def _prepare_fit_window(
        self,
        rvals,
        ev,
        ring_area,
        ed,
        beam_energy_keV=None,
        resist_thickness_nm=None,
    ):
        mask = np.isfinite(ed) & (ed > 0)
        mask[:2] = False
        x_full = np.asarray(rvals[mask], dtype=float)
        y_full = np.log10(np.asarray(ed[mask], dtype=float))
        ev_full = np.asarray(ev[mask], dtype=float)
        ring_full = np.asarray(ring_area[mask], dtype=float)
        if x_full.size < 50:
            raise ValueError("Too few valid points to fit alpha/beta/eta.")

        max_fit_radius_nm = min(float(rvals[-1]) * 0.8, 20000.0)
        base_mask = (x_full >= 2.0) & (x_full <= max_fit_radius_nm)
        x = x_full[base_mask]
        y = y_full[base_mask]
        ev_sel = ev_full[base_mask]
        ring_sel = ring_full[base_mask]
        if x.size < 50:
            raise ValueError("Too few valid points in fitting window.")

        tail_cut_applied = False
        if x.size >= 80:
            idx = np.arange(x.size, dtype=int)
            win = min(31, max(7, (x.size // 40) * 2 + 1))
            kernel = np.ones(win, dtype=float) / win
            smooth_y = np.convolve(y, kernel, mode="same")
            rough = np.abs(y - smooth_y)
            rough_s = np.convolve(rough, kernel, mode="same")
            rel_ev = ev_sel / max(float(np.max(ev_sel)), 1e-300)
            cum_ev = np.cumsum(ev_sel) / max(float(np.sum(ev_sel)), 1e-300)
            tail_start_nm = max(800.0, 2.5 * float(resist_thickness_nm or 0.0) + 250.0)
            tail_candidates = np.where(
                (idx >= max(60, int(0.55 * x.size)))
                & (x >= tail_start_nm)
                & (cum_ev >= 0.999)
                & ((rough_s > 0.20) | (rel_ev < 5e-4))
            )[0]
            if tail_candidates.size:
                cut_idx = int(tail_candidates[0])
                if cut_idx >= 50:
                    x_cut = x[:cut_idx]
                    y_cut = y[:cut_idx]
                    ev_cut = ev_sel[:cut_idx]
                    ring_cut = ring_sel[:cut_idx]
                    if x_cut.size >= 50:
                        x, y, ev_sel, ring_sel = x_cut, y_cut, ev_cut, ring_cut
                        tail_cut_applied = True

        center_scale_nm = 180.0
        if resist_thickness_nm is not None:
            center_scale_nm = max(40.0, min(500.0, 0.8 * float(resist_thickness_nm)))
        elif beam_energy_keV is not None:
            center_scale_nm = max(60.0, min(350.0, 3.0 * float(beam_energy_keV)))
        radial_w = 1.0 / (1.0 + (x / center_scale_nm) ** 0.85)
        signal_w = np.sqrt(np.clip(ev_sel / max(float(np.max(ev_sel)), 1e-300), 1e-8, 1.0))
        weights = radial_w * signal_w
        weights /= max(float(np.mean(weights)), 1e-300)
        weighting_description = (
            "weighted log-fit with center-priority and signal-based downweighting"
        )
        if tail_cut_applied:
            weighting_description += "; noisy far-tail auto-cut applied"

        return {
            "x_nm": x,
            "y_log10_density": y,
            "ring_area": ring_sel,
            "weights": weights,
            "fit_window_max_nm": float(x[-1]),
            "fit_point_count": int(x.size),
            "weighting_description": weighting_description,
        }

    def _show_text_dialog(self, title, text, width=760, height=520):
        win = tk.Toplevel(self.root)
        win.title(title)
        _configure_toplevel(win, self.root, width=width, height=height, min_width=480, min_height=320)

        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        txt = tk.Text(frm, wrap="word", height=20)
        txt.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        txt.configure(yscrollcommand=scroll.set)
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        _bind_wheel_scroll(txt, txt)

        btns = ttk.Frame(win, padding=(10, 0, 10, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())
        return win

    def _open_sim_progress_window(self, total_electrons):
        if self._sim_progress_win is not None and self._sim_progress_win.winfo_exists():
            self._sim_progress_win.deiconify()
            self._sim_progress_win.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("Simulation Progress")
        _configure_toplevel(win, self.root, width=560, height=180, min_width=460, min_height=160)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: win.withdraw())

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)

        ttk.Label(frm, text="Monte Carlo progress", font=("Helvetica", 13, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Label(frm, textvariable=self._sim_progress_stage_var, foreground="#333").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Progressbar(
            frm,
            orient="horizontal",
            mode="determinate",
            maximum=100.0,
            variable=self.sim_progress_var,
        ).grid(row=2, column=0, sticky="ew", pady=8)
        ttk.Label(
            frm,
            textvariable=self._sim_progress_detail_var,
            foreground="#444",
            justify="left",
        ).grid(row=3, column=0, sticky="w")
        ttk.Label(frm, text=f"Target electrons: {total_electrons}", foreground="#666").grid(
            row=4, column=0, sticky="w", pady=(8, 0)
        )

        self._sim_progress_win = win
        win.lift()

    def _set_sim_progress_message(self, message):
        self._sim_progress_stage_var.set(message)
        self._sim_progress_detail_var.set("")
        self.workflow_hint_var.set(message)
        if self._sim_progress_win is not None and self._sim_progress_win.winfo_exists():
            self._sim_progress_win.update_idletasks()

    def _set_sim_progress_text(self, stage, done, total, start_time, collision_count=None):
        elapsed_s = max(0.0, time.time() - start_time)
        frac = (done / total) if total > 0 else 0.0
        rate = (done / elapsed_s) if elapsed_s > 1e-9 else 0.0
        eta_s = ((total - done) / rate) if rate > 1e-9 else float("nan")
        collision_txt = "" if collision_count is None else f", collisions={collision_count}"
        header_text = (
            f"{stage}: {done}/{total} electrons ({100.0 * frac:.1f}%), "
            f"ETA={_format_duration_compact(eta_s)}"
        )
        detail_text = (
            f"Elapsed: {_format_duration_compact(elapsed_s)}   "
            f"Speed: {rate:.1f} e-/s   "
            f"Remaining: {_format_duration_compact(eta_s)}"
            f"{collision_txt}"
        )
        self.sim_progress_var.set(100.0 * frac)
        self._sim_progress_stage_var.set(header_text)
        self._sim_progress_detail_var.set(detail_text)
        self.workflow_hint_var.set(header_text)
        if self._sim_progress_win is not None and self._sim_progress_win.winfo_exists():
            self._sim_progress_win.deiconify()
            self._sim_progress_win.lift()
            self._sim_progress_win.update_idletasks()

    def _close_sim_progress_window(self):
        if self._sim_progress_win is not None and self._sim_progress_win.winfo_exists():
            self._sim_progress_win.destroy()
        self._sim_progress_win = None

    def _show_fit_result_dialog(self, res):
        beamer_txt = self._beamer_gaussian_text(res)
        psf_diag = res.get("psf_diagnostics") or {}
        fit_diag = res.get("fit_diagnostics") or {}
        warnings = res.get("warnings") or []
        diag_txt = ""
        if psf_diag or fit_diag:
            diag_txt = (
                "\n\nPSF / Fit Diagnostics\n"
                f"PSF integral: {float(psf_diag.get('psf_integral', float('nan'))):.6f}\n"
                f"Cumulative energy at r_max: {float(psf_diag.get('cumulative_energy_r_max', float('nan'))):.6f}\n"
                f"Total deposited energy in selected resist: {float(psf_diag.get('total_deposited_energy_keV', float('nan'))):.6g} keV\n"
                f"Nonzero radial bins: {int(psf_diag.get('nonzero_bin_count', 0))}/{int(psf_diag.get('radial_bin_count', 0))}\n"
                f"Excluded bins outside fit window: {int(res.get('fit_excluded_bin_count', 0))}\n"
                f"Unweighted MSE (log10 density): {float(fit_diag.get('fit_unweighted_mse_log10', float('nan'))):.6g}\n"
                f"Max |log10 residual|: {float(fit_diag.get('fit_max_abs_log10_residual', float('nan'))):.6g}"
            )
        transport = res.get("transport_diagnostics") or {}
        if transport:
            counts = transport.get("termination_counts", {})
            diag_txt += (
                "\n\nTransport energy accounting\n"
                f"Incident energy: {transport.get('incident_energy_keV', 0.0):.6g} keV\n"
                f"Deposited in all layers: {transport.get('deposited_energy_all_materials_keV', 0.0):.6g} keV\n"
                f"Selected-resist energy outside histogram: {transport.get('deposited_energy_selected_outside_radius_keV', 0.0):.6g} keV\n"
                f"Escaped energy: {transport.get('escaped_energy_keV', 0.0):.6g} keV\n"
                f"Residual at energy cutoff: {transport.get('residual_energy_at_cutoff_keV', 0.0):.6g} keV\n"
                f"Residual at collision/radial limits: {transport.get('residual_energy_max_collisions_keV', 0.0) + transport.get('residual_energy_radial_limit_keV', 0.0):.6g} keV\n"
                f"Energy balance error: {transport.get('energy_balance_error_keV', 0.0):.3g} keV\n"
                + "Trajectories: " + ", ".join(f"{key}={value}" for key, value in counts.items())
            )
        warning_txt = ""
        if warnings:
            warning_txt = "\n\nWarnings\n" + "\n".join(f"- {w}" for w in warnings)
        msg = (
            "PEC fit complete\n\n"
            f"Model: {self._fit_model_display_name(res)}\n"
            f"Source: {res['input_file']}\n"
            f"Layer: {res['layer_pattern']}\n"
            f"Collisions in layer: {res['layer_collision_count']}\n"
            f"{self._fit_forward_parameter_text(res)}\n"
            f"Beta (nm): {res['beta_nm']:.4f}\n"
            f"Eta (fit): {res['eta_fit']:.6f}\n"
            f"Eta (split): {res['eta_split']:.6f}\n"
            f"Forward split radius: {res['forward_range_nm']:.1f} nm\n"
            f"Fit window max radius: {res.get('fit_window_max_nm', float('nan')):.1f} nm\n"
            f"Fit points: {res.get('fit_point_count', 0)}\n"
            f"Fit weighting: {res.get('fit_weighting', '')}\n"
            f"Fit MSE (log10 density): {res['fit_mse']:.6g}\n"
            f"PEC guidance: {res.get('pec_guidance', '')}"
            f"{diag_txt}"
            f"{beamer_txt}"
            f"{warning_txt}"
        )
        self._show_text_dialog("PEC Fit Result", msg, width=720, height=420)

    def _beamer_gaussian_text(self, res):
        beamer = res.get("beamer_gaussian") or (res.get("fit_candidates") or {}).get("beamer_gaussian")
        dg = (res.get("fit_candidates") or {}).get("double_gaussian")
        if not beamer and not dg:
            return ""
        src = beamer or dg
        alpha_um = nm_to_um(src.get("alpha_nm", float("nan")))
        beta_um = nm_to_um(src.get("beta_nm", float("nan")))
        eta = float(src.get("eta_fit", float("nan")))
        gamma1_um = nm_to_um(src.get("gamma1_nm", 0.0) or 0.0)
        nue1 = float(src.get("nue1", 0.0) or 0.0)
        gamma2_um = nm_to_um(src.get("gamma2_nm", 0.0) or 0.0)
        nue2 = float(src.get("nue2", 0.0) or 0.0)
        try:
            fwhm_um = float(res.get("beamer_fwhm_um", 0.03))
        except Exception:
            fwhm_um = 0.03
        short_range_param_um = fwhm_um / GAUSSIAN_FWHM_FACTOR if fwhm_um > 0 else 0.0
        return (
            "\n\nBEAMER Gaussian Approximation (um)\n"
            f"Gaussian convention: {res.get('gaussian_convention', LEGACY_GAUSSIAN_CONVENTION)}\n"
            f"Alpha [um]: {alpha_um:.6f}\n"
            f"Beta [um]: {beta_um:.6f}\n"
            f"Eta: {eta:.6f}\n"
            f"Gamma1 [um]: {gamma1_um:.6f}\n"
            f"Nue1: {nue1:.6f}\n"
            f"Gamma2 [um]: {gamma2_um:.6f}\n"
            f"Nue2: {nue2:.6f}\n"
            f"Effective short-range blur FWHM [um]: {fwhm_um:.6f}\n"
            f"Equivalent short-range Gaussian parameter [um]: {short_range_param_um:.6f}\n"
            f"BEAMER Gaussian MSE: {float(src.get('mse', float('nan'))):.6g}\n"
            "Note: Alpha/Beta/Eta/Gamma1/Nue1 above are Gaussian-equivalent values for BEAMER. "
            "They are shown even when the selected physical fit is Power-Gaussian."
        )

    def _beamer_plot_annotation(self, res):
        beamer = res.get("beamer_gaussian") or (res.get("fit_candidates") or {}).get("beamer_gaussian")
        dg = (res.get("fit_candidates") or {}).get("double_gaussian")
        src = beamer or dg
        if not src:
            return ""
        try:
            fwhm_um = float(res.get("beamer_fwhm_um", 0.03))
        except Exception:
            fwhm_um = 0.03
        return (
            "BEAMER values (um)\n"
            f"Alpha={nm_to_um(src.get('alpha_nm', float('nan'))):.6f}\n"
            f"Beta={nm_to_um(src.get('beta_nm', float('nan'))):.6f}\n"
            f"Eta={float(src.get('eta_fit', float('nan'))):.6f}\n"
            f"Gamma1={nm_to_um(src.get('gamma1_nm', 0.0) or 0.0):.6f}\n"
            f"Nue1={float(src.get('nue1', 0.0) or 0.0):.6f}\n"
            f"FWHM={fwhm_um:.6f}"
        )

    def _fit_input_snapshot(self, fit_result):
        snapshot = fit_result.get("input_snapshot")
        if isinstance(snapshot, dict) and all(key in snapshot for key in ("beam", "materials", "stack")):
            return snapshot
        return None

    def _input_signature(self, snapshot):
        # Ignore display units and unused library entries. Round only the
        # comparison fingerprint to avoid repeated-normalization roundoff making
        # a newly loaded/canonicalized result appear stale.
        names = {layer["material_name"] for layer in snapshot["stack"]}
        beam = snapshot["beam"]
        values = {
            "beam": {key: beam.get(key) for key in ("energy_keV", "beam_diameter_nm", "current_pA")},
            "stack": snapshot["stack"],
            "materials": sorted((mat for mat in snapshot["materials"] if mat["name"] in names), key=lambda mat: mat["name"]),
        }
        def stable(value):
            if isinstance(value, float):
                return float(f"{value:.12g}")
            if isinstance(value, dict):
                return {key: stable(item) for key, item in value.items() if key not in ("alias", "notes")}
            if isinstance(value, list):
                return [stable(item) for item in value]
            return value
        return _stable_json_hash(stable(values))

    def _fit_state(self, fit_result):
        snapshot = self._fit_input_snapshot(fit_result)
        if snapshot is None:
            return "legacy_missing_snapshot"
        current = {"beam": self.project.get("beam", {}), "materials": self.materials, "stack": self.project.get("stack", [])}
        try:
            if all(hasattr(self, name) for name in ("energy_var", "diam_var", "current_var", "current_unit_var")):
                current["beam"] = self._beam_from_fields()
            current = _validated_inputs(current)
            return "current" if self._input_signature(snapshot) == self._input_signature(current) else "stale"
        except (ValueError, TypeError, KeyError):
            return "invalid_inputs"

    def _require_exportable_fit(self, fit_result):
        state = self._fit_state(fit_result)
        if state == "legacy_missing_snapshot":
            raise ValueError("This legacy result has no complete input snapshot. Run Simulation + Fit again before export.")
        if state != "current":
            raise ValueError("The inputs have changed or are invalid since this fit. Run Simulation + Fit again before export. The historical result remains available for inspection.")

    def _store_fit_result(self, res):
        fit_record = copy.deepcopy(res)
        snapshot = _validated_inputs(self.project)
        fit_record["input_snapshot"] = snapshot
        # Keep legacy keys as detached copies for readers of older JSON files.
        fit_record["beam"] = copy.deepcopy(snapshot["beam"])
        fit_record["stack_snapshot"] = copy.deepcopy(snapshot["stack"])
        fit_record["materials_snapshot"] = copy.deepcopy(snapshot["materials"])
        fits = self.project.setdefault("pec_fits", [])
        fits.append(fit_record)
        if len(fits) > 50:
            del fits[:-50]
        self.last_fit_result = copy.deepcopy(fit_record)
        return self.last_fit_result

    def _refresh_fit_info(self):
        fits = self.project.get("pec_fits", [])
        if not fits:
            self.fit_info_var.set("No PEC fit yet.")
            return
        last = fits[-1]
        state = self._fit_state(last)
        status = "" if state == "current" else f" [{state.replace('_', ' ')}; rerun before export]"
        forward_txt = self._fit_forward_parameter_text(last, short=True)
        self.fit_info_var.set(
            "Last PEC fit" + status + ": "
            f"{forward_txt}, "
            f"beta={last.get('beta_nm', float('nan')):.2f} nm, "
            f"eta={last.get('eta_fit', float('nan')):.4f}, "
            f"model={self._fit_model_display_name(last)}, "
            f"layer='{last.get('layer_pattern','')}'"
        )

    def _fit_double_gaussian_grid(
        self,
        x_nm,
        y_log10_density,
        fit_ring_area,
        fit_weights=None,
        beam_energy_keV=None,
        resist_thickness_nm=None,
    ):
        _ensure_numpy()
        x = np.asarray(x_nm, dtype=float)
        y = np.asarray(y_log10_density, dtype=float)
        ring_area = np.asarray(fit_ring_area, dtype=float)
        if len(x) != len(ring_area):
            raise ValueError("Fit window/ring area mismatch.")
        weights = np.ones_like(x) if fit_weights is None else np.asarray(fit_weights, dtype=float)
        if len(weights) != len(x):
            raise ValueError("Fit weights/window mismatch.")
        wsum = max(float(np.sum(weights)), 1e-300)

        beta_center_nm = _projected_backscatter_beta_nm(beam_energy_keV)
        alpha_hi = 180.0 if resist_thickness_nm is None else min(450.0, max(25.0, 0.9 * float(resist_thickness_nm)))
        beta_lo = max(200.0, beta_center_nm / 6.0)
        beta_hi = min(120000.0, max(6000.0, beta_center_nm * 3.8))

        def score_grid(alphas, betas, etas):
            best_local = None
            x2 = x * x
            for a in alphas:
                ea = _gaussian_ring_psf(x, ring_area, a)
                for b in betas:
                    if b <= a * 1.05:
                        continue
                    eb = _gaussian_ring_psf(x, ring_area, b)
                    et = etas[:, None]
                    pred_shape = (ea[None, :] + et * eb[None, :]) / (1.0 + et)
                    log_pred = np.log10(np.clip(pred_shape, 1e-300, None))
                    offsets = np.sum(weights[None, :] * (y[None, :] - log_pred), axis=1) / wsum
                    resid = log_pred + offsets[:, None] - y[None, :]
                    err = np.sum(weights[None, :] * (resid ** 2), axis=1) / wsum
                    j = int(np.argmin(err))
                    mse = float(err[j])
                    if best_local is None or mse < best_local["mse"]:
                        pred_best = pred_shape[j] * (10 ** offsets[j])
                        best_local = {
                            "mse": mse,
                            "fit_model": "double_gaussian",
                            "alpha_nm": float(a),
                            "beta_nm": float(b),
                            "eta_fit": float(etas[j]),
                            "plot_r_nm": x.tolist(),
                            "plot_measured_density": (10 ** y).tolist(),
                            "plot_fitted_density": pred_best.tolist(),
                        }
                        best_local["fit_representation"] = _fit_representation(
                            best_local, 10.0 ** offsets[j],
                        )
            return best_local

        coarse = score_grid(
            np.geomspace(2.0, alpha_hi, 32),
            np.geomspace(beta_lo, beta_hi, 48),
            np.geomspace(0.03, 8.0, 40),
        )
        a0, b0, e0 = coarse["alpha_nm"], coarse["beta_nm"], coarse["eta_fit"]
        refined = score_grid(
            np.geomspace(max(1.0, a0 / 3), a0 * 3, 36),
            np.geomspace(max(100.0, b0 / 4), min(140000.0, b0 * 4), 56),
            np.geomspace(max(1e-3, e0 / 5), e0 * 5, 50),
        )
        return min((coarse, refined), key=lambda candidate: candidate["mse"])

    def _fit_beamer_gaussian_grid(
        self,
        x_nm,
        y_log10_density,
        fit_ring_area,
        fit_weights=None,
        double_gaussian_seed=None,
    ):
        _ensure_numpy()
        x = np.asarray(x_nm, dtype=float)
        y = np.asarray(y_log10_density, dtype=float)
        ring_area = np.asarray(fit_ring_area, dtype=float)
        weights = np.ones_like(x) if fit_weights is None else np.asarray(fit_weights, dtype=float)
        if len(x) != len(ring_area) or len(x) != len(weights):
            raise ValueError("BEAMER fit window mismatch.")

        seed = double_gaussian_seed or {}
        seed_alpha = float(seed.get("alpha_nm", 10.0) or 10.0)
        seed_beta = float(seed.get("beta_nm", 5000.0) or 5000.0)
        seed_eta = float(seed.get("eta_fit", 1.0) or 1.0)
        seed_alpha = max(1.0, seed_alpha)
        seed_beta = max(seed_alpha * 3.0, seed_beta)

        full_x, full_y, full_weights = x.copy(), y.copy(), weights.copy()
        full_area = ring_area.copy()
        # Only search samples are thinned; analytic component normalization is global.
        # Final amplitude and diagnostics are always evaluated on the full input grid.
        if x.size > 650:
            idx = np.unique(np.round(np.geomspace(1, x.size - 1, 650)).astype(int))
            x = x[idx]
            y = y[idx]
            ring_area = ring_area[idx]
            weights = weights[idx]

        x2 = x * x
        weights = np.clip(weights, 1e-12, None)
        wsum = max(float(np.sum(weights)), 1e-300)

        def normalized_gaussian(width_nm):
            return _gaussian_ring_psf(x, ring_area, width_nm)

        def score_grid(alpha_grid, gamma_grid, beta_grid, eta_grid, nue_grid):
            best_local = None
            eta_vals = np.asarray(list(eta_grid), dtype=float)
            nue_vals = np.asarray(list(nue_grid), dtype=float)
            eta_mesh, nue_mesh = np.meshgrid(eta_vals, nue_vals, indexing="ij")
            eta_flat = eta_mesh.reshape(-1, 1)
            nue_flat = nue_mesh.reshape(-1, 1)
            denom = 1.0 + eta_flat + nue_flat
            for alpha_nm in alpha_grid:
                alpha_nm = float(alpha_nm)
                alpha_comp = normalized_gaussian(alpha_nm)
                for gamma_nm in gamma_grid:
                    gamma_nm = float(gamma_nm)
                    if gamma_nm <= alpha_nm * 1.15:
                        continue
                    gamma_comp = normalized_gaussian(gamma_nm)
                    for beta_nm in beta_grid:
                        beta_nm = float(beta_nm)
                        if beta_nm <= gamma_nm * 1.15:
                            continue
                        beta_comp = normalized_gaussian(beta_nm)
                        pred = (
                            alpha_comp[None, :]
                            + eta_flat * beta_comp[None, :]
                            + nue_flat * gamma_comp[None, :]
                        ) / denom
                        log_pred = np.log10(np.clip(pred, 1e-300, None))
                        offsets = np.sum(weights[None, :] * (y[None, :] - log_pred), axis=1) / wsum
                        resid = log_pred + offsets[:, None] - y[None, :]
                        errs = np.sum(weights[None, :] * (resid ** 2), axis=1) / wsum
                        j = int(np.argmin(errs))
                        err = float(errs[j])
                        if best_local is None or err < best_local["mse"]:
                            best_local = {
                                "alpha_nm": alpha_nm,
                                "beta_nm": beta_nm,
                                "eta_fit": float(eta_flat[j, 0]),
                                "gamma1_nm": gamma_nm,
                                "nue1": float(nue_flat[j, 0]),
                                "gamma2_nm": 0.0,
                                "nue2": 0.0,
                                "mse": err,
                            }
            return best_local

        gamma_lo = max(seed_alpha * 1.4, 15.0)
        gamma_hi = max(gamma_lo * 1.4, min(seed_beta / 1.25, max(120.0, seed_beta * 0.65)))
        coarse = score_grid(
            np.geomspace(max(1.0, seed_alpha / 2.8), seed_alpha * 2.4, 9),
            np.geomspace(gamma_lo, gamma_hi, 16),
            np.geomspace(max(gamma_lo * 1.3, seed_beta / 2.6), min(140000.0, seed_beta * 2.6), 11),
            np.geomspace(max(0.003, seed_eta / 8.0), max(8.0, seed_eta * 4.0), 16),
            np.geomspace(0.003, 3.0, 14),
        )
        if coarse is None:
            fallback = {
                "alpha_nm": seed_alpha,
                "beta_nm": seed_beta,
                "eta_fit": seed_eta,
                "gamma1_nm": max(seed_alpha * 4.0, 40.0),
                "nue1": 0.01,
                "gamma2_nm": 0.0,
                "nue2": 0.0,
                "mse": float(seed.get("mse", float("nan"))),
            }
            fallback["fit_representation"] = _fit_representation(fallback)
            return fallback

        refined = score_grid(
            np.geomspace(max(1.0, coarse["alpha_nm"] / 1.8), coarse["alpha_nm"] * 1.8, 11),
            np.geomspace(max(coarse["alpha_nm"] * 1.2, coarse["gamma1_nm"] / 2.0), coarse["gamma1_nm"] * 2.0, 18),
            np.geomspace(max(coarse["gamma1_nm"] * 1.2, coarse["beta_nm"] / 1.9), min(140000.0, coarse["beta_nm"] * 1.9), 13),
            np.geomspace(max(1e-4, coarse["eta_fit"] / 4.0), coarse["eta_fit"] * 4.0, 16),
            np.geomspace(max(1e-4, coarse["nue1"] / 4.0), coarse["nue1"] * 4.0, 14),
        )
        candidates = [candidate for candidate in (coarse, refined) if candidate is not None]
        for candidate in candidates:
            model = _fit_representation(candidate)
            log_shape = np.log10(np.clip(_evaluate_psf_ring_average(model, full_x, full_area), 1e-300, None))
            offset = float(np.sum(full_weights * (full_y - log_shape)) / np.sum(full_weights))
            model["amplitude"] = 10.0 ** offset
            candidate["search_mse"] = candidate["mse"]
            candidate["mse"] = float(np.sum(full_weights * (log_shape + offset - full_y) ** 2) / np.sum(full_weights))
            candidate["fit_representation"] = model
        return min(candidates, key=lambda candidate: candidate["mse"])

    def _beamer_gaussian_density(
        self, x_nm, ring_area, beamer_fit,
        target_y_log10_density=None, fit_weights=None,
    ):
        _ensure_numpy()
        model = beamer_fit.get("fit_representation")
        if model is None:
            raise ValueError("Legacy Gaussian fit has no global normalization metadata; rerun the fit.")
        # The fitted amplitude is part of the representation. Do not refit it when
        # evaluating another grid, otherwise a displayed curve differs from its fit.
        return _evaluate_psf_ring_average(model, x_nm, ring_area)

    def _fit_power_gaussian_grid(
        self,
        x_nm,
        y_log10_density,
        fit_ring_area,
        fit_weights=None,
        beam_energy_keV=None,
        resist_thickness_nm=None,
        beam_sigma_nm=None,
        resist_material_name=None,
    ):
        _ensure_numpy()
        x = np.asarray(x_nm, dtype=float)
        y = np.asarray(y_log10_density, dtype=float)
        ring_area = np.asarray(fit_ring_area, dtype=float)
        if len(x) != len(ring_area):
            raise ValueError("Fit window/ring area mismatch.")
        weights = np.ones_like(x) if fit_weights is None else np.asarray(fit_weights, dtype=float)
        if len(weights) != len(x):
            raise ValueError("Fit weights/window mismatch.")
        wsum = max(float(np.sum(weights)), 1e-300)

        beam_floor_nm = max(1.0, 0.5 * float(beam_sigma_nm or 0.0))
        beta_center_nm = _projected_backscatter_beta_nm(beam_energy_keV)
        beta_lo = max(200.0, beta_center_nm / 5.0)
        beta_hi = min(140000.0, max(8000.0, beta_center_nm * 3.5))
        high_energy_thin = _is_high_tension_thin_resist(beam_energy_keV, resist_thickness_nm)

        def score_grid(alpha_powers, betas, etas):
            best_local = None
            for aexp in alpha_powers:
                pow_comp = _power_ring_psf(x, ring_area, aexp, beam_floor_nm)
                for b in betas:
                    gauss_comp = _gaussian_ring_psf(x, ring_area, b)
                    et = etas[:, None]
                    pred_shape = (pow_comp[None, :] + et * gauss_comp[None, :]) / (1.0 + et)
                    log_pred = np.log10(np.clip(pred_shape, 1e-300, None))
                    offsets = np.sum(weights[None, :] * (y[None, :] - log_pred), axis=1) / wsum
                    resid = log_pred + offsets[:, None] - y[None, :]
                    err = np.sum(weights[None, :] * (resid ** 2), axis=1) / wsum
                    j = int(np.argmin(err))
                    mse = float(err[j])
                    if best_local is None or mse < best_local["mse"]:
                        pred_best = pred_shape[j] * (10 ** offsets[j])
                        best_local = {
                            "mse": mse,
                            "fit_model": "power_gaussian",
                            "alpha_power": float(aexp),
                            "beta_nm": float(b),
                            "eta_fit": float(etas[j]),
                            "plot_r_nm": x.tolist(),
                            "plot_measured_density": (10 ** y).tolist(),
                            "plot_fitted_density": pred_best.tolist(),
                        }
                        best_local["fit_representation"] = _fit_representation(
                            best_local, 10.0 ** offsets[j],
                            core_radius_nm=beam_floor_nm,
                        )
            return best_local

        if high_energy_thin:
            alpha_range = np.geomspace(2.01, 3.2, 26)
        else:
            alpha_range = np.geomspace(2.01, 3.0, 24)

        coarse = score_grid(
            alpha_range,
            np.geomspace(beta_lo, beta_hi, 40),
            np.geomspace(0.02, 6.0, 28),
        )
        a0, b0, e0 = coarse["alpha_power"], coarse["beta_nm"], coarse["eta_fit"]
        refined = score_grid(
            np.geomspace(max(2.01, a0 / 1.35), min(4.0, a0 * 1.35), 28),
            np.geomspace(max(150.0, b0 / 3.0), min(160000.0, b0 * 3.0), 48),
            np.geomspace(max(1e-3, e0 / 4.0), e0 * 4.0, 36),
        )
        return min((coarse, refined), key=lambda candidate: candidate["mse"])

    def plot_last_fit(self):
        if not self.last_fit_result:
            fits = self.project.get("pec_fits", [])
            if not fits:
                messagebox.showinfo("Plot PEC Fit", "No PEC fit available yet.")
                return
            self.last_fit_result = copy.deepcopy(fits[-1])

        res = self.last_fit_result
        plot_data = res.get("plot_data")
        if not plot_data:
            messagebox.showerror("Plot PEC Fit", "No plot data stored in the last fit result.")
            return

        _ensure_numpy()
        r = np.asarray(plot_data.get("r_nm", []), dtype=float)
        y_meas = np.asarray(plot_data.get("measured_density", []), dtype=float)
        y_fit = np.asarray(plot_data.get("fitted_density", []), dtype=float)
        y_beamer = np.asarray(plot_data.get("beamer_gaussian_density", []), dtype=float)
        if r.size == 0 or y_meas.size == 0 or y_fit.size == 0:
            messagebox.showerror("Plot PEC Fit", "Stored plot data is empty.")
            return
        if y_beamer.size != r.size:
            y_beamer = np.asarray([], dtype=float)

        if res.get("fit_model") == "power_gaussian":
            title = (
                f"PEC Fit ({self._fit_model_display_name(res)}): αp={res.get('alpha_power', float('nan')):.3f}, "
                f"β={res.get('beta_nm', float('nan')):.2f} nm, η={res.get('eta_fit', float('nan')):.4f}"
            )
        else:
            title = (
                f"PEC Fit ({self._fit_model_display_name(res)}): α={res.get('alpha_nm', float('nan')):.2f} nm, "
                f"β={res.get('beta_nm', float('nan')):.2f} nm, η={res.get('eta_fit', float('nan')):.4f}"
            )

        state = self._fit_state(res)
        if state != "current":
            title += f" [historical result: {state.replace('_', ' ')}]"
        mpl = _ensure_matplotlib_pyplot()
        fit_label = f"{self._fit_model_display_name(res)} fit"
        beamer_annotation = self._beamer_plot_annotation(res)
        if mpl is not None:
            fig = mpl.figure(figsize=(8.5, 5.6))
            ax = fig.add_subplot(111)
            ax.loglog(r, y_meas, '.', markersize=3, label='Measured (simulation histogram)')
            ax.loglog(r, y_fit, '-', linewidth=1.5, label=fit_label)
            if y_beamer.size:
                ax.loglog(
                    r,
                    y_beamer,
                    '--',
                    linewidth=1.35,
                    color='tab:green',
                    label='BEAMER Gaussian approximation',
                )
            ax.set_xlabel('Radius (nm)')
            ax.set_ylabel('Deposited energy density (normalized, 1/nm^2)')
            ax.set_title(title)
            ax.grid(True, which='both', alpha=0.25)
            ax.legend()
            if beamer_annotation:
                ax.text(
                    0.985,
                    0.04,
                    beamer_annotation,
                    transform=ax.transAxes,
                    ha="right",
                    va="bottom",
                    fontsize=8.5,
                    family="monospace",
                    bbox={
                        "boxstyle": "round,pad=0.35",
                        "facecolor": "white",
                        "edgecolor": "#666666",
                        "alpha": 0.88,
                    },
                )
            fig.tight_layout()
            mpl.show()
            return

        self._plot_last_fit_tk(r, y_meas, y_fit, title, beamer_annotation, y_beamer)

    def _plot_last_fit_tk(self, r, y_meas, y_fit, title, beamer_annotation="", y_beamer=None):
        win = tk.Toplevel(self.root)
        win.title("PEC Fit Plot (Tk fallback)")
        _configure_toplevel(win, self.root, width=900, height=650, min_width=520, min_height=360)

        outer = ttk.Frame(win, padding=8)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=title).pack(anchor="w", pady=(0, 6))

        canvas = tk.Canvas(outer, bg="white", highlightthickness=1, highlightbackground="#999")
        canvas.pack(fill="both", expand=True)

        info_text = "Matplotlib not found, using built-in plot. Axes are log-log."
        if beamer_annotation:
            info_text += "\n\n" + beamer_annotation
        info = ttk.Label(outer, text=info_text, justify="left")
        info.pack(anchor="w", pady=(6, 0))

        def draw(_event=None):
            canvas.delete("all")
            w = max(canvas.winfo_width(), 200)
            h = max(canvas.winfo_height(), 200)
            left, right, top, bottom = 70, 20, 20, 50
            pw, ph = w - left - right, h - top - bottom
            if pw <= 20 or ph <= 20:
                return

            m1 = (r > 0) & (y_meas > 0)
            m2 = (r > 0) & (y_fit > 0)
            yb = np.asarray([] if y_beamer is None else y_beamer, dtype=float)
            mb = (r > 0) & (yb > 0) if yb.size == r.size else np.zeros_like(r, dtype=bool)
            if not np.any(m1) or not np.any(m2):
                return
            x_all = np.concatenate([r[m1], r[m2], r[mb]]) if np.any(mb) else np.concatenate([r[m1], r[m2]])
            y_all = np.concatenate([y_meas[m1], y_fit[m2], yb[mb]]) if np.any(mb) else np.concatenate([y_meas[m1], y_fit[m2]])
            lx0, lx1 = np.log10(np.min(x_all)), np.log10(np.max(x_all))
            ly0, ly1 = np.log10(np.min(y_all)), np.log10(np.max(y_all))
            if lx1 <= lx0 or ly1 <= ly0:
                return

            def xmap(xv):
                return left + (np.log10(xv) - lx0) / (lx1 - lx0) * pw

            def ymap(yv):
                return top + (ly1 - np.log10(yv)) / (ly1 - ly0) * ph

            canvas.create_rectangle(left, top, left + pw, top + ph, outline="#333")

            # Major decade grid
            for d in range(int(math.floor(lx0)), int(math.ceil(lx1)) + 1):
                xv = 10 ** d
                if xv < x_all.min() or xv > x_all.max():
                    continue
                xpix = float(xmap(xv))
                canvas.create_line(xpix, top, xpix, top + ph, fill="#ddd")
                canvas.create_text(xpix, top + ph + 15, text=f"1e{d}", font=("Helvetica", 9))
            for d in range(int(math.floor(ly0)), int(math.ceil(ly1)) + 1):
                yv = 10 ** d
                if yv < y_all.min() or yv > y_all.max():
                    continue
                ypix = float(ymap(yv))
                canvas.create_line(left, ypix, left + pw, ypix, fill="#ddd")
                canvas.create_text(left - 35, ypix, text=f"1e{d}", font=("Helvetica", 9))

            # Measured points
            rr = r[m1]
            yy = y_meas[m1]
            for xv, yv in zip(rr[::max(1, len(rr)//1500)], yy[::max(1, len(yy)//1500)]):
                xp, yp = float(xmap(xv)), float(ymap(yv))
                canvas.create_oval(xp - 1, yp - 1, xp + 1, yp + 1, fill="#1f77b4", outline="")

            # Fitted line
            rr2 = r[m2]
            yy2 = y_fit[m2]
            coords = []
            step = max(1, len(rr2) // 1500)
            for xv, yv in zip(rr2[::step], yy2[::step]):
                coords.extend([float(xmap(xv)), float(ymap(yv))])
            if len(coords) >= 4:
                canvas.create_line(*coords, fill="#d62728", width=2, smooth=False)

            # BEAMER Gaussian approximation line
            if np.any(mb):
                rrb = r[mb]
                yyb = yb[mb]
                coords = []
                step = max(1, len(rrb) // 1500)
                for xv, yv in zip(rrb[::step], yyb[::step]):
                    coords.extend([float(xmap(xv)), float(ymap(yv))])
                if len(coords) >= 4:
                    canvas.create_line(*coords, fill="#2ca02c", width=2, dash=(7, 4), smooth=False)

            # Legend
            lx = left + 10
            ly = top + 10
            legend_h = 58 if np.any(mb) else 40
            canvas.create_rectangle(lx, ly, lx + 230, ly + legend_h, fill="white", outline="#bbb")
            canvas.create_oval(lx + 8, ly + 9, lx + 12, ly + 13, fill="#1f77b4", outline="")
            canvas.create_text(lx + 20, ly + 11, text="Measured (histogram)", anchor="w", font=("Helvetica", 9))
            canvas.create_line(lx + 8, ly + 28, lx + 18, ly + 28, fill="#d62728", width=2)
            canvas.create_text(lx + 20, ly + 28, text=fit_label, anchor="w", font=("Helvetica", 9))
            if np.any(mb):
                canvas.create_line(lx + 8, ly + 45, lx + 18, ly + 45, fill="#2ca02c", width=2, dash=(7, 4))
                canvas.create_text(lx + 20, ly + 45, text="BEAMER Gaussian", anchor="w", font=("Helvetica", 9))

            canvas.create_text(left + pw / 2, h - 15, text="Radius (nm) [log scale]", font=("Helvetica", 10))
            canvas.create_text(15, top + ph / 2, text="Density\n(log)", font=("Helvetica", 10))

        canvas.bind("<Configure>", draw)
        draw()


def main():
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    app = StackDesignerApp(root)
    root.geometry("1100x800")
    root.minsize(900, 650)
    root.resizable(True, True)
    root.mainloop()


if __name__ == "__main__":
    main()

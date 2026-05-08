import json
import math
import time
import random
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
np = None
plt = None


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


def _norm(vals):
    s = float(sum(vals))
    if s <= 0:
        return list(vals)
    return [float(v) / s for v in vals]


def _mat(name, alias, density, elements, notes=""):
    # elements: list of tuples (symbol, Z, weight_fraction, atomic_fraction)
    wf = _norm([e[2] for e in elements])
    af = _norm([e[3] for e in elements])
    out_elems = []
    for i, e in enumerate(elements):
        out_elems.append({
            "symbol": e[0],
            "Z": int(e[1]),
            "weight_fraction": wf[i],
            "atomic_fraction": af[i],
        })
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


ATOMIC_WEIGHTS = {
    "H": 1.008, "B": 10.81, "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974, "S": 32.06,
    "Cl": 35.45, "K": 39.098, "Ca": 40.078, "Ti": 47.867, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38, "Ga": 69.723,
    "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904, "Rb": 85.468, "Sr": 87.62,
    "Y": 88.906, "Zr": 91.224, "Nb": 92.906, "Mo": 95.95, "In": 114.818, "Sn": 118.710,
    "Sb": 121.760, "Te": 127.60, "I": 126.904, "Cs": 132.905, "Ba": 137.327, "Hf": 178.49,
    "Ta": 180.948, "W": 183.84, "Pt": 195.084, "Au": 196.967, "Hg": 200.592, "Pb": 207.2,
}
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
    return ATOMIC_WEIGHTS.get(symbol, max(1.0, 2.0 * float(z)))


def _material_mc_properties(material):
    elements = material.get("elements", [])
    rho = float(material.get("density_g_cm3", 1.0) or 1.0)
    if not elements:
        j0 = _mean_ionization_energy_keV(6)
        return {
            "rho": rho, "zeff_af": 10.0, "z_back": 10.0, "a_eff": 20.0,
            "scatter_strength": rho, "stop_strength": rho,
            "mean_I_eV": 75.0, "ko_range_coeff_nm": 2500.0,
            "bragg_wZ": [(6.0, 12.011, 1.0, j0)],
        }
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
        ttk.Entry(self.frame, width=12, textvariable=self.af_var).grid(row=0, column=3, padx=2, pady=2)
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
        ttk.Label(cols, text="Atomic frac").grid(row=0, column=3, padx=2)

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
            w = [safe_float(r.wf_var.get(), 0.0) for r in self.element_rows]
            a = [safe_float(r.af_var.get(), 0.0) for r in self.element_rows]
            sw = sum(w)
            sa = sum(a)
            if sw > 0:
                for r, v in zip(self.element_rows, w):
                    r.wf_var.set(f"{v / sw:.6f}")
            if sa > 0:
                for r, v in zip(self.element_rows, a):
                    r.af_var.set(f"{v / sa:.6f}")
        except Exception as exc:
            messagebox.showerror("Normalize Error", str(exc), parent=self)

    def save(self):
        try:
            name = self.name_var.get().strip()
            if not name:
                raise ValueError("Material name is required.")
            density = safe_float(self.density_var.get())
            if density is None or density <= 0:
                raise ValueError("Density must be > 0.")

            elements = [r.to_dict() for r in self.element_rows]
            if not elements:
                raise ValueError("At least one element is required.")

            wf_sum = sum(e["weight_fraction"] for e in elements)
            af_sum = sum(e["atomic_fraction"] for e in elements)
            if abs(wf_sum - 1.0) > 0.02:
                raise ValueError(f"Weight fractions must sum to ~1.0 (current {wf_sum:.4f}).")
            if abs(af_sum - 1.0) > 0.02:
                raise ValueError(f"Atomic fractions must sum to ~1.0 (current {af_sum:.4f}).")

            self.result = {
                "name": name,
                "alias": self.alias_var.get().strip(),
                "density_g_cm3": density,
                "notes": self.notes_var.get().strip(),
                "elements": elements,
            }
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
        self.refresh_all()
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
            old_name = self.materials[idx]["name"]
            self.materials[idx] = dlg.result
            new_name = dlg.result["name"]
            for layer in self.project.get("stack", []):
                if layer.get("material_name") == old_name:
                    layer["material_name"] = new_name
            self.refresh_all()

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
                t = safe_float(thick_var.get())
                if t is None or t < 0:
                    raise ValueError("Thickness must be >= 0 nm.")
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

    def collect_project(self):
        current_value = safe_float(self.current_var.get(), None)
        current_unit = str(self.current_unit_var.get() or "pA")
        if current_unit not in ("pA", "nA"):
            current_unit = "pA"
        self.project["project_name"] = self.project_name_var.get().strip() or "Untitled"
        self.project["beam"] = {
            "energy_keV": safe_float(self.energy_var.get()),
            "beam_diameter_nm": safe_float(self.diam_var.get(), None),
            "current_pA": None if current_value is None else self._convert_current_value(current_value, current_unit, "pA"),
            "current_input_unit": current_unit,
        }
        if self.project["beam"]["energy_keV"] is None or self.project["beam"]["energy_keV"] <= 0:
            raise ValueError("Electron energy (keV) must be > 0.")
        self.project["materials"] = self.materials
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
            if "materials" not in data or "stack" not in data or "beam" not in data:
                raise ValueError("Invalid project file.")
            self.project = data
            self.project_path = path
            self.refresh_all()
            messagebox.showinfo("Loaded", f"Loaded project:\n{path}")
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

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
                lines.append("Last PEC fit result")
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
                lines.append(f"PEC guidance: {self.last_fit_result.get('pec_guidance', '')}")
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
                    "seed": int(float(vars_["seed"].get())),
                    "max_collisions_per_electron": int(float(vars_["max_collisions_per_electron"].get())),
                    "min_energy_keV": float(vars_["min_energy_keV"].get()),
                }
                if params["electrons"] <= 0:
                    raise ValueError("Electrons must be > 0.")
                if params["max_radius_nm"] < 1000:
                    raise ValueError("Max radius must be >= 1000 nm.")
                if params["forward_nm"] <= 0:
                    raise ValueError("Forward split radius must be > 0.")
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
            res["simulation"] = {
                "engine": "standalone_mc_rutherford_bethe_like",
                "electrons": params["electrons"],
                "seed": params["seed"],
                "elapsed_s": time.time() - t0,
                "max_collisions_per_electron": params["max_collisions_per_electron"],
                "min_energy_keV": params["min_energy_keV"],
                "beam_energy_keV": self.project.get("beam", {}).get("energy_keV"),
                "resist_layer_index": params["resist_layer_index"],
                "resist_layer_indices": params.get("resist_layer_indices", [params["resist_layer_index"]]),
                "collision_count_in_resist": sim["collision_count_in_resist"],
                "segments_in_resist": sim["segments_in_resist"],
            }
            self.last_fit_result = res
            self._store_fit_result(res)
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
        rng = random.Random(int(params["seed"]))
        stack = self.project.get("stack", [])
        if not stack:
            raise ValueError("Stack is empty.")

        # Build layer geometry and MC properties.
        layers = []
        z = 0.0
        for i, layer in enumerate(stack):
            t = float(layer.get("thickness_nm", 0) or 0.0)
            if t < 0:
                raise ValueError(f"Negative thickness in layer {i+1}.")
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
        if total_stack_nm <= 0:
            raise ValueError("Total stack thickness must be > 0.")

        resist_indices_raw = params.get("resist_layer_indices")
        if resist_indices_raw is None:
            resist_indices = [int(params["resist_layer_index"])]
        else:
            resist_indices = [int(i) for i in resist_indices_raw]
        if not resist_indices:
            raise ValueError("No resist layer selected.")
        for resist_idx in resist_indices:
            if resist_idx < 0 or resist_idx >= len(layers):
                raise ValueError("Invalid resist layer index.")
        resist_layers = [layers[i] for i in resist_indices]
        launch_props = resist_layers[0]["props"]
        resist_intervals = [(L["z0"], L["z1"]) for L in resist_layers]
        resist_thickness_nm = sum(float(L["thickness_nm"]) for L in resist_layers)
        resist_layer_name = " + ".join(L["name"] for L in resist_layers)

        # Keep thin membrane-style substrates finite, but treat clearly bulk substrates as semi-infinite.
        if (
            layers
            and str(layers[-1].get("role", "")).lower() == "substrate"
            and float(layers[-1].get("thickness_nm", 0.0) or 0.0) >= 50000.0
        ):
            layers[-1]["z1"] = float("inf")

        max_radius_nm = max(int(params["max_radius_nm"]), 1000)
        rvals = np.arange(1, max_radius_nm + 1, dtype=float)
        evals = np.zeros_like(rvals)

        beam = self.project.get("beam", {})
        E0 = float(beam.get("energy_keV") or 0.0)
        if E0 <= 0:
            raise ValueError("Beam energy (keV) must be set and > 0.")
        beam_diam_nm = float(beam.get("beam_diameter_nm") or 0.0)
        beam_sigma_nm = max(0.0, beam_diam_nm / 2.355) if beam_diam_nm else 0.0

        ne = int(params["electrons"])
        min_energy_keV = float(params["min_energy_keV"])
        max_coll = int(params["max_collisions_per_electron"])
        if max_coll <= 0:
            max_coll = 1000

        collision_count_in_resist = 0
        segments_in_resist = 0
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
            if not any(zmid >= z0 and zmid < z1 for z0, z1 in resist_intervals):
                return
            if dE > 0:
                lateral_len = math.hypot(x1 - x0, y1 - y0)
                sub_segments = min(8, max(1, int(lateral_len / 15.0)))
                share = dE / sub_segments
                for j in range(sub_segments):
                    frac = (j + 0.5) / sub_segments
                    rx = x0 + (x1 - x0) * frac
                    ry = y0 + (y1 - y0) * frac
                    idx = int(round(math.hypot(rx, ry) / dr))
                    if 0 <= idx < len(evals):
                        evals[idx] += share
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

            for _ in range(max_coll):
                if E <= min_energy_keV:
                    break
                li = layer_at_z(zpos)
                if li is None:
                    # If escaped above surface or beyond finite stack, stop.
                    break
                L = layers[li]
                P = L["props"]
                role = str(L.get("role", "")).lower()

                # Screened Rutherford-like elastic transport with a Kanaya-Okayama range scale.
                mfp_nm = _elastic_mean_free_path_nm(E, P)
                if role == "resist":
                    mfp_nm *= 0.55
                elif role in ("substrate", "metal", "adhesion"):
                    mfp_nm *= 0.82
                remaining_step = -mfp_nm * math.log(max(1e-12, 1.0 - rng.random()))

                while remaining_step > 1e-9:
                    role = str(L.get("role", "")).lower()
                    ux, uy, uz = direction
                    # Distance to current layer boundary along z.
                    if uz > 1e-12:
                        boundary_z = L["z1"]
                        dist_to_boundary = (boundary_z - zpos) / uz
                    elif uz < -1e-12:
                        boundary_z = L["z0"]
                        dist_to_boundary = (boundary_z - zpos) / uz
                    else:
                        dist_to_boundary = float("inf")
                    if dist_to_boundary <= 1e-9:
                        dist_to_boundary = float("inf")

                    step = remaining_step if remaining_step <= dist_to_boundary else dist_to_boundary
                    x0, y0, z0 = x, y, zpos
                    x += ux * step
                    y += uy * step
                    zpos += uz * step

                    # Bethe-inspired continuous slowing-down with a mild substrate/interface boost.
                    stop_coeff = _bethe_stopping_keV_per_nm(E, P)
                    if role == "resist":
                        stop_coeff *= 1.08
                    elif role in ("substrate", "metal", "adhesion"):
                        z_ratio = P["zeff_af"] / max(launch_props["zeff_af"], 1.0)
                        if z_ratio > 1.0:
                            stop_coeff *= 1.0 + 0.08 * min(3.0, z_ratio - 1.0)
                    dE = min(E - min_energy_keV, max(0.0, stop_coeff * step * (0.92 + 0.16 * rng.random())))
                    if dE < 0:
                        dE = 0.0
                    E -= dE
                    zmid = 0.5 * (z0 + zpos)
                    deposit_in_resist(x0, y0, x, y, zmid, dE, collision_flag=False)

                    remaining_step -= step

                    # Boundary crossing (no scattering event yet).
                    if step == dist_to_boundary:
                        # Move slightly inside next layer to avoid sticking on boundary.
                        if uz > 0:
                            zpos += 1e-6
                        elif uz < 0:
                            zpos -= 1e-6
                        if zpos < -1.0:  # escaped upward
                            remaining_step = 0.0
                            break
                        next_li = layer_at_z(zpos)
                        if next_li is None:
                            remaining_step = 0.0
                            break
                        li = next_li
                        L = layers[li]
                        P = L["props"]
                        continue

                    # Collision occurs at end of remaining path segment.
                    deposit_in_resist(x0, y0, x, y, zpos, 0.0, collision_flag=True)

                    z_ratio = P["zeff_af"] / max(launch_props["zeff_af"], 1.0)
                    theta = _screened_rutherford_theta(P["zeff_af"] * max(1.0, z_ratio ** 0.2), E, rng)
                    if role in ("substrate", "metal", "adhesion"):
                        theta = min(math.pi * 0.97, theta * 1.08)
                    phi = 2.0 * math.pi * rng.random()
                    direction = _scatter_direction(direction, theta, phi)
                    remaining_step = 0.0

                if E <= min_energy_keV:
                    break
                if zpos < 0 and direction[2] < 0:
                    break
                # Hard radial cutoff to keep runtime bounded in extreme cases.
                if (x * x + y * y) ** 0.5 > max_radius_nm * 4:
                    break

            done = ie + 1
            if done % update_every == 0 or ie == ne - 1:
                elapsed_s = time.time() - progress_t0
                rate = done / elapsed_s if elapsed_s > 1e-9 else 0.0
                eta_s = (ne - done) / rate if rate > 1e-9 else float("nan")
                frac = done / ne if ne > 0 else 0.0
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
        }

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
        ring_area = np.pi * rvals**2 - np.concatenate(([0.0], np.pi * rvals[:-1]**2))
        ed = ev / ring_area
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

        prefer_pg = _is_high_tension_thin_resist(beam_energy_keV, resist_thickness_nm)
        if prefer_pg:
            best = best_pg if best_pg["mse"] <= best_dg["mse"] * 1.10 else best_dg
        else:
            best = best_pg if best_pg["mse"] < best_dg["mse"] * 0.90 else best_dg

        dr = 1.0
        fwd_idx = int(max(1, min(len(ev) - 2, round(float(forward_nm) / dr))))
        fwd = float(ev[1:fwd_idx + 1].sum())
        back = float(ev[fwd_idx + 1:].sum())
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
            "plot_data": {
                "r_nm": best["plot_r_nm"],
                "measured_density": best["plot_measured_density"],
                "fitted_density": best["plot_fitted_density"],
            },
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
            "fit_weighting": fit_window["weighting_description"],
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
            f"{beamer_txt}"
        )
        self._show_text_dialog("PEC Fit Result", msg, width=720, height=420)

    def _beamer_gaussian_text(self, res):
        beamer = res.get("beamer_gaussian") or (res.get("fit_candidates") or {}).get("beamer_gaussian")
        dg = (res.get("fit_candidates") or {}).get("double_gaussian")
        if not beamer and not dg:
            return ""
        src = beamer or dg
        alpha_um = float(src.get("alpha_nm", float("nan"))) / 1000.0
        beta_um = float(src.get("beta_nm", float("nan"))) / 1000.0
        eta = float(src.get("eta_fit", float("nan")))
        gamma1_um = float(src.get("gamma1_nm", 0.0) or 0.0) / 1000.0
        nue1 = float(src.get("nue1", 0.0) or 0.0)
        gamma2_um = float(src.get("gamma2_nm", 0.0) or 0.0) / 1000.0
        nue2 = float(src.get("nue2", 0.0) or 0.0)
        fwhm_um = 0.03
        beam = self.project.get("beam", {})
        try:
            beam_diam_nm = float(beam.get("beam_diameter_nm") or 0.0)
            if beam_diam_nm > 0:
                fwhm_um = beam_diam_nm / 1000.0
        except Exception:
            pass
        return (
            "\n\nBEAMER Gaussian Approximation (um)\n"
            f"Alpha [um]: {alpha_um:.6f}\n"
            f"Beta [um]: {beta_um:.6f}\n"
            f"Eta: {eta:.6f}\n"
            f"Gamma1 [um]: {gamma1_um:.6f}\n"
            f"Nue1: {nue1:.6f}\n"
            f"Gamma2 [um]: {gamma2_um:.6f}\n"
            f"Nue2: {nue2:.6f}\n"
            f"Effective short-range blur FWHM [um]: {fwhm_um:.6f}\n"
            f"BEAMER Gaussian MSE: {float(src.get('mse', float('nan'))):.6g}\n"
            "Note: Alpha/Beta/Eta/Gamma1/Nue1 above are Gaussian-equivalent values for BEAMER. "
            "They are shown even when the selected physical fit is Power-Gaussian."
        )

    def _store_fit_result(self, res):
        fit_record = dict(res)
        fit_record["beam"] = dict(self.project.get("beam", {}))
        fit_record["stack_snapshot"] = [dict(layer) for layer in self.project.get("stack", [])]
        fits = self.project.setdefault("pec_fits", [])
        fits.append(fit_record)
        if len(fits) > 50:
            del fits[:-50]

    def _refresh_fit_info(self):
        fits = self.project.get("pec_fits", [])
        if not fits:
            self.fit_info_var.set("No PEC fit yet.")
            return
        last = fits[-1]
        forward_txt = self._fit_forward_parameter_text(last, short=True)
        self.fit_info_var.set(
            "Last PEC fit: "
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
                ea = np.exp(-x2 / (a * a))
                ea /= max(float(np.sum(ea * ring_area)), 1e-300)
                for b in betas:
                    if b <= a * 1.05:
                        continue
                    eb = np.exp(-x2 / (b * b))
                    eb /= max(float(np.sum(eb * ring_area)), 1e-300)
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
        return refined

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

        # Downsample for a fast BEAMER-oriented fit while keeping log-spaced radius coverage.
        if x.size > 850:
            idx = np.unique(np.round(np.geomspace(1, x.size - 1, 850)).astype(int))
            x = x[idx]
            y = y[idx]
            ring_area = ring_area[idx]
            weights = weights[idx]

        density = 10.0 ** y
        x2 = x * x
        sqrt_w = np.sqrt(np.clip(weights, 1e-12, None))
        weighted_target = sqrt_w * density

        def normalized_gaussian(width_nm):
            comp = np.exp(-x2 / max(float(width_nm) ** 2, 1e-24))
            comp /= max(float(np.sum(comp * ring_area)), 1e-300)
            return comp

        def score_grid(alpha_grid, gamma_grid, beta_grid):
            best_local = None
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
                        model = np.vstack((alpha_comp, beta_comp, gamma_comp)).T
                        weighted_model = model * sqrt_w[:, None]
                        try:
                            coeffs = np.linalg.lstsq(weighted_model, weighted_target, rcond=None)[0]
                        except Exception:
                            continue
                        if not np.all(np.isfinite(coeffs)):
                            continue
                        if coeffs[0] <= 0.0 or coeffs[1] <= 0.0 or coeffs[2] <= 0.0:
                            continue
                        pred = model @ coeffs
                        log_pred = np.log10(np.clip(pred, 1e-300, None))
                        err = float(np.sum(weights * (log_pred - y) ** 2) / max(float(np.sum(weights)), 1e-300))
                        if best_local is None or err < best_local["mse"]:
                            best_local = {
                                "alpha_nm": alpha_nm,
                                "beta_nm": beta_nm,
                                "eta_fit": float(coeffs[1] / coeffs[0]),
                                "gamma1_nm": gamma_nm,
                                "nue1": float(coeffs[2] / coeffs[0]),
                                "gamma2_nm": 0.0,
                                "nue2": 0.0,
                                "mse": err,
                            }
            return best_local

        gamma_lo = max(seed_alpha * 1.4, 15.0)
        gamma_hi = max(gamma_lo * 1.4, min(seed_beta / 1.25, max(120.0, seed_beta * 0.65)))
        coarse = score_grid(
            np.geomspace(max(1.0, seed_alpha / 2.5), seed_alpha * 2.5, 13),
            np.geomspace(gamma_lo, gamma_hi, 24),
            np.geomspace(max(gamma_lo * 1.3, seed_beta / 2.4), min(140000.0, seed_beta * 2.4), 18),
        )
        if coarse is None:
            return {
                "alpha_nm": seed_alpha,
                "beta_nm": seed_beta,
                "eta_fit": seed_eta,
                "gamma1_nm": 0.0,
                "nue1": 0.0,
                "gamma2_nm": 0.0,
                "nue2": 0.0,
                "mse": float(seed.get("mse", float("nan"))),
            }

        refined = score_grid(
            np.geomspace(max(1.0, coarse["alpha_nm"] / 1.8), coarse["alpha_nm"] * 1.8, 15),
            np.geomspace(max(coarse["alpha_nm"] * 1.2, coarse["gamma1_nm"] / 2.0), coarse["gamma1_nm"] * 2.0, 24),
            np.geomspace(max(coarse["gamma1_nm"] * 1.2, coarse["beta_nm"] / 1.9), min(140000.0, coarse["beta_nm"] * 1.9), 20),
        )
        return refined or coarse

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

        x2 = x * x
        beam_floor_nm = max(1.0, 0.5 * float(beam_sigma_nm or 0.0))
        xeff = np.sqrt(x2 + beam_floor_nm * beam_floor_nm)
        beta_center_nm = _projected_backscatter_beta_nm(beam_energy_keV)
        beta_lo = max(200.0, beta_center_nm / 5.0)
        beta_hi = min(140000.0, max(8000.0, beta_center_nm * 3.5))
        high_energy_thin = _is_high_tension_thin_resist(beam_energy_keV, resist_thickness_nm)

        def score_grid(alpha_powers, betas, etas):
            best_local = None
            for aexp in alpha_powers:
                pow_comp = xeff ** (-aexp)
                pow_comp /= max(float(np.sum(pow_comp * ring_area)), 1e-300)
                for b in betas:
                    gauss_comp = np.exp(-x2 / (b * b))
                    gauss_comp /= max(float(np.sum(gauss_comp * ring_area)), 1e-300)
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
            return best_local

        if high_energy_thin:
            alpha_range = np.geomspace(1.8, 3.2, 26)
        else:
            alpha_range = np.geomspace(1.2, 3.0, 24)

        coarse = score_grid(
            alpha_range,
            np.geomspace(beta_lo, beta_hi, 40),
            np.geomspace(0.02, 6.0, 28),
        )
        a0, b0, e0 = coarse["alpha_power"], coarse["beta_nm"], coarse["eta_fit"]
        refined = score_grid(
            np.geomspace(max(1.05, a0 / 1.35), min(4.0, a0 * 1.35), 28),
            np.geomspace(max(150.0, b0 / 3.0), min(160000.0, b0 * 3.0), 48),
            np.geomspace(max(1e-3, e0 / 4.0), e0 * 4.0, 36),
        )
        return refined

    def plot_last_fit(self):
        if not self.last_fit_result:
            fits = self.project.get("pec_fits", [])
            if not fits:
                messagebox.showinfo("Plot PEC Fit", "No PEC fit available yet.")
                return
            self.last_fit_result = fits[-1]

        res = self.last_fit_result
        plot_data = res.get("plot_data")
        if not plot_data:
            messagebox.showerror("Plot PEC Fit", "No plot data stored in the last fit result.")
            return

        _ensure_numpy()
        r = np.asarray(plot_data.get("r_nm", []), dtype=float)
        y_meas = np.asarray(plot_data.get("measured_density", []), dtype=float)
        y_fit = np.asarray(plot_data.get("fitted_density", []), dtype=float)
        if r.size == 0 or y_meas.size == 0 or y_fit.size == 0:
            messagebox.showerror("Plot PEC Fit", "Stored plot data is empty.")
            return

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

        mpl = _ensure_matplotlib_pyplot()
        fit_label = f"{self._fit_model_display_name(res)} fit"
        if mpl is not None:
            fig = mpl.figure(figsize=(7, 5))
            ax = fig.add_subplot(111)
            ax.loglog(r, y_meas, '.', markersize=3, label='Measured (simulation histogram)')
            ax.loglog(r, y_fit, '-', linewidth=1.5, label=fit_label)
            ax.set_xlabel('Radius (nm)')
            ax.set_ylabel('Deposited energy density (normalized, 1/nm^2)')
            ax.set_title(title)
            ax.grid(True, which='both', alpha=0.25)
            ax.legend()
            fig.tight_layout()
            mpl.show()
            return

        self._plot_last_fit_tk(r, y_meas, y_fit, title)

    def _plot_last_fit_tk(self, r, y_meas, y_fit, title):
        win = tk.Toplevel(self.root)
        win.title("PEC Fit Plot (Tk fallback)")
        _configure_toplevel(win, self.root, width=900, height=650, min_width=520, min_height=360)

        outer = ttk.Frame(win, padding=8)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=title).pack(anchor="w", pady=(0, 6))

        canvas = tk.Canvas(outer, bg="white", highlightthickness=1, highlightbackground="#999")
        canvas.pack(fill="both", expand=True)

        info = ttk.Label(outer, text="Matplotlib not found, using built-in plot. Axes are log-log.")
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
            if not np.any(m1) or not np.any(m2):
                return
            x_all = np.concatenate([r[m1], r[m2]])
            y_all = np.concatenate([y_meas[m1], y_fit[m2]])
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

            # Legend
            lx = left + 10
            ly = top + 10
            canvas.create_rectangle(lx, ly, lx + 180, ly + 40, fill="white", outline="#bbb")
            canvas.create_oval(lx + 8, ly + 9, lx + 12, ly + 13, fill="#1f77b4", outline="")
            canvas.create_text(lx + 20, ly + 11, text="Measured (histogram)", anchor="w", font=("Helvetica", 9))
            canvas.create_line(lx + 8, ly + 28, lx + 18, ly + 28, fill="#d62728", width=2)
            canvas.create_text(lx + 20, ly + 28, text=fit_label, anchor="w", font=("Helvetica", 9))

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

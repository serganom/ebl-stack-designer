# EBL Stack Designer

Desktop Python/Tkinter application for electron-beam lithography stack design, fast standalone Monte Carlo style energy-deposition simulation, and PEC parameter fitting.

Author: `Sergei Nomoev`

Suggested GitHub repo description:
`Desktop EBL stack designer with standalone Monte Carlo PEC fitting, adaptive PSF models, and multilayer material/stack editing.`

## What It Is

`EBL Stack Designer` is a practical GUI tool for building multilayer EBL stacks and estimating proximity-effect parameters without requiring a full external Monte Carlo workflow for every iteration.

It is meant for:

- rapid PEC exploration
- comparing substrates, resists, and layer stacks
- estimating `alpha`, `beta`, `eta`, or `alpha_p`
- educational and engineering use

It is not meant to replace a fully calibrated production simulator.

## Current Highlights

- custom material library with elemental composition, density, weight fraction, and atomic fraction
- multilayer stack editor with roles such as `resist`, `substrate`, `metal`, `dielectric`, and `adhesion`
- stack cross-section preview
- resizable dialogs and scrollable forms/lists
- standalone transport simulation for the selected resist layer
- adaptive PSF fitting:
  - double-Gaussian
  - power-Gaussian composite
- weighted fitting with center-priority
- automatic noisy-tail cutoff during fit preparation
- fit plot viewer
- live Monte Carlo progress window with:
  - electron count
  - percent complete
  - elapsed time
  - ETA
  - approximate electron rate
- JSON save/load
- exportable project summary

## Physics Summary

The program contains a lightweight standalone physical approximation for EBL transport and PEC fitting.

Implemented ideas include:

- compound material properties derived from elemental fractions
- effective atomic number and atomic weight
- Bragg-type compound stopping bookkeeping
- Joy-Luo / modified Bethe inspired continuous slowing-down
- screened Rutherford-inspired elastic scattering
- Kanaya-Okayama / Kyser-Murata style `E^1.67` range scaling
- radial deposited-energy histogram inside the selected resist layer
- adaptive PSF model selection based on fit quality and exposure regime

Short version:

- transport is approximate but physically motivated
- fitting is intended to give useful engineering PEC parameters
- the code is fast enough for interactive iteration inside a GUI

More detail is in [docs/PHYSICS.md](docs/PHYSICS.md).

## References Behind The Current Direction

- Qingyuan Mao, Jingyuan Zhu, Xinbin Cheng, Zhanshan Wang, "Proximity effect correction in electron beam lithography using a composite function model of electron scattering energy distribution", Discover Nano (2025). DOI: [10.1186/s11671-025-04264-0](https://doi.org/10.1186/s11671-025-04264-0)
- "Fast and accurate proximity effect correction algorithm based on pattern edge shape adjustment for electron beam lithography", Microelectronics Journal (2023). DOI: [10.1016/j.mejo.2023.105718](https://doi.org/10.1016/j.mejo.2023.105718)
- Takashi Kamikubo et al., JJAP (1997). DOI: [10.1143/JJAP.36.7546](https://doi.org/10.1143/JJAP.36.7546)
- Joy and Luo, Scanning (1989)
- Kyser and Murata, IBM Journal of Research and Development (1974)
- Chang, Journal of Vacuum Science and Technology (1975)

## Repository Layout

- `ebl_stack_designer.py` — main application
- `run_ebl_stack_designer.sh` — shell launcher
- `run_ebl_stack_designer.command` — macOS double-click launcher
- `requirements.txt` — runtime Python dependencies
- `docs/PHYSICS.md` — short physics note

## Installation

### Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

Dependencies:

- `numpy`
- `matplotlib`
- `tkinter` from the Python installation

On Linux, `tkinter` may need a system package such as `python3-tk`.

## Run

### Standard shell launcher

```bash
./run_ebl_stack_designer.sh
```

### macOS double-click launcher

```bash
run_ebl_stack_designer.command
```

### Direct Python launch

```bash
python3 ebl_stack_designer.py
```

### Important macOS note

On some macOS systems, `/usr/bin/python3` is not suitable for this GUI app.

If needed, use the python.org Framework build explicitly:

```bash
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 ebl_stack_designer.py
```

If dependencies are missing for that interpreter:

```bash
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m pip install numpy matplotlib
```

The bundled launchers try to prefer a Python interpreter with working `tkinter`.

## Basic Workflow

1. Add or import materials.
2. Build the stack from top to bottom.
3. Mark the resist layer with role `resist`.
4. Set beam energy and optional beam diameter/current.
5. Run `Simulation + Fit`.
6. Watch the dedicated progress window during Monte Carlo.
7. Inspect the fit result and plot.
8. Save the project or export a summary.

## What The Fit Produces

Depending on the chosen model, the program can estimate:

- `alpha` for double-Gaussian forward blur
- `alpha_p` for power-Gaussian forward behavior
- `beta` for long-range backscatter spread
- `eta` fit ratio
- split-based forward/back energy ratio estimate
- simple PEC guidance text based on long-range blur strength

The fit pipeline currently includes:

- weighted log-space fitting
- center-priority weighting
- signal-based downweighting
- optional far-tail automatic cutoff when the histogram becomes noise-dominated

## Current Limitations

- this is still a fast approximate standalone model
- it is not numerically identical to CASINO
- commercial resist presets are approximate because exact chemistries are proprietary
- PEC parameters should still be calibrated against experiment for real process use
- a two-component PSF can still be too simple for some exposure regimes

## Good Use Cases

- fast substrate comparison
- resist / thickness trend exploration
- early PEC parameter estimation
- generating starting values for more detailed calibration
- teaching / demonstration of EBL scattering and PEC behavior




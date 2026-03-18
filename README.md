# EBL Stack Designer

`EBL Stack Designer` is a desktop Python/Tkinter application for electron-beam lithography stack design and fast proximity-effect estimation.

Author: `made by Sergei Nomoev`

## What The Program Does

- builds multilayer EBL stacks from user-defined materials
- stores elemental composition, density, thickness, and layer role
- previews the stack cross-section
- runs a built-in Monte Carlo style transport model for the selected resist layer
- fits PEC parameters from the deposited-energy histogram
- supports both a standard double-Gaussian PSF and an adaptive power-Gaussian composite PSF
- saves projects and exports text summaries

## Physics Summary

This version is not just a UI shell. It includes a standalone physical approximation for EBL transport and PEC fitting:

- compound material properties are derived from elemental fractions, density, effective atomic number, effective atomic weight, and mean ionization energy
- continuous energy loss uses a Joy-Luo / modified Bethe style stopping model with Bragg additivity for compounds
- elastic deflection uses a screened Rutherford-inspired angular model
- transport length scales are tied to a Kanaya-Okayama / Kyser-Murata style `E^1.67` range scaling
- deposited energy is accumulated radially inside the chosen resist layer
- the radial energy-density profile is fit either with:
  - a double-Gaussian PSF for standard PEC workflows
  - a power-Gaussian composite PSF for high-voltage and thin-resist regimes

Short version: the tool is meant to be a fast engineering estimator for PEC exploration, not a replacement for full CASINO, GEANT4, or a rigorously calibrated production simulator.

More detail is in [docs/PHYSICS.md](docs/PHYSICS.md).

## References Used For The Current Physics Direction

- Qingyuan Mao, Jingyuan Zhu, Xinbin Cheng, Zhanshan Wang, "Proximity effect correction in electron beam lithography using a composite function model of electron scattering energy distribution", Discover Nano (2025). DOI: [10.1186/s11671-025-04264-0](https://doi.org/10.1186/s11671-025-04264-0)
- "Fast and accurate proximity effect correction algorithm based on pattern edge shape adjustment for electron beam lithography", Microelectronics Journal (2023). DOI: [10.1016/j.mejo.2023.105718](https://doi.org/10.1016/j.mejo.2023.105718)
- Takashi Kamikubo et al., JJAP (1997). DOI: [10.1143/JJAP.36.7546](https://doi.org/10.1143/JJAP.36.7546)
- Joy and Luo, Scanning (1989), modified Bethe stopping formulation
- Kyser and Murata, IBM Journal of Research and Development (1974), electron-scattering transport scaling
- Chang, Journal of Vacuum Science and Technology (1975), double-Gaussian PEC model

## Repository Layout

- `ebl_stack_designer.py` — main GUI application
- `run_ebl_stack_designer.sh` — simple launcher
- `requirements.txt` — Python dependencies
- `docs/PHYSICS.md` — short physics note and formulas

## Installation

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Notes:

- `tkinter` usually comes with the Python installation. On Linux it may need to be installed from the system package manager.
- `matplotlib` is optional for the main app logic, but recommended for plotting PEC fits.

## Run

Using the launcher:

```bash
./run_ebl_stack_designer.sh
```

Or directly:

```bash
python3 ebl_stack_designer.py
```

## Basic Workflow

1. Add or import materials.
2. Build the stack from top to bottom.
3. Mark the resist layer with role `resist`.
4. Set beam energy and optional beam diameter/current.
5. Run `Simulation + Fit`.
6. Inspect the fitted PEC parameters and export the project summary if needed.

## Current Output

The app can estimate and display:

- forward blur parameter `alpha` for double-Gaussian fits
- forward power exponent `alpha_p` for power-Gaussian fits
- backscatter range `beta`
- fitted energy ratio `eta`
- split-based forward/back energy ratio estimate
- a simple PEC guidance label based on long-range backscatter strength

## Important Limitations

- this is a fast approximate standalone model
- it is not numerically identical to CASINO
- material presets for commercial resists are approximate because exact formulations are proprietary
- PEC accuracy still depends on calibration against real process data

## Upload To GitHub

This folder is prepared to be a clean GitHub repository. After creating a GitHub repo, use:

```bash
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```


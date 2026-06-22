# Physics Notes

This document summarizes the physics approximations used in `ebl_stack_designer.py`.

## 0. Units And PSF Normalization

The program uses a strict unit policy:

- internal lengths: `nm`
- BEAMER-facing output lengths: `um`
- density: `g/cm^3`
- beam energy in the GUI: `keV`
- layer thickness: `nm`
- radial PSF density: `1/nm^2` internally and `1/um^2` in text/CSV export where stated

Raw Monte Carlo deposited energy is accumulated in radial ring bins. It is converted to an area-density PSF by:

`PSF_i = E_i / area_i`

with:

`area_i = pi * (r_outer^2 - r_inner^2)`

The normalized physical PSF is expected to satisfy:

`sum(PSF_i * area_i) ~= 1`

The code stores and exports diagnostics for this integral and refuses export when a stored normalized PSF is clearly invalid.

## 1. Material Model

Each material is defined by:

- density `rho` in `g/cm^3`
- elemental list with `Z`
- weight fraction
- atomic fraction

From this, the code derives:

- effective atomic number `Z_eff`
- effective atomic weight `A_eff`
- Bragg-style compound stopping data
- compound mean ionization energy

Approximate ionization-energy relation:

`J(eV) = 9.76 Z + 58.8 Z^-0.19`

For compounds, a Bragg-type logarithmic mixing rule is used.

## 2. Electron Transport Scale

The transport length scale follows an `E^1.67` style range dependence motivated by Kanaya-Okayama / Kyser-Murata type electron-range scaling.

This is used to construct an effective elastic mean free path.

## 3. Elastic Scattering

Angular deflection uses a screened Rutherford-inspired inversion:

`cos(theta) = 1 - 2 alpha R / (1 + alpha - R)`

with

`alpha ~ 3.4e-3 Z^0.67 / E`

where `R` is a uniform random number and `E` is the electron energy in `keV`.

This keeps the code lightweight while still producing physically sensible growth of scattering with higher `Z` and lower `E`.

## 4. Continuous Energy Loss

Stopping is based on a Joy-Luo / modified Bethe style form with Bragg additivity:

`-dE/dS = rho * sum_i [ w_i * 7.85e-3 * Z_i / (A_i E) * ln(1.166 * (E + 0.85 J_i) / J_i ) ]`

in code units of `keV / nm`.

This term is blended with a simple CSDA-like range-derived term to avoid unphysical behavior across the full operating range.

## 5. Energy Deposition

Deposited energy is accumulated inside the selected resist layer as a radial histogram.

If multiple adjacent layers are marked as `resist`, they can be analyzed as one combined resist region. This is useful for PMMA bilayer processes such as PMMA 950k on PMMA 495k, where the chemistry is similar but the process stack still benefits from keeping the layers explicit in the editor.

Instead of dumping the whole segment energy at a single endpoint, the code subdivides the lateral segment and distributes energy along it. This reduces center-bias artifacts in the histogram.

For the final layer, clearly bulk substrates are treated as semi-infinite for transport. Thin substrate or membrane-like examples, such as a 4.4 um Si layer, remain finite so that the simulated stack matches the entered geometry.

## 6. PEC / PSF Fitting

### Double-Gaussian

Standard PEC fit:

`PSF(r) = [ G(alpha) + eta G(beta) ] / (1 + eta)`

where

`G(width) = exp(-r^2 / width^2)`

with normalization applied numerically over the sampled radial bins.

This is the width convention used by the program and BEAMER-oriented output metadata. With this convention:

`FWHM = 2 * width * sqrt(ln 2)`

This is the conventional EBL PEC representation used in many older and current workflows.

### Power-Gaussian Composite

For high-voltage and thin-resist conditions, the code also tests a composite model:

`PSF(r) = [ P(alpha_p) + eta G(beta) ] / (1 + eta)`

where

`P(alpha_p) ~ r^(-alpha_p)`

after numerical normalization on the fit domain.

This model direction is motivated by recent literature showing that a pure double-Gaussian description may be too restrictive for some high-energy scattering distributions.

## 7. Model Selection

Both candidate models are fit on the same histogram window.

The program prefers the power-Gaussian model in high-voltage / thin-resist regimes, but still compares the fit error and can fall back to the double-Gaussian model if it is clearly better.

## 8. Fit Weighting And Tail Handling

The fit is not an unweighted raw least-squares pass over the whole histogram.

The current implementation gives higher importance to:

- smaller radii
- stronger-signal bins

This is intentional, because the physically important forward-scattering region near the beam center should not be dominated by a large number of weak far-tail bins.

The code can also cut the far tail automatically when the histogram becomes noise-dominated. This avoids dragging the whole fit toward sparse long-range Monte Carlo noise.

## 9. PSF Curve Export

The fitted radial PSF curve can be exported in three forms:

- `.lpsf`: zlib-compressed `LPSF_2012` XML archive for BEAMER-style numerical PSF import
- `.psf`: simple two-column text table, `radius_um` and selected fitted density in `1/um^2`
- `.csv`: diagnostic table with measured histogram, selected physical fit, and BEAMER Gaussian approximation

For `.lpsf`, the selected physical fit curve is resampled onto an exponential radial grid with 50 points per decade, similar to common mcTrace/BEAMER PSF archives. The amplitude is scaled as a relative PSF; the important quantity for PEC import is the radial shape, while BEAMER can normalize the numerical PSF internally.

Exports are written atomically: the program writes a temporary file, reads it back, validates the curve, and only then replaces the target file.

## 10. Scope

This is an engineering approximation for rapid PEC exploration inside a GUI workflow.

It should be treated as:

- useful for stack comparison
- useful for early PEC parameter estimation
- useful for educational and exploratory work

It should not be treated as:

- a replacement for calibrated full Monte Carlo engines
- a substitute for measured process calibration
- a process-certified production model

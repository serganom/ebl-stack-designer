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

`PSF_i = E_i / (sum_j(E_j) * area_i)`

with:

`area_i = pi * (r_outer^2 - r_inner^2)`

Stored histogram radii are the outer edges of rings `[i*dr, (i+1)*dr)`. A deposition at radius `r` enters bin `floor(r/dr)`. The split-energy diagnostic includes the central ring; a cutoff within a ring uses its area fraction.

The normalized histogram PSF is expected to satisfy:

`sum(PSF_i * area_i) ~= 1`

The code stores and exports diagnostics for this integral and refuses export when a stored normalized PSF is clearly invalid.

## 1. Material Model

Each material is defined by:

- density `rho` in `g/cm^3`
- elemental list with `Z`
- mass fractions (canonical input)
- atomic fractions derived as `(w_i/A_i) / sum_j(w_j/A_j)`

Atomic weights use the [CIAAW 2024 abridged standard table](https://ciaaw.org/abridged-atomic-weights.htm). Elements without a standard weight require an isotope-specific model and are rejected. Older independent atomic-fraction values are recalculated from the mass composition with a migration notice. Commercial resist mass recipes remain approximate; internal consistency does not establish their true proprietary chemistry.

From this, the code derives:

- effective atomic number `Z_eff`
- effective atomic weight `A_eff`
- Bragg-style compound stopping data
- compound mean ionization energy

Approximate ionization-energy relation:

`J(eV) = 9.76 Z + 58.8 Z^-0.19`

Hydrogen is an explicit exception: the implementation uses `J_H = 19.2 eV`.

For compounds, a Bragg-type logarithmic mixing rule is used.

## 2. Electron Transport Scale

The transport length scale follows an `E^1.67` style range dependence motivated by Kanaya-Okayama / Kyser-Murata type electron-range scaling.

The effective elastic mean free path is

`lambda(E) = max(0.5 nm, 0.009 R_KO(E) / (1 + 0.045 Z_eff + 0.12 rho))`.

This empirical effective length has not been independently calibrated. It is not derived by integrating the angular differential cross section. The sampled optical depth `tau = -ln(1-u)` is consumed by `ds/lambda` in each traversed material; any remainder is converted using the next material's local lambda. Local stopping and lambda are frozen within each numerical segment. Layer role labels and the selected energy-tally region do not modify these physical coefficients.

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

The implementation retains the explicitly named legacy blend

`S_mix(E) = 0.65 S_JL(E) + 0.35 * 0.72 E/R_KO(E)`.

The repository does not establish a source or calibration for the constants 0.65, 0.35 and 0.72. Their removal is a physical-model change requiring comparison against independent stopping data, not a substitute for correcting software errors. See [the correctness review](CORRECTNESS_REVIEW.md). No accuracy benefit from this blend is asserted. A uniform multiplicative factor between 0.92 and 1.08 is also retained as a heuristic fluctuation, not a physical straggling model.

All stopping coefficients depend on the local material and energy. Previous role-dependent multipliers and corrections based on the chosen tally material have been removed.

## 5. Energy Deposition

Deposited energy is accumulated inside the selected resist layer as a radial histogram.

If multiple adjacent layers are marked as `resist`, they can be analyzed as one combined resist region. This is useful for PMMA bilayer processes such as PMMA 950k on PMMA 495k, where the chemistry is similar but the process stack still benefits from keeping the layers explicit in the editor.

Instead of dumping the whole segment energy at a single endpoint, the code subdivides the lateral segment and distributes energy along it. This reduces center-bias artifacts in the histogram.

Every entered layer remains finite, including thick substrates. An electron leaving either surface is recorded as escaped. The final segment is shortened if its energy reaches the positive cutoff before a collision or a boundary; energy is not spread over an untraversed part of the segment.

Transport records a complete primary-electron energy account:

`incident = deposited_in_all_materials + escaped + residual_at_cutoff + residual_at_collision_limit + residual_at_radial_limit`.

Deposits in the selected resist are separately split into those inside and outside the histogram radius. The result stores termination counts, residual energies, maximum reached depth/radius, and the numerical balance error. Limit truncations and significant histogram losses generate visible warnings. A unit-normalized histogram alone cannot show these losses, so it is not used as evidence of transport convergence.

## 6. PEC / PSF Fitting

New fits store a versioned `fit_representation` with the model family, component parameters, the power core radius, and the fitted amplitude. Its evaluator is independent of the radius array and the fit window.

### Double-Gaussian

`K(r) = A * [G(r, alpha) + eta * G(r, beta)] / (1 + eta)`

`G(r, a) = exp(-r^2/a^2) / (pi*a^2)`

Each component has unit area integral on the entire radial plane, `integral_0^infinity 2*pi*r*G(r,a) dr = 1`. Thus `eta` is the ratio of **global component integrals**, not a window-dependent weight. The width convention remains `FWHM = 2*a*sqrt(ln 2)`.

### Power-Gaussian Composite

`K(r) = A * [P(r, p, r0) + eta * G(r, beta)] / (1 + eta)`

`P(r,p,r0) = (p-2)/(2*pi*r0^2) * (1 + r^2/r0^2)^(-p/2)`

Here `r0 = max(1 nm, beam_sigma/2)`. Regularization makes the center finite. The power exponent must satisfy **p > 2** for a finite area integral on an unbounded plane; the search starts at 2.01. Earlier window-normalized fits allowed p <= 2 and did not define a globally integrable PSF. No unvalidated tail taper is introduced to hide this condition.

### Amplitude And Compatibility

`A` is a positive scale obtained analytically in the weighted log-density fit. It reconciles the observed, finite histogram with the globally normalized shape. Plots and residual metrics include this fitted amplitude. Numerical PSF exports use the unit-integral shape before `A`; LPSF applies its documented relative scale afterward.

Saved fits without a versioned representation keep their old plot data and convention labels. Their old eta values are not reinterpreted as global weights, and numerical PSF/LPSF export requires rerunning the simulation. Diagnostic CSV retains the original fit-window data.

### Histogram Averages Versus Point Density

A histogram value is the average density over its ring, not the density at the ring's outer edge. Fitting and residual diagnostics therefore use exact annular integrals divided by the original ring area:

`G_average = [exp(-r_inner^2/a^2) - exp(-r_outer^2/a^2)] / area`

`P_average = [(1+r_inner^2/r0^2)^(1-p/2) - (1+r_outer^2/r0^2)^(1-p/2)] / area`

Stable `expm1`/`log1p` forms avoid cancellation for narrow rings and broad components. This matters most for 1 nm bins and a few-nanometer forward width: evaluating at the outer edge biases the recovered global eta even when the first two rings are excluded.

`plot_data` stores these **annular average** densities at the corresponding outer radii, together with each original `ring_area_nm2` and a `sample_representation` label. Selected and BEAMER residuals compare like quantities. Numerical PSF/LPSF exports instead evaluate the continuous point density, including the center, from the same globally normalized model parameters.

The BEAMER Gaussian approximation uses the same global Gaussian components. Search points may be subsampled for speed, but component normalization never depends on that subset. The returned amplitude and MSE are recomputed on the full input grid, and evaluating the stored model on another grid does not refit its amplitude.

## 7. Model Selection

Both candidate models are fit on the same histogram window. A coarse search is followed by a finer grid, and the better of the two results is retained: refinement cannot discard a superior coarse candidate.

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

For `.psf` and `.lpsf`, the stored model is evaluated from **r = 0** on a logarithmic grid (80 points per decade), including the analytically reconstructed center. The radius extends until the exact remaining normalized mass is at most `1e-4`. Gaussian remaining mass is `exp(-R^2/a^2)`; the power-component remainder is `(1 + R^2/r0^2)^(1-p/2)`. Mixture tails use the corresponding component weights. The curve ends with its actual positive model value; no fabricated zero or constant central plateau is appended.

Export refuses a model whose remainder is still too large at `1e8 nm`, rather than silently truncating a very heavy power tail. This check controls mathematical truncation of the selected model, not the physical validity of extrapolating beyond Monte Carlo data. LPSF metadata records the omitted tail, tolerance, normalization and fitted amplitude. LPSF samples are scaled to a numerical radial integral of `1e9` as a relative PSF. The `.psf` density retains its physical `1/um^2` units and unit-integral shape. `.csv` is explicitly a diagnostic fit-window table and uses the original ring areas for cumulative quantities.

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

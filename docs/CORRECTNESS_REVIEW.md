# PEC correctness review

The baseline of this review is the published `0.4.0` source at commit
`f64d0937b016d5796106ee9ebb1b6ce52921f774`. Version 0.5.0 separates
numerical/software corrections from physical calibration.

The program defines a layer stack, estimates a radial deposited-energy PSF,
fits a compact representation, and exports it for subsequent PEC. It does
not solve a layout dose map. Passing regression tests establishes consistency
of the implementation; it does not establish exposure-dose or critical-dimension
accuracy on an electron-beam writer.

## Findings reproduced on the published baseline

| Area | Reproduced failure | Consequence |
| --- | --- | --- |
| Interfaces | A free flight selected in material A keeps its geometric length after crossing into B. | The collision probability in B initially follows A's mean free path. |
| Selected resist | Selecting a different layer for energy tally changes scattering in other, unchanged layers. | Two tallies no longer describe the same transport problem. |
| Material composition | Atomic and mass fractions describe different compositions in several presets. | Scattering and stopping use incompatible material definitions. |
| Atomic masses | Missing elements silently use `A = 2Z`; Ag becomes 94 instead of 107.87. | Compound conversion, range and stopping are biased. |
| Radial bins | `round(r)` deposits into rings subsequently interpreted as `[i, i+1)` nm. | The central density and split energy ratio are wrong. |
| Refinement | The fine grid replaces a better coarse-grid result. | Refinement can worsen a known exact fit. |
| BEAMER fitting | Component normalization changes between the subsampled fitting grid and full output grid. | The reported objective does not describe the output curve. |
| Export coverage | Only the fit window is exported, with constant inward extrapolation and an artificial outward zero. | Narrow centers and broad tails are distorted. |
| Result state | Loading project B can retain project A's `last_fit_result`. | Export can contain the wrong PSF. |
| Provenance | Results can inherit material/stack metadata from an edited live project. | An old PSF appears to describe new inputs. |
| Input validation | NaN, negative fractions and negative energy cutoffs are accepted in some paths. | Invalid input can produce invalid physical results, including energy gain. |

Additional state defects include duplicate material-name ambiguity, losing unsaved
beam values during refresh, and replacing the current project before a loaded
project has been fully validated.

## Status of the corrections

Version 0.5.0 addresses the reproduced software failures above and adds
headless regression coverage for them. Exact annular averages are now used when
fitting the energy histogram; evaluating the density at each ring's outer edge
was another source of bias, including about -42% in eta in a narrow analytic
test case. Continuous point densities are retained for numerical export.

The entered geometry stays finite. The transported primary energy is accounted
for across deposition, escape, energy cutoff and runtime limits. Results store
immutable input snapshots, source-run version and transport diagnostics. Numerical
exports reconstruct a globally normalized model from its center through a radius
with a controlled model-tail remainder. Old fits must be recalculated.

## Why 0.65 and 0.35 are a separate issue

The baseline stopping model is

`S_mix(E) = 0.65 S_JL(E) + 0.35 * 0.72 E / R_KO(E)`.

These constants are already present in the initial public commit
`5de241fd060192d42302212042d9be9277c232d5` (18 March 2026). The available
history and physics notes do not identify a source or calibration for their
specific values. This is an unresolved provenance question, not evidence of
fabrication and not an arithmetic error by itself.

For the **published baseline compositions** at 50 keV, `S_mix / S_JL` is
1.1807 for ma-N 2400, 1.1929 for Si and 1.2286 for InP. These are comparisons
between two internal approximations, not deviations from experiment. A separate
1000-electron sensitivity run on ma-N 500 nm / Si3N4 200 nm / InP 350 um changed
the fitted long-range parameters when only this blend was replaced by `S_JL`.
That run cannot select the physically more accurate model.

Blindly removing the weights does not fix the independent problems listed above.
A replacement stopping model should be chosen against external stopping-power
data with consistent material composition, density, energy and units. The weights
remain explicit legacy approximations until this comparison is completed.

Also, if `R = K E^1.67` were treated as a CSDA range, differentiation would give
`S = E/(1.67 R)`, not `0.72 E/R`. Kanaya–Okayama's range scale must not be
silently equated with a CSDA integral to justify the latter coefficient.

## What still requires physical validation

- The effective mean free path is based on a range scaling law, not obtained by
  integrating the same elastic differential cross section used for angular sampling.
- The continuous stopping approximation and its random multiplier do not model
  explicit secondary-electron transport or physical energy straggling.
- A low residual when fitting the simulator's own PSF validates the fit, not the
  electron transport that generated the PSF.
- A measured PEC process additionally involves beam blur, resist contrast and
  development. Practical use of a writer is not a numerical error measurement.
- The real BEAMER importer must verify interoperability; parsing our own export
  is only a format and numerical consistency check.

The next independent comparisons should cover Si, Au and InP substrates with a
specified resist at 20, 50 and 100 keV. Compare deposited-energy fractions,
radial cumulative distributions, backscatter fractions and their convergence
with electron count and energy cutoff. Compare stopping separately from elastic
transport so fitted compensation cannot conceal errors in either component.

## Reference data and scope

- [CIAAW abridged standard atomic weights 2024](https://ciaaw.org/abridged-atomic-weights.htm)
  supplies the atomic weights. Elements without a standard atomic weight require
  isotope-specific inputs rather than an invented fallback.
- [NIST ESTAR methods](https://physics.nist.gov/PhysRefData/Star/Text/method.html)
  describes stopping powers and CSDA ranges. Its low-energy limitations must be
  respected: an ESTAR comparison at tens of keV does not validate a 50 eV cutoff.
- [Mao et al., Discover Nano 20, 84 (2025)](https://doi.org/10.1186/s11671-025-04264-0)
  supports the power–Gaussian PSF modelling direction. Its experimental accuracy
  and fabrication results are not measurements of this implementation.

Numerical ESTAR reference tables were not successfully retrieved during this
review; no agreement with ESTAR is claimed.

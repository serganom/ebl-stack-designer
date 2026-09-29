# Changelog

## 0.5.0

This update corrects numerical and state-management errors in the stack-to-PSF
workflow. Previous results must be recalculated.

- Electron flights preserve optical depth across interfaces; the selected tally
  layer and role labels no longer alter the transport in other layers.
- Input thicknesses remain finite. Energy cutoff shortens the final segment;
  energy balance and termination reasons are retained with each calculation.
- Atomic fractions are derived from mass composition and sourced atomic weights.
- Histogram ring assignment, central energy accounting and annular-average fitting
  are consistent. Grid refinement retains the best coarse candidate.
- Gaussian and regularized power–Gaussian components use full-plane normalization;
  eta is a global component-integral ratio. Power exponents must exceed two.
- BEAMER approximation uses the same normalization during fitting and output.
  Numerical PSF exports reconstruct the center and control the omitted tail.
- Fit input snapshots are immutable. Loading projects updates the result cache;
  stale and legacy numerical exports are guarded. Input validation is transactional.
- Added regression tests, an example calculation script and GitHub Actions checks.

The legacy 0.65/0.35 stopping blend remains uncalibrated. These corrections and
regression tests do not establish absolute physical or process PEC accuracy.
See `docs/CORRECTNESS_REVIEW.md` and `docs/PHYSICS.md`.

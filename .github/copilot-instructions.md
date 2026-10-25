# Copilot instructions

Read `AGENTS.md` first. This codebase is a CPU-first research scaffold, not a medical device. Keep modules small and preserve the current API/message contracts.

- Run `python -m compileall -q app worker`, `python -m pytest -q`, `python -m black --check app worker tests scripts`, and `python -m flake8 app worker tests scripts` after Python edits.
- Never use horizontal flips or Guided Grad-CAM. Apply MONOCHROME1 inversion after VOI. Register CAM hooks once and release request state in `finally`.
- Never put direct identifiers in queue messages or upload original un-deidentified DICOMs to object storage.
- Treat the PostgreSQL claim/fenced update as correctness; Redis only reduces duplicate work. Never claim Docker/GPU/cloud tests ran unless actually executed.
- Label any unvalidated design proposal with `# FLAG:`; no unfinished placeholders and no clinical/regulatory claims.

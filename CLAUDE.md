# MyAstroBoard - instructions for AI coding agents

The rules live in two files under `.github/instructions/`, shared with GitHub Copilot:

- the organization standards, synced from
  [myastroboard/.github](https://github.com/myastroboard/.github/tree/main/standards) - do not edit
  the copy here;
- the MyAstroBoard-specific rules, which add how this project implements them.

@.github/instructions/org-standards.instructions.md

@.github/instructions/copilot.instructions.md

## Things that will waste your time if you don't know them

- **Never run two pytest processes at once.** Backend modules are imported at collection time, so
  `DATA_DIR` binds to the temp root set by `tests/conftest.py`, shared by every run; two runs race
  on the same state files and produce hundreds of phantom failures. `_clean_stale_test_state()`
  wipes that state when conftest is imported.
- **The first pytest run after a while is slow** (astropy / skyfield ephemeris and IERS loading,
  several minutes). It is not a hang. The full suite then takes about 5 minutes.
- **The background cache scheduler runs during tests** and can write real data into shared caches
  mid-test. Route tests in `tests/blueprints/test_app_routes.py` plant per-location cache data
  through the `_LEGACY[name]` proxy instead.
- **Known order-dependent flakes**: a test that fails in a full run but passes alone
  (`pytest path::test`) is first suspected of shared-state interference, not of a bug in the code
  that changed. Rerun it in isolation before diagnosing.
- **Do not edit `backend/` while a `--cov=backend` run is in flight**: coverage maps line numbers
  against the source at report time, so a mid-run edit shows fake missing lines.

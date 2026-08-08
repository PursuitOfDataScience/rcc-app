# Working on Sage

## Finish the job

A task is done when the work is **merged to `main`**, not when it is pushed and CI
is pending. Do not stop at "waiting for CI" and hand back — see it through:

1. Push to the working branch.
2. Open a PR if there is no open one for it.
3. Run CI (`ci.yml` sometimes needs a manual dispatch — check that a run exists for
   the exact SHA rather than assuming the push triggered one).
4. Merge. Squash merges leave `main` with a commit that is not an ancestor of the
   branch, so a follow-up push will report a merge conflict: rebuild the branch on
   `origin/main`, cherry-pick, confirm `git diff --stat <old> HEAD` is empty, and
   force-push with `--force-with-lease`.
5. Report the merge commit.

If something genuinely blocks the merge, say what it is in one line — don't go quiet.

The layout check (`python tools/render_check.py`) takes ~10 minutes in CI. Running it
locally on the same commit is the same script against the same stylesheet, so a clean
local run plus green lint/tests is enough to merge on; don't idle waiting for the
remote copy of a result already in hand.

## Running the checks here

Three of them are available and two of them hide:

- **Lint**: `/root/.local/bin/ruff check .` — installed, but not on `PATH`, so a bare
  `ruff` or `python -m ruff` says "no module named ruff". A whole session was spent
  reporting the lint as unrunnable while CI failed on `SIM117`; it is runnable.
- **Tests**: pytest cannot be installed (no package index). Write a shim in the session
  scratchpad, put that directory first on `PYTHONPATH`, and run it from the repo root.
  Do **not** commit a `pytest.py` to the repo: CI installs the real one and a module at
  the root would shadow it.

  Six things the shim needs, each because its absence silently shrinks the run rather
  than failing:
  1. `fixture` (including `scope="session"`) — without it, 2 files of 11 collect.
  2. `mark.parametrize`, `raises(...).value`, `mark.xfail`, `skip`.
  3. **Methods of `Test*` classes.** Collecting only module-level `test_*` functions
     reports a green run of 136 tests where there are 329 — every class-based test in
     `test_search.py`, `test_providers.py`, `test_app_smoke.py` and others is skipped,
     and nothing says so. This is the single easiest way to believe the suite passes
     when most of it never ran; check the count, not just the exit code.
  4. `monkeypatch` (`setattr`/`setenv`/`setitem`/`undo`) and `caplog`.
  5. `tests/` on `sys.path`, because test modules import `stub_streamlit` by bare name.
  6. Marks read through `__func__` for bound methods — a bound method cannot carry the
     attributes the decorators set.

  The current count is **390 passing across 13 files**. A run reporting far fewer is a
  collection bug in the shim, not a smaller suite.

- **The stub matters as much as the shim.** `tests/stub_streamlit.py` models the
  Streamlit API the app actually calls. Using a new `st.*` function means adding it
  there or every smoke test dies at import with `AttributeError`. Watch the decorators
  when inserting code into that file: a class dropped between `@contextmanager` and its
  function turns `st.container()` into a generator and takes 57 tests down at once.
- **Layout**: `python tools/render_check.py`, ~4 minutes locally for ~576 renders.

Run all three before pushing. Each has failed CI at least once for want of being run.

## The UI

Every UI bug that has shipped here was pure CSS, and Streamlit usually cannot be
installed in the working environment. `tools/render_check.py` renders `static/app.css`
against a replica of Streamlit's DOM in headless Chromium and measures it.

Two habits from things that got past it:

- **Reproduce first.** Make the harness fail on the bug before fixing it, then confirm
  the fix silences it. A check that cannot fail reads as a pass, which is worse than
  no check.
- **Model both shapes.** When Streamlit's real markup is not visible from here, render
  every plausible shape rather than guessing one. The container-key class landing on
  the vertical block vs. a wrapper, the bottom bar `fixed` vs. `sticky`, the scrollbar
  on `stMain` vs. the document, the send button beside the text vs. under it — each of
  those pairs cost a round of "fixed it" that fixed nothing.

Prefer a mechanism whose failure mode is visible over one that depends on how Streamlit
lays out the page, and don't write a rule against an unversioned Streamlit test id that
this repo cannot see — it fails silently the day it changes.

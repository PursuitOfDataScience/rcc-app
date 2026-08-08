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
- **Tests**: pytest cannot be installed (no package index). There is a working shim in
  the session scratchpad that handles fixtures, `parametrize`, `raises(...).value` and
  `xfail`; without those four it silently runs 2 test files out of 11.
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

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

**Activate the environment first. Everything below is in it:**

```bash
source /software/python-miniforge-25.3.0-el8-x86_64/bin/activate AI
```

That gives you ruff 0.15.18, pytest 9.0.3, streamlit 1.54.0, playwright 1.59.0 and
httpx. Outbound HTTPS works. Chromium is at
`~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome`.

- **Lint**: `ruff check .`
- **Tests**: `python -m pytest -q` — 387 pass. Real pytest; no shim is needed.
- **Layout**: `SAGE_CHROME=~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome
  python tools/render_check.py` — ~7 minutes for 576 renders.
- **Anchors**: `python tools/anchor_check.py` — network-bound, so not in the suite.
  Run it after touching `slugify`, `plain_heading` or `docs_url`.

Run the first three before pushing. Each has failed CI at least once for want of
being run.

### Running the app itself, with no API key

The OpenCode adapter is a plain OpenAI-compatible HTTP client, so a local server is
a provider. `tools/mock_provider.py` is one; nothing in the app knows it is there.

```bash
python tools/mock_provider.py 8799 &
echo '{"mode": "tools"}' > /tmp/mock_provider.json      # search → read → answer
OPENCODE_API_KEY=sk-zen-test OPENCODE_BASE_URL=http://127.0.0.1:8799/v1 \
SAGE_DEFAULT_MODEL=opencode:mock-fast-free \
streamlit run app.py --server.port 8502 --server.headless true
```

Run it from the repo root, or `RCC_DOCS_PATH=./docs` resolves somewhere with no
corpus in it and every answer comes back uncited. Then drive it with Playwright
(`~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome`), and rewrite the
control file between turns to pick the next scenario — an empty completion, a 402, a
tool loop that never finishes, a slow stream you can interact with mid-answer.
`/tmp/mock_provider.jsonl` records what the app actually sent upstream, which is the
only way to see the messages the history budget produced.

This is what found the bugs the harness structurally cannot: a rate-limited starter
card that did nothing at all, a completion with no text rendering as a blank, an
oversized upload vanishing with its error message inside the hidden uploader, and the
copy button painted over the first line of every answer.

> This section used to say pytest could not be installed, that ruff lived at
> `/root/.local/bin/ruff` (it is there, and permission-denied for this user), and that
> Streamlit usually could not be run. All three were wrong, and the cost was that
> nobody ran the app: a post-turn scroll bug that hid every answer's Sources strip and
> 👍/👎 behind the composer, and a question-to-answer gap the layout harness was
> structurally unable to see, both survived because the only thing that could catch
> them was believed to be unavailable. **Check before recording that a tool is
> missing.**

## The UI

Every UI bug that has shipped here was pure CSS, and `tools/render_check.py` renders
`static/app.css` against a replica of Streamlit's DOM in headless Chromium and
measures it. But Streamlit **does** run here, so the replica is no longer the only
witness: boot the real app against a mock provider and drive it with Playwright when
a bug is about behaviour over time rather than a static layout. That is what the
harness cannot model — it renders settled states, not the moment a turn lands and the
page grows by 130–290px underneath the reader.

Two habits from things that got past it:

- **Reproduce first.** Make the harness fail on the bug before fixing it, then confirm
  the fix silences it. A check that cannot fail reads as a pass, which is worse than
  no check.
- **Model both shapes.** When Streamlit's real markup is not visible from here, render
  every plausible shape rather than guessing one. The container-key class landing on
  the vertical block vs. a wrapper, the bottom bar `fixed` vs. `sticky`, the scrollbar
  on `stMain` vs. the document, the send button beside the text vs. under it — each of
  those pairs cost a round of "fixed it" that fixed nothing.

- **Model the wrappers, not just the classes.** Streamlit puts
  `[data-testid="stMarkdownContainer"]` between `.stMarkdown` and anything given to
  `st.markdown`, and it carries `margin-bottom: -1rem`. The replica had the classes and
  not that wrapper, so every gap set from inside a markdown block measured 16px more
  generous here than in the app — the harness read 44px, the app drew 28px, and it
  passed a bound the app was failing. Margins in `app.css` are written 1rem larger than
  the gap they draw for this reason.

Prefer a mechanism whose failure mode is visible over one that depends on how Streamlit
lays out the page, and don't write a rule against an unversioned Streamlit test id that
this repo cannot see — it fails silently the day it changes. On 1.54,
`[data-testid="stMain"]` no longer exists; the scrollport is
`section[data-testid="stAppScrollToBottomContainer"]`.

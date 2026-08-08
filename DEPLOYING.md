# Running and deploying the website assistant

Step by step, from nothing to a hosted app. Written for `SAGE_PROFILE=site` — the
assistant that answers from [youzhi.netlify.app](https://youzhi.netlify.app/) — but
every step applies to the RCC deployment with the profile line left out.

Nothing here touches the website repository.

---

## 1. Get at least one API key

One is enough. With both, the model picker offers both and a spent quota fails over
on its own instead of ending the conversation mid-answer.

**OpenCode Zen — free, start here.** Sign in at
[opencode.ai/zen](https://opencode.ai/docs/zen/) with GitHub or Google, create an API
key from the dashboard. It looks like `sk-zen-…` and **is shown once**, so paste it
somewhere before closing the tab. No billing details are needed for the free models.
Its free lineup rotates; the app discovers the current one at runtime rather than
trusting a hardcoded list.

**Mistral — paid, better answers.** [console.mistral.ai](https://console.mistral.ai/)
→ API Keys → create one. Mistral's free experiment tier requires phone verification.
`mistral-small-latest` is the default and is the cheapest of the three offered.

If you only want to see the thing work, take the Zen key and skip Mistral.

---

## 2. Run it locally

```bash
git clone https://github.com/PursuitOfDataScience/sage
cd sage
git checkout claude/chatbot-website-integration-plan-91ibip

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Put the keys in `.streamlit/secrets.toml`. That path is **gitignored** — it will not
be committed:

```toml
# .streamlit/secrets.toml
MISTRAL_API_KEY  = "..."            # either of these,
OPENCODE_API_KEY = "sk-zen-..."     # or both

SAGE_PROFILE     = "site"
SAGE_MAX_TOKENS  = "1500"
```

Then:

```bash
streamlit run app.py          # → http://localhost:8501
```

Environment variables work too, and win over the file:

```bash
SAGE_PROFILE=site OPENCODE_API_KEY=sk-zen-... streamlit run app.py
```

### Confirming it is the right assistant

Three things to look at, in order — each rules out a different way this can go quietly
wrong:

1. **The terminal** prints one line on first load:

   ```
   Sage ready: profile=site, 116 pages · 562 sections
   ```

   `profile=rcc` here means the setting did not arrive, and the app is answering
   about Slurm from a corpus of blog posts. `0 pages` means the corpus is missing —
   the app will say so on screen rather than answering "not covered" forever.

2. **The welcome screen** should read *"Ask about anything I've written"* with blue
   starter cards, not *"What can I help you with?"* in maroon.

3. **Ask something and check the citation.** Under the answer is a Sources strip;
   the chips should link to `youzhi.netlify.app/post/…/#a-section-anchor`. Click one.
   It should land on the section the answer came from, not the top of the page.

### Questions worth trying

These exercise the parts most likely to be wrong:

| Question | What it tests |
|---|---|
| `What is rapiDU and what can it measure that du cannot?` | a recent long article, deep-link anchors |
| `How were the Argonne models pretrained from scratch?` | multi-section retrieval within one article |
| `What is the difference between Argonne 3.5-base and 3.5-think?` | two articles in one answer |
| `Which articles use random forests?` | retrieval across the 2021–22 archive by method |
| `Who writes this site and how do I get in touch?` | `site_notes/`, and third-person voice |
| `What does the site say about quantum computing?` | **should decline** — nothing on it |

That last one is the important one. A confident answer there means grounding is not
holding, and it is the failure that matters most for a public assistant.

---

## 3. Host it on Streamlit Community Cloud

Free, and it deploys straight from a branch — you do not have to merge anything first.

1. Go to [share.streamlit.io](https://share.streamlit.io/) and sign in with the
   GitHub account that owns the repo.
2. **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository** — `PursuitOfDataScience/sage`
   - **Branch** — `claude/chatbot-website-integration-plan-91ibip`
   - **Main file path** — `app.py`
   - **App URL** — pick something like `yu-site-assistant`; this is public.
4. **Advanced settings → Secrets.** Paste the same TOML as above:

   ```toml
   MISTRAL_API_KEY  = "..."
   OPENCODE_API_KEY = "sk-zen-..."
   SAGE_PROFILE     = "site"
   SAGE_MAX_TOKENS  = "1500"
   ```

   Secrets are encrypted, are not in the repo, and are not visible to visitors. They
   can be edited later from the app's ⋮ menu → **Settings → Secrets**; the app reboots
   itself when you save.
5. **Deploy.** First boot installs `requirements.txt`, which takes a couple of
   minutes. The corpus is committed to the repo, so nothing is fetched or built at
   startup — the index is ready in a few seconds after that.
6. Open **Manage app** (bottom right) and check the log for the
   `Sage ready: profile=site` line.

Your existing RCC app is a separate app in the same console, pointing at the same
repo with no `SAGE_PROFILE` in its secrets. The two do not interact.

### Things worth knowing before you share the link

- **The app sleeps after about 12 hours without traffic.** The next visitor sees a
  "Yes, get this app back up!" page and waits ~30 seconds. That is tolerable for a
  link you send someone; it is the main reason this is not yet embedded in the
  website itself.
- **The URL is public and so is the model quota.** Anyone with the link can spend
  your Mistral credit. If you post it widely, start on the Zen free key. There is no
  rate limiting in the app.
- **Uploads are on.** The composer accepts attachments, which is useful for you and
  is an open door on a public URL. To turn it off, drop the `st.file_uploader` block
  in `app.py`.

---

## 4. Keeping the corpus current

`site/` is a committed snapshot, so a new blog post does not appear in the assistant
until it is re-synced. From a checkout with both repos side by side:

```bash
cd sage
python tools/build_site_corpus.py --site ../personal-website
git add site && git commit -m "Sync the website corpus" && git push
```

Community Cloud redeploys on push, so that is the whole loop.

The script prints any permalink it could not verify against the website's own
`public/sitemap.xml`. Posts newer than the last committed Hugo build are always
listed there — that is expected and not an error. It matters when a post you expect
to be *old* appears in that list, which would mean its URL has moved.

To change what the assistant says about you rather than about your writing, edit
`site_notes/about-this-site.md` and re-run the same command.

---

## 5. If something is wrong

| Symptom | Cause |
|---|---|
| "No API key is set" | Neither key reached the app. Check the secret names are exactly `MISTRAL_API_KEY` / `OPENCODE_API_KEY`, at the top level of the TOML with no `[section]` header above them. |
| Maroon UI, "What can I help you with?" | `SAGE_PROFILE` did not arrive. Check the log line; check the value is `"site"` in quotes. |
| "The `site` corpus is empty" | `site/` is missing from the checkout — you are on a branch without it, or a `.gitignore` is excluding it. |
| Answers are cut off mid-sentence | `SAGE_MAX_TOKENS` is too low. Raise it; 1500 is a guide, not a limit. |
| "This model is out of credit" | Expected on a spent Mistral key. Add the Zen key and it fails over by itself. |
| Citations land at the top of a page, not the section | That page declares no anchor for the heading, so the bare page is cited deliberately. Not a bug — a guessed anchor would be worse. |

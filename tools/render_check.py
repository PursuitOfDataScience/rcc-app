#!/usr/bin/env python3
"""Audit static/app.css in a real browser, across every screen, theme and width.

Streamlit often cannot be installed where this repo is worked on, and every UI bug
that has actually shipped here was pure CSS. This renders the stylesheet against a
replica of Streamlit's DOM in headless Chromium and asserts that nothing is
clipped, hidden behind the fixed input bar, overflowing horizontally, wrapping
onto an unwanted extra line, or failing contrast.

It has already caught what reading the CSS did not:
  * the newest answer sitting 131px underneath the fixed chat input;
  * the hero subtitle and all six starter cards wrapping to two lines;
  * a maroon focus ring at 1.73:1 on the dark background.

Usage:
    python tools/render_check.py            # audit; exits non-zero on failure
    python tools/render_check.py -v         # also print every measurement

Both colour schemes are exercised by rewriting the `prefers-color-scheme` block,
because headless Chromium cannot be told which scheme to emulate from the CLI.
Requires a Chromium binary; set SAGE_CHROME to override the path.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

CHROME = os.environ.get(
    "SAGE_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
)
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Streamlit Community Cloud overlays an opaque toolbar over the top of the page.
HOST_BAR = 46
# ...and it is a right-aligned cluster (Share / star / edit / GitHub), not full width.
HOST_BAR_W = 220


def _read(*parts: str) -> str:
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return handle.read()


CSS = _read("static", "app.css")
JS = _read("static", "app.js")
APP = _read("app.py")


def _subtitle() -> str:
    match = re.search(r'class="welcome-subtitle">(.*?)</p>', APP, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else "(missing)"


def _card_labels() -> list[str]:
    block = re.search(r"EXAMPLES = \[(.*?)\n\]", APP, re.S).group(1)
    return [
        f"{icon} {label}"
        for icon, label, _q in re.findall(
            r'\(\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\s*\)', block
        )
    ]


SUBTITLE = _subtitle()
CARDS = _card_labels()


def theme_css(scheme: str) -> str:
    """Force one colour scheme, since the CLI cannot emulate prefers-color-scheme."""
    marker = "@media (prefers-color-scheme: dark) {"
    if scheme == "light":
        # Drop every dark block; light is the base.
        out, index = [], 0
        while True:
            start = CSS.find(marker, index)
            if start == -1:
                out.append(CSS[index:])
                break
            out.append(CSS[index:start])
            depth, pos = 0, start
            while pos < len(CSS):
                if CSS[pos] == "{":
                    depth += 1
                elif CSS[pos] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                pos += 1
            index = pos + 1
        return "".join(out)
    # Dark: make the block unconditional.
    return CSS.replace(marker, "@media all {")


BACKGROUNDS = {"dark": "#0e1117", "light": "#ffffff"}
FOREGROUNDS = {"dark": "#e5e7eb", "light": "#31333f"}


def base_css(scheme: str) -> str:
    return f"""
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: {BACKGROUNDS[scheme]}; color: {FOREGROUNDS[scheme]};
       font-family: "Source Sans Pro", system-ui, sans-serif; }}
[data-testid="stAppViewContainer"] {{ min-height: 100vh; }}
[data-testid="stMain"] {{ overflow: auto; height: 100vh; }}
.block-container {{ padding: 6rem 1rem 10rem; margin: 0 auto; }}
.stMarkdown h1 {{ font-size: 2.75rem; font-weight: 600; line-height: 1.2;
                 padding: 1.25rem 0 1rem; margin: 0; }}
.stMarkdown h2 {{ font-size: 1.75rem; line-height: 1.3; margin: 0 0 .5rem; }}
.stMarkdown p {{ margin: 0 0 1rem; }}
.stMarkdown pre {{ background: {'#262730' if scheme == 'dark' else '#f0f2f6'};
                  padding: 1rem; border-radius: 8px; overflow-x: auto; margin: 0 0 1rem; }}
.stMarkdown code {{ font-family: monospace; }}
.element-container {{ width: 100%; }}
[data-testid="stVerticalBlock"] {{ display: flex; flex-direction: column; }}
[data-testid="stHorizontalBlock"] {{ display: flex; flex-direction: row; }}
[data-testid="stColumn"] {{ flex: 1; min-width: 0; }}
.stButton button {{ width: 100%; padding: .4rem .75rem; border-radius: 8px;
   background: {'#262730' if scheme == 'dark' else '#fff'};
   color: inherit; border: 1px solid {'#3a3b46' if scheme == 'dark' else '#d5d6d8'};
   font: inherit; cursor: pointer; }}
.stButton button p {{ margin: 0; }}
[data-testid="stBottomBlockContainer"] {{ position: fixed; bottom: 0; left: 0; right: 0;
   background: {BACKGROUNDS[scheme]}; padding: 1rem; }}
.stChatInput > div {{ background: {'#262730' if scheme == 'dark' else '#f0f2f6'}; }}
.stChatInput textarea {{ width: 100%; background: transparent; border: 0;
                        color: inherit; font: inherit; resize: none; }}
.stChatMessage {{ display: flex; }}
/* A popover trigger is a button, and Streamlit gives it the same base styling as
   st.button. Modelled explicitly because the markup is not `.stButton`, so the
   rule above does not reach it — and an unstyled button would measure smaller
   than the real one and hide an overflow. */
[data-testid="stPopover"] button {{ padding: .4rem .75rem; border-radius: 8px;
   background: {'#262730' if scheme == 'dark' else '#fff'};
   color: inherit; border: 1px solid {'#3a3b46' if scheme == 'dark' else '#d5d6d8'};
   font: inherit; cursor: pointer; }}
[data-testid="stPopover"] button p {{ margin: 0; }}
#host-bar {{ position: fixed; top: 0; right: 0; width: {HOST_BAR_W}px;
            height: {HOST_BAR}px; background: {BACKGROUNDS[scheme]}; z-index: 9999; }}
"""


def _cards_html() -> str:
    rows = ""
    for a, b in ((0, 1), (2, 3), (4, 5)):
        rows += f"""<div data-testid="stHorizontalBlock">
  <div data-testid="stColumn"><div class="st-key-example-card-{a} element-container">
    <div class="stButton"><button><p>{CARDS[a]}</p></button></div></div></div>
  <div data-testid="stColumn"><div class="st-key-example-card-{b} element-container">
    <div class="stButton"><button><p>{CARDS[b]}</p></button></div></div></div>
</div>"""
    return rows


TOPBAR = """<div class="st-key-topbar element-container">
  <div data-testid="stHorizontalBlock">
    <div data-testid="stColumn"><div data-testid="stPopover"><div class="stPopover">
      <button><p>Zen · deepseek-v4-flash-free</p></button>
    </div></div></div>
    <div data-testid="stColumn"><div class="stButton"><button><p>ℹ️</p></button></div></div>
    <div data-testid="stColumn"><div class="stButton"><button><p>🗑️</p></button></div></div>
  </div></div>"""


def answer_block(index: int) -> str:
    return f"""
<div class="element-container"><div class="stMarkdown">
  <div class="user-message"><div class="user-bubble">How do I request a GPU for a
  batch job on Midway3, and what partition should I use?</div></div>
</div></div>
<div class="st-key-answer-{index} element-container"><div class="stChatMessage">
 <div></div>
 <div class="stMarkdown">
  <h2>Requesting a GPU</h2>
  <p>Add <code>--gres=gpu:1</code> to your script and submit to the
  <code>gpu</code> partition.</p>
  <pre><code>#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --time=04:00:00
#SBATCH --mem=32G
module load cuda/11.8
python train.py --epochs 100 --batch-size 64 --output /scratch/midway3/$USER/run</code></pre>
 </div></div>
 <div class="sources"><span class="sources-label">Sources</span>
   <a class="source-chip" href="#">Batch jobs — GPU jobs<span class="source-kind">docs</span></a>
   <a class="source-chip" href="#">Partitions — Partition QoS<span class="source-kind">docs</span></a>
 </div>
 <div class="sources"><span class="sources-label">Related</span>
   <a class="source-chip" href="#">Large-Memory Jobs</a>
   <a class="source-chip" href="#">Checking job status</a>
 </div>
</div>"""


# app.py injects this on the welcome screen only (see the comment there).
LANDING_OVERRIDE = ("<style>[data-testid='stMainBlockContainer'], "
                    ".main .block-container{padding-bottom: 10rem !important;}</style>")

SCENARIOS = {
    "landing": LANDING_OVERRIDE + TOPBAR + f"""
<div class="element-container"><div class="stMarkdown">
  <div class="welcome">
    <h1 class="welcome-title">What can I help you with?</h1>
    <p class="welcome-subtitle">{SUBTITLE}</p>
  </div></div></div>
<div class="st-key-examples element-container">{_cards_html()}</div>""",
    "answer": TOPBAR + '<div class="element-container"><div class="stMarkdown">'
    '<div class="chat-container"></div></div></div>' + answer_block(0),
    "long-chat": TOPBAR + '<div class="element-container"><div class="stMarkdown">'
    '<div class="chat-container"></div></div></div>'
    + "".join(answer_block(i) for i in range(6)),
    "error": TOPBAR + '<div class="element-container"><div class="stMarkdown">'
    '<div class="chat-container"></div></div></div>'
    + """
<div class="element-container"><div class="stMarkdown">
  <div class="user-message"><div class="user-bubble">How do I run PyTorch on GPUs?</div></div>
</div></div>
<div class="element-container"><div class="stMarkdown">
  <div class="error-card" role="alert">
    <div class="error-title">Could not complete that request</div>
    <div class="error-body">This model is out of credit or its quota is used up.
      Switch to another model and try again.</div>
  </div></div></div>
<div class="st-key-error-actions element-container">
 <div data-testid="stHorizontalBlock">
  <div data-testid="stColumn"><div class="st-key-retry element-container">
    <div class="stButton"><button><p>↻ Try again</p></button></div></div></div>
  <div data-testid="stColumn"><div class="st-key-switch-model element-container">
    <div class="stButton"><button><p>→ Use Zen · deepseek-v4-flash-free</p></button></div></div></div>
 </div></div>""",
}

# Elements every scenario should keep clear of the chrome, and their line budgets.
LINE_LIMITS = {
    ".welcome-subtitle": 1,
    # Two lines is fine for an error action; three means the label no longer fits
    # its column and should be shortened rather than allowed to sprawl.
    ".st-key-retry button p": 1, ".st-key-switch-model button p": 2,
    **{f".st-key-example-card-{i} button p": 1 for i in range(6)},
}

MEASURE = """
<script>
function parts(c) {
  var m = (c || '').match(/[\\d.]+/g);
  if (!m || m.length < 3) return null;
  return [+m[0], +m[1], +m[2], m.length > 3 ? +m[3] : 1];
}
function over(fg, bg) {           // composite a translucent layer onto an opaque one
  var a = fg[3];
  return [fg[0] * a + bg[0] * (1 - a), fg[1] * a + bg[1] * (1 - a),
          fg[2] * a + bg[2] * (1 - a), 1];
}
function ratio(fgRaw, bgRaw) {
  var b = parts(bgRaw) || [255, 255, 255, 1];
  var f = parts(fgRaw) || [0, 0, 0, 1];
  if (f[3] < 1) f = over(f, b);   // translucent text must be composited first
  function lum(v3) {
    var m = v3.slice(0, 3).map(function (v) {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];
  }
  var x = lum(f), y = lum(b);
  return Math.round(((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)) * 100) / 100;
}
// Effective background: composite every translucent layer up the tree. A flat
// backgroundColor read misses gradients entirely, which made the maroon user
// bubble measure as white-on-white (1:1).
function solidBg(el) {
  var stack = [];
  for (var n = el; n; n = n.parentElement) {
    var cs = getComputedStyle(n);
    var img = cs.backgroundImage || '';
    if (img.indexOf('gradient') !== -1) {
      var g = img.match(/rgba?\\([^)]*\\)/);
      if (g) { stack.push(parts(g[0])); break; }
    }
    var c = parts(cs.backgroundColor);
    if (c && c[3] > 0) { stack.push(c); if (c[3] === 1) break; }
  }
  var base = parts(getComputedStyle(document.body).backgroundColor) || [255,255,255,1];
  if (!stack.length || stack[stack.length - 1][3] < 1) stack.push(base);
  var out = stack.pop();
  while (stack.length) out = over(stack.pop(), out);
  return 'rgb(' + Math.round(out[0]) + ',' + Math.round(out[1]) + ',' + Math.round(out[2]) + ')';
}
function box(sel) {
  var el;
  if (sel.indexOf('last:') === 0) {
    var all = document.querySelectorAll(sel.slice(5));
    el = all.length ? all[all.length - 1] : null;
  } else {
    el = document.querySelector(sel);
  }
  if (!el) return null;
  var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
  var lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
  return {
    top: Math.round(r.top), bottom: Math.round(r.bottom),
    left: Math.round(r.left), right: Math.round(r.right),
    lines: Math.max(1, Math.round(r.height / lh)),
    fontPx: Math.round(parseFloat(cs.fontSize) * 10) / 10,
    overflowX: el.scrollWidth - el.clientWidth,
    contrast: ratio(cs.color, solidBg(el))
  };
}
var main = document.querySelector('[data-testid="stMain"]');
if (window.__scrollBottom && main) main.scrollTop = main.scrollHeight;
function snapshot() {
  var out = {viewport: {w: innerWidth, h: innerHeight}, hostBar: HOSTBAR,
           scrolled: main ? Math.round(main.scrollTop) : 0,
           docOverflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
           els: {}};
  SELECTORS.forEach(function (s) { out.els[s] = box(s); });
  document.title = JSON.stringify(out);
}
// Give app.js's requestAnimationFrame + interval work time to settle.
setTimeout(snapshot, 700);
</script>
"""

# The model picker's trigger. Named because two checks below treat it specially.
PICKER = '.st-key-topbar [data-testid="stPopover"] button'

SELECTORS = [
    ".welcome-title", ".welcome-subtitle", ".user-bubble", "last:.user-bubble",
    ".error-card",
    ".error-title", ".error-body", ".ai-disclaimer", ".sources-label",
    ".source-chip", ".st-key-answer-5", ".st-key-answer-0", ".stChatMessage pre",
    ".stChatMessage code", '[data-testid="stBottomBlockContainer"]',
    ".st-key-topbar button",
    # The rightmost control in the bar. With a model name in it the bar is far
    # wider than it was, so it can now reach the host toolbar on narrow screens.
    "last:.st-key-topbar button",
    PICKER,
    # The error card's actions. The switch one carries a whole model name, so it
    # is the widest button in the app and the first thing to overflow at 360px.
    ".st-key-retry button p", ".st-key-switch-model button p",
] + [f".st-key-example-card-{i} button p" for i in range(6)]


def page(body: str, scheme: str, scroll: bool, generating: bool = False) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{base_css(scheme)}</style><style>{theme_css(scheme)}</style></head><body>
<div id="host-bar"></div>
<div data-testid="stAppViewContainer">
  <div data-testid="stMain" class="main">
    <div data-testid="stMainBlockContainer" class="block-container">
      <div data-testid="stVerticalBlock">{body}</div></div></div>
  <div data-testid="stBottomBlockContainer">
    <div class="stChatInput"><div><textarea placeholder="Ask anything about RCC…"></textarea></div></div>
    <p class="ai-disclaimer">Sage can make mistakes and cannot see your account or jobs.
       Verify commands against the linked docs.</p>
  </div></div>
{'<div id="processing-signal" hidden></div>' if generating else ''}
<script>window.__scrollBottom = {str(scroll).lower()};</script>
{'<script>' + JS + '</script>' if generating else ''}
{MEASURE.replace("HOSTBAR", str(HOST_BAR)).replace("SELECTORS", json.dumps(SELECTORS))}
</body></html>"""


def render(name, html, width, height, shot=False):
    path = os.path.join(HERE, f"{name}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    cmd = [CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           f"--window-size={width},{height}", "--virtual-time-budget=1500"]
    if shot:
        cmd.append(f"--screenshot={os.path.join(HERE, name + '.png')}")
    cmd += ["--dump-dom", f"file://{path}"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    start, end = out.find("<title>"), out.find("</title>")
    if start == -1:
        return None
    import html as _html

    # The payload rides back in <title>, so every entity has to come back out —
    # `&gt;` in particular, or any selector containing ">" gets a mangled key.
    return json.loads(_html.unescape(out[start + 7 : end]))


def audit(data, scenario, scheme, width, scrolled: bool, generating=False) -> list[str]:
    problems, els = [], data["els"]
    where = f"{scenario}/{scheme}/{width}px"

    if data["docOverflowX"] > 0:
        problems.append(f"{where}: page scrolls sideways by {data['docOverflowX']}px")

    bar = els.get('[data-testid="stBottomBlockContainer"]')
    for sel, b in els.items():
        if not b:
            continue
        # Only meaningful at rest: once the page is scrolled, content passing
        # beneath a fixed host overlay is inherent, not an app defect. What must
        # never happen is content being unreachable — covered by the input-bar
        # check below, which only runs in the scrolled state.
        if (not scrolled and b["top"] < data["hostBar"] and b["bottom"] > 0
                and b["right"] > width - HOST_BAR_W):
            problems.append(
                f"{where}: {sel} collides with the host toolbar "
                f"({data['hostBar'] - b['top']}px under it)"
            )
        # The picker ellipsing a long model id is intended, and <pre> scrolls.
        if b["overflowX"] > 1 and "pre" not in sel and sel != PICKER:
            problems.append(f"{where}: {sel} overflows horizontally by {b['overflowX']}px")
        limit = LINE_LIMITS.get(sel)
        if limit and b["lines"] > limit and width >= 641:
            problems.append(f"{where}: {sel} wraps to {b['lines']} lines (want {limit})")
        # Small text needs 4.5:1; >=18.66px counts as large text at 3:1.
        if b["contrast"] and "chip" not in sel:
            need = 3.0 if b["fontPx"] >= 18.66 else 4.5
            if b["contrast"] < need and sel not in (".welcome-title",):
                problems.append(
                    f"{where}: {sel} contrast {b['contrast']}:1 (needs {need}:1)"
                )

    # A zero-width picker is the exact bug that shipped twice: present in the DOM,
    # invisible on screen. 80px is narrower than any real label, so anything below
    # it means the control collapsed rather than merely being tight.
    picker = els.get(PICKER)
    if picker and picker["right"] - picker["left"] < 80:
        problems.append(
            f"{where}: the model picker is only "
            f"{picker['right'] - picker['left']}px wide (collapsed)"
        )

    if generating:
        # The question must stay on screen while its answer streams in. Pinning to
        # the document bottom used to scroll it clean off the top.
        asked = els.get("last:.user-bubble")
        if asked and asked["top"] < data["hostBar"]:
            problems.append(
                f"{where}: the question is {data['hostBar'] - asked['top']}px above "
                "the fold while its answer generates"
            )

    newest = els.get(".st-key-answer-5") or els.get(".st-key-answer-0") or els.get(".error-card")
    if scrolled and not generating and newest and bar and newest["bottom"] > bar["top"]:
        problems.append(
            f"{where}: newest content is {newest['bottom'] - bar['top']}px under the input bar"
        )
    return problems


def main() -> int:
    verbose = "-v" in sys.argv
    widths = [(1440, 1080), (1263, 900), (966, 626), (768, 900), (414, 896)]
    failures: list[str] = []
    checked = 0

    for scenario, body in SCENARIOS.items():
        for scheme in ("dark", "light"):
            for width, height in widths:
                # Every screen is checked twice: as the user lands on it, and
                # scrolled to the bottom the way app.js leaves it after a reply.
                # at rest / user-scrolled / generating (app.js driving the scroll)
                states = ([(False, False)] if scenario == "landing"
                          else [(False, False), (True, False), (False, True)])
                for scroll, generating in states:
                    suffix = "-scrolled" if scroll else ("-generating" if generating else "")
                    name = f"{scenario}-{scheme}-{width}{suffix}"
                    data = render(name, page(body, scheme, scroll, generating), width, height,
                                  shot=(scheme == "dark" and width == 1263 and not scroll
                                        and not generating))
                    if data is None:
                        failures.append(f"{name}: render failed")
                        continue
                    checked += 1
                    failures.extend(
                        audit(data, scenario, scheme, width,
                              scroll or generating, generating)
                    )
                    if verbose:
                        print(f"\n--- {name} (usable {data['viewport']['h']}px, "
                              f"scrollTop {data['scrolled']}) ---")
                        for sel, b in data["els"].items():
                            if b:
                                print(f"  {sel:42} top={b['top']:>5} "
                                      f"lines={b['lines']} contrast={b['contrast']}")

    print(f"\nChecked {checked} renders across {len(SCENARIOS)} screens, "
          f"2 themes, {len(widths)} widths.")
    if failures:
        print(f"\n{len(failures)} problem(s):")
        for problem in dict.fromkeys(failures):
            print(f"  ✗ {problem}")
        return 1
    print("No layout or contrast problems found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

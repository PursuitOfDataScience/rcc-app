#!/usr/bin/env python3
"""Audit static/app.css in a real browser, across every screen, theme and width.

Streamlit often cannot be installed where this repo is worked on, and every UI bug
that has actually shipped here was pure CSS. This renders the stylesheet against a
replica of Streamlit's DOM in headless Chromium and asserts that nothing is
clipped, hidden behind the fixed input bar, overflowing horizontally, wrapping
onto an unwanted extra line, painted on top of a control, too close to the message
above it, adrift above the input bar, or failing contrast.

It has already caught what reading the CSS did not:
  * the newest answer sitting 131px underneath the fixed chat input;
  * the hero subtitle and all six starter cards wrapping to two lines;
  * a maroon focus ring at 1.73:1 on the dark background;
  * the controls under the input painted over by Streamlit's own pinned bar;
  * 19–25px between a question and its answer, and up to 566px of nothing
    between the last message and the input box;
  * the slack above a short conversation growing by 42px a frame, because a media
    query was quietly overriding the padding it was being applied to;
  * the caveat line under the input rendering at Streamlit's own paragraph size and
    wrapping onto a second line, because a bare `.ai-disclaimer` is one class where
    the rule it was losing to is a class and a type — and this replica had no
    paragraph size of its own for it to lose to;
  * that same slack being applied while an answer was still generating, which put
    the question halfway down the window with the reply arriving into the bottom of
    it. Both of those needed a model added here before they could be caught.

The dead space at the end of a conversation outlived three rounds of fixes because
of a line in this file: the bar was modelled `position: fixed`, the stylesheet
reserved a bar's worth of room at the end of the page on the strength of it, and
that reservation *was* the dead space. Streamlit also ships it `sticky`, in the
flow, where it needs no room reserved at all. Four of the screens here are
rendered the first way and three the second, and app.js asks the browser which one
it is looking at rather than trusting either.

It also, for a while, cheerfully passed a top bar that was completely unusable,
because the replica modelled Streamlit's header as a small right-aligned box
when it is really a full-width strip that takes every click underneath it. Two
checks came out of that and are the ones worth keeping honest:

  * every control is hit-tested with `elementFromPoint`, so "in the DOM with a
    sensible rectangle" is no longer mistaken for "a user can click it";
  * whatever the harness cannot see, it must not silently model away — a wrong
    model is worse than no model, because it reads as a pass.

Five states per screen — the first frame with no app.js at all, at rest, scrolled to
the end, mid-generation, and just finished — except the two landing screens, which
have no turn to be in the middle of and render the first two, and the mid-answer
screen, which *is* the generating state and renders only that.

The first of those states is the layout the stylesheet's own fallbacks produce — a
frame every user sees, and where CI once found an answer 2px under the input. In the
rest the real app.js runs, because the room the page leaves for the bar and the slack
above a short conversation are both measurements it publishes; the last two states
additionally exercise the per-turn scroll pin and the settle that closes what it
leaves behind.

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

# Streamlit's own header (`[data-testid="stHeader"]`) is a FULL-WIDTH fixed strip
# across the top of every app at a z-index far above anything a stylesheet sets.
# It is usually transparent, so it hides nothing — but it is on top, so it takes
# the clicks for everything underneath it. Anything interactive placed in this
# band is unreachable, however good it looks.
#
# This used to be modelled as a 220px right-aligned box, on the reasoning that
# Community Cloud's visible controls are right-aligned. That was wrong, and it
# is why the top bar passed every render while being unusable in the real app.
HOST_BAR = 60
# The part that also paints: the Community Cloud control cluster, right-aligned.
HOST_BAR_W = 220
# Streamlit's header sits at this z-index. Its pinned bottom container is not
# documented as being in the same band, but it is Streamlit chrome and it is
# fixed over the page, so it is modelled as if it were: the strip of controls
# app.py pins inside that band has to outrank whatever is really there, and a
# harness that assumed the friendlier number would pass a dead picker again.
HOST_Z = 999990


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


def _disclaimer() -> str:
    """The line under the input, read from app.py so the two cannot drift apart.

    Loud on failure rather than falling back to a placeholder. It used to return
    "(missing)" when the regex missed, and when `DISCLAIMER` was shortened from a
    parenthesised pair of strings to one literal, that is what every render
    measured: nine characters where the app has sixty. The line-count check passed
    on text the app does not contain, which is the harness's own cardinal sin —
    a wrong model reads as a pass.
    """
    # Flags per pattern: `re.S` belongs to the parenthesised form only. Shared, it
    # let `.*` in the single-literal form run to the end of the file, and the
    # "disclaimer" became app.py itself.
    for pattern, flags in (
        (r"^DISCLAIMER = \((.*?)\n\)", re.S | re.M),
        (r'^DISCLAIMER = ("[^"]*")\s*$', re.M),
    ):
        match = re.search(pattern, APP, flags)
        if match:
            return "".join(re.findall(r'"([^"]*)"', match.group(1)))
    raise SystemExit(
        "render_check: could not find DISCLAIMER in app.py. Fix this parser rather "
        "than letting every render measure a placeholder."
    )


SUBTITLE = _subtitle()
CARDS = _card_labels()
DISCLAIMER = _disclaimer()
# Read from app.js so the two can never drift apart.
TOP_GAP = int(re.search(r"var TOP_GAP = (\d+)", JS).group(1))


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
/* Streamlit sizes markdown paragraphs itself, at a specificity of (0,1,1) — one
   class and one type. A bare `.ai-disclaimer` rule is (0,1,0) and loses to it, so
   the line under the input rendered at Streamlit's size rather than the one the
   stylesheet asked for, and wrapped onto a second line. Modelled here because the
   replica had no paragraph size at all, which let that rule win by default. */
.stMarkdown p {{ margin: 0 0 1rem; font-size: 1rem; line-height: 1.6; }}
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
/* The pinned input bar, modelled BOTH ways — see `page(sticky=…)`. `fixed` paints
   it over the conversation, so the page must leave a bar's worth of room at the end
   or the newest answer hides underneath; `sticky` puts it in the flow at the end of
   the scrolling area, where it takes its own space and reserving that room again is
   dead space. Streamlit has shipped both, this harness asserted the first for a
   year, and app.js now asks the browser which one it is looking at. */
[data-testid="stBottomBlockContainer"] {{
   background: {BACKGROUNDS[scheme]}; padding: 1rem; z-index: {HOST_Z}; }}
.bar-fixed [data-testid="stBottomBlockContainer"] {{ position: fixed; bottom: 0;
   left: 0; right: 0; }}
.bar-sticky [data-testid="stBottom"] {{ position: sticky; bottom: 0;
   z-index: {HOST_Z}; }}
/* Sticky alone would leave the input floating mid-page whenever the conversation
   is short — `bottom: 0` only offsets an element that would otherwise scroll out
   of view. So the in-flow version has to come with a column that fills the height
   and a block that grows into it, which is what puts the bar at the bottom of a
   short page and, incidentally, what makes any padding this stylesheet reserves
   for the bar pure dead space above it. */
.bar-sticky [data-testid="stMain"] {{ display: flex; flex-direction: column; }}
.bar-sticky .block-container {{ flex: 1 0 auto; }}
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
/* Streamlit's header: full width, transparent, and above everything. */
[data-testid="stHeader"] {{ position: fixed; top: 0; left: 0; right: 0;
   height: {HOST_BAR}px; background: transparent; z-index: {HOST_Z}; }}
/* The host's own control cluster, which additionally paints. */
#host-bar {{ position: fixed; top: 0; right: 0; width: {HOST_BAR_W}px;
            height: {HOST_BAR}px; background: {BACKGROUNDS[scheme]}; z-index: 999991; }}
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


def strip(clear: bool = True, wrapped: bool = True) -> str:
    """The controls under the input, and the AI disclaimer under those.

    Rendered last in the block, where app.py renders it. `clear` is False on the
    landing screen, where there is no conversation to throw away.

    `wrapped` picks which of the two shapes `st.container(key=…)` produces: the
    `st-key-…` class on a wrapper *around* the vertical block, or on the vertical
    block itself. Which one Streamlit emits is an implementation detail that has
    changed between versions, and modelling only the wrapped shape is how a
    stylesheet that stacked the three controls in a column in the real app passed
    170 renders here in a row. Both shapes are rendered now, so a rule that only
    reaches one of them fails the audit.
    """
    trash = ('<div class="element-container"><div class="stButton">'
             "<button><p>🗑️</p></button></div></div>") if clear else ""
    # Disclaimer, Clear, picker — app.py's order, and the order that decides the
    # line: the disclaimer takes the space on the left and the picker ends up in
    # the corner. All three are one row now; the disclaimer had a second row to
    # itself until two rows of furniture under the input were one too many.
    controls = f"""
    <div class="element-container"><div class="stMarkdown">
      <p class="ai-disclaimer">{DISCLAIMER} <a href="#">RCC Help Desk</a></p>
    </div></div>
    {trash}
    <div class="element-container"><div data-testid="stPopover"><div class="stPopover">
      <button><p>Zen · deepseek-v4-flash-free</p></button>
    </div></div></div>"""
    if wrapped:
        return f"""<div class="st-key-composer-strip" data-testid="stVerticalBlockBorderWrapper">
 <div data-testid="stVerticalBlock">{controls}</div></div>"""
    return f"""<div class="st-key-composer-strip" data-testid="stVerticalBlock">
 {controls}</div>"""


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


CHAT_MARKER = ('<div class="element-container"><div class="stMarkdown">'
               '<div class="chat-container"></div></div></div>')

# One question and a two-line reply: the shape that used to leave 121–566px of
# nothing between the answer and the input box, because the page was shorter than
# the window and there was no scroll left for app.js to close the gap with. The
# failover notice is on it because that is when a reader is looking at the bottom.
SHORT_ANSWER = """
<div class="element-container"><div class="stMarkdown">
  <div class="user-message"><div class="user-bubble">How do I submit a batch job with
  sbatch?</div></div>
</div></div>
<div class="st-key-answer-0 element-container"><div class="stChatMessage">
 <div></div>
 <div class="stMarkdown"><p>Submit it with <code>sbatch ./my_job.sbatch</code>, and the
 scheduler prints the job id it assigned.</p></div></div>
 <div class="sources"><span class="sources-label">Sources</span>
   <a class="source-chip" href="#">Batch jobs<span class="source-kind">docs</span></a>
 </div>
</div>
<div class="element-container"><div class="stMarkdown">
  <div class="notice">Mistral · small-latest was unavailable (out of credit), so Zen ·
  deepseek-v4-flash-free answered instead. Pick a different one from the model button
  under the input box.</div></div></div>"""

LANDING = f"""
<div class="element-container"><div class="stMarkdown">
  <div class="welcome">
    <h1 class="welcome-title">What can I help you with?</h1>
    <p class="welcome-subtitle">{SUBTITLE}</p>
  </div></div></div>
<div class="st-key-examples element-container">{_cards_html()}</div>"""

def _check_balanced(scenarios: dict) -> None:
    """Every fixture must close every div it opens.

    One missing `</div>` in the mid-answer screen re-parented everything after it:
    Streamlit's bottom container was parsed *inside* the block that holds the
    conversation instead of beside it, so the in-flow bar landed mid-window with
    553px of empty page below it. Nothing failed — the checks that would have
    noticed only run in states that screen does not render — so the screen added to
    catch a bug was structurally unable to see it. A replica that is not the shape
    it claims to be is the one failure mode this harness cannot afford.
    """
    for name, body in scenarios.items():
        opened = len(re.findall(r"<div\b", body))
        closed = len(re.findall(r"</div\s*>", body))
        if opened != closed:
            raise SystemExit(
                f"render_check: the {name!r} fixture opens {opened} divs and closes "
                f"{closed}. Every render of it measures a DOM the app never has."
            )


# Which screens render the bar in the flow rather than fixed over the page. Split
# across the scenarios rather than doubling every render: both ways of pinning it
# are then audited at every width, in both themes, in every state. Whichever
# Streamlit is doing, one of these screens is looking at it.
STICKY_BAR = {"landing-flat", "answer", "long-chat"}

# What is actually on screen while an answer is being generated: the question, and
# a status row where the answer will go. The other screens render a *finished*
# answer with the processing marker set, which is a much taller page — so the slack
# app.js puts above a short conversation stayed small there and the check below had
# nothing to catch. On this screen it is the whole page, which is how the question
# ended up halfway down the window with the answer arriving underneath it.
IN_FLIGHT = """
<div class="element-container"><div class="stMarkdown">
  <div class="user-message"><div class="user-bubble">How do I connect to Midway via
  SSH?</div></div>
</div></div>
<div class="element-container"><div class="stChatMessage">
 <div></div>
 <div class="stMarkdown">
  <div class="status-row" role="status" aria-live="polite">
    <span class="status-dot" aria-hidden="true"></span>
    <span class="status-text">Reading SSH (Secure Shell)</span>
    <span class="status-dots" aria-hidden="true"><span></span><span></span><span></span></span>
  </div>
 </div></div></div>"""

# The strip's container shape alternates across the screens, so both shapes are
# audited at every width, in both themes, in every state.
SCENARIOS = {
    "landing": LANDING + strip(clear=False, wrapped=True),
    "landing-flat": LANDING + strip(clear=False, wrapped=False),
    "answer": CHAT_MARKER + answer_block(0) + strip(wrapped=False),
    "short-answer": CHAT_MARKER + SHORT_ANSWER + strip(),
    "long-chat": CHAT_MARKER
    + "".join(answer_block(i) for i in range(6))
    + strip(wrapped=False),
    "in-flight": CHAT_MARKER + IN_FLIGHT + strip(wrapped=False),
    "error": CHAT_MARKER
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
 </div></div>"""
    + strip(),
}

# Elements every scenario should keep clear of the chrome, and their line budgets.
_check_balanced(SCENARIOS)

LINE_LIMITS = {
    ".welcome-subtitle": 1,
    # Two lines is fine for an error action; three means the label no longer fits
    # its column and should be shortened rather than allowed to sprawl.
    ".st-key-retry button p": 1, ".st-key-switch-model button p": 2,
    # One line, sharing it with the controls. It is a standing caveat that should
    # be findable and ignorable; at two lines it is a paragraph at the bottom of
    # the window, which is what it looked like when Streamlit's own paragraph size
    # won over this stylesheet's.
    ".ai-disclaimer": 1,
    # NB: the loop below gates line limits on width >= 641, because at phone widths
    # nearly everything wraps and a limit there would be noise. That gate made this
    # entry dead at 414px — the one width where this line does wrap — so the narrow
    # budget is stated separately in NARROW_LINE_LIMITS rather than left unenforced.
    **{f".st-key-example-card-{i} button p": 1 for i in range(6)},
}

# Line budgets that apply BELOW 641px too, where the general gate does not.
NARROW_LINE_LIMITS = {".ai-disclaimer": 2}

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
    contrast: ratio(cs.color, solidBg(el)),
    hit: hitTest(el, r)
  };
}
// Is this element the thing a user's click would actually land on? Geometry
// alone cannot tell you: the top bar had a perfectly good rectangle for 100
// renders while sitting underneath Streamlit's full-width header, which is
// transparent (so it looked fine) and on top (so it took every click).
// '' means yes; anything else names what is in the way.
function hitTest(el, r) {
  if (r.width < 1 || r.height < 1) return 'zero-sized';
  var x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return 'offscreen';
  var top = document.elementFromPoint(x, y);
  if (!top) return 'nothing painted there';
  if (el.contains(top) || top.contains(el)) return '';
  return (top.getAttribute('data-testid') || top.id ||
          top.className || top.tagName || 'something').toString().slice(0, 60);
}
var main = document.querySelector('[data-testid="stMain"]');
if (window.__scrollBottom && main) main.scrollTop = main.scrollHeight;
// Leave the view where app.js's per-turn pin would have left it, so the settle
// that runs once the answer lands has something to actually close.
if (window.__pinLast && main) {
  var asked = document.querySelectorAll('.user-message');
  var lastAsked = asked[asked.length - 1];
  if (lastAsked) main.scrollTop = Math.max(0, Math.min(
    lastAsked.getBoundingClientRect().top + main.scrollTop - TOPGAP,
    main.scrollHeight - main.clientHeight));
}
function snapshot() {
  // The two custom properties app.js publishes. Reported so a failed gap check
  // says whether the reservation was measured or still on the CSS fallback —
  // "2px under the input bar" with no numbers took a while to place.
  var root = getComputedStyle(document.documentElement);
  var out = {viewport: {w: innerWidth, h: innerHeight}, hostBar: HOSTBAR,
           scrolled: main ? Math.round(main.scrollTop) : 0,
           // Whether there is anywhere to scroll to. A conversation shorter than
           // the window sits at the bottom of the space reserved for it, so if
           // that reservation is wrong it lands under the input with no scroll
           // available to reveal it.
           canScroll: !!main && main.scrollHeight - main.clientHeight > 1,
           docOverflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
           reserved: {bar: root.getPropertyValue('--bar-h').trim(),
                      strip: root.getPropertyValue('--strip-h').trim()},
           els: {}};
  SELECTORS.forEach(function (s) { out.els[s] = box(s); });
  document.title = JSON.stringify(out);
}
// Give app.js's requestAnimationFrame + interval work time to settle.
setTimeout(snapshot, 700);
</script>
"""

# The model picker's trigger. Named because three checks below treat it specially:
# collapsed width, whether it is inside the strip pinned for it, and reachability.
PICKER = '.st-key-composer-strip [data-testid="stPopover"] button'
# The strip the controls sit in, and the input it must never cover.
STRIP = ".st-key-composer-strip"
INPUT = ".stChatInput textarea"

SELECTORS = [
    ".welcome-title", ".welcome-subtitle", ".user-bubble", "last:.user-bubble",
    ".error-card", ".notice", ".st-key-error-actions",
    ".error-title", ".error-body", ".ai-disclaimer", ".sources-label",
    ".source-chip", ".st-key-answer-5", ".st-key-answer-0", ".stChatMessage pre",
    ".stChatMessage code", '[data-testid="stBottomBlockContainer"]',
    STRIP, INPUT,
    ".st-key-composer-strip button",
    # The rightmost control in the strip, so the row is measured end to end: with
    # a model name in it, it is the widest thing under the input.
    "last:.st-key-composer-strip button",
    PICKER,
    # The error card's actions. The switch one carries a whole model name, so it
    # is the widest button in the app and the first thing to overflow at 360px.
    ".st-key-retry button p", ".st-key-switch-model button p",
] + [f".st-key-example-card-{i} button p" for i in range(6)]

# Controls a user has to be able to click. For these, occupying a sensible
# rectangle is not enough — something else must not be on top of them. The input
# is on the list because the strip of controls is pinned in a band the bar above
# it reserves: if the two measurements ever disagree, the strip lands on the
# textarea, and "the box will not take a click" is the worst bug in the app.
INTERACTIVE = {
    PICKER, ".st-key-composer-strip button", "last:.st-key-composer-strip button", INPUT,
    ".st-key-retry button p", ".st-key-switch-model button p",
    *(f".st-key-example-card-{i} button p" for i in range(6)),
}

# The picker ellipses a long model id on purpose, and it is now both the first
# button in the row on the landing screen (no Clear to precede it) and the last one
# everywhere, since the row is right-aligned and it belongs in the corner. So all
# three selectors that can reach it are exempt from the overflow check; the emoji
# button they also reach has nothing to ellipse.
ELLIPSIS_OK = {PICKER, ".st-key-composer-strip button", "last:.st-key-composer-strip button"}

# How far apart things should be, in px. Both ends matter: the first of these was
# reported twice as "barely any spacing between the user and AI messages", at a
# measured 19–25px; the second as "such a big empty space" between the end of an
# answer and the input box, at a measured 121–566px.
GAP_QUESTION_TO_ANSWER = (30, 60)
# Only an upper bound: a reply taller than the window runs off the bottom, and
# that is the reader's to scroll, not dead space.
MAX_TAIL_GAP = 64


def page(body: str, scheme: str, scroll: bool, generating: bool = False,
         pin: bool = False, script: bool = True, sticky: bool = False) -> str:
    """The replica, with or without app.js, and with the bar pinned either way.

    `script=False` is the app's first frame: the stylesheet's own fallback for how
    much room the bar takes, before app.js has measured the real thing. It is a
    state a user sees, and it is the one CI caught an answer 2px underneath the
    input in — the two fallbacks disagreed with each other by 26px and every
    render that ran app.js papered over it.

    `sticky` is the other thing Streamlit does with its bottom container: put it in
    the flow at the end of the scrolling area rather than fixed over the page. This
    replica asserted `fixed` from the day it was written, the stylesheet reserved a
    bar's worth of room at the end of every conversation on the strength of it, and
    that reservation was the dead space three rounds of fixes could not find.
    Nothing here is allowed to model only one of them again.
    """
    bar = ('<div data-testid="stBottom">'
           '<div data-testid="stBottomBlockContainer">'
           '<div class="stChatInput"><div>'
           '<textarea placeholder="Ask anything about RCC…"></textarea>'
           "</div></div></div></div>")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{base_css(scheme)}</style><style>{theme_css(scheme)}</style></head>
<body class="{'bar-sticky' if sticky else 'bar-fixed'}">
<div data-testid="stHeader"></div><div id="host-bar"></div>
<div data-testid="stAppViewContainer">
  <div data-testid="stMain" class="main">
    <div data-testid="stMainBlockContainer" class="block-container">
      <div data-testid="stVerticalBlock">{body}</div></div>
    {bar if sticky else ''}</div>
  {'' if sticky else bar}</div>
{'<div id="processing-signal" hidden></div>' if generating else ''}
<script>window.__scrollBottom = {str(scroll).lower()}; window.__pinLast = {str(pin).lower()};</script>
{'<script>' + JS + '</script>' if script else ''}
{MEASURE.replace("HOSTBAR", str(HOST_BAR)).replace("TOPGAP", str(TOP_GAP)).replace("SELECTORS", json.dumps(SELECTORS))}
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


def audit(data, scenario, scheme, width, state: str) -> list[str]:
    problems, els = [], data["els"]
    where = f"{scenario}/{scheme}/{width}px"
    generating = state == "generating"
    # "unmeasured" is the first frame, so it is at the top of the page like "rest":
    # the host-toolbar collision check below is meaningful in both.
    scrolled = state not in ("rest", "unmeasured")

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
        # (Both selectors that reach the picker trigger are exempt; the trash
        # button, matched by `last:`, is not — it has nothing to ellipse.)
        if b["overflowX"] > 1 and "pre" not in sel and sel not in ELLIPSIS_OK:
            problems.append(f"{where}: {sel} overflows horizontally by {b['overflowX']}px")
        limit = (LINE_LIMITS.get(sel) if width >= 641
                 else NARROW_LINE_LIMITS.get(sel))
        if limit and b["lines"] > limit:
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

    # The controls belong under the input, not on it. The strip is pinned inside a
    # band the bar above reserves from a measurement, so this is the check that
    # the two agree — at every width, in both themes, in every state.
    band, entry = els.get(STRIP), els.get(INPUT)
    if band and entry and band["top"] < entry["bottom"]:
        problems.append(
            f"{where}: the controls strip overlaps the input by "
            f"{entry['bottom'] - band['top']}px"
        )
    if band and picker and picker["top"] < band["top"] - 1:
        problems.append(f"{where}: the model picker is outside the strip pinned for it")

    if generating:
        # The question must stay on screen while its answer streams in. Pinning to
        # the document bottom used to scroll it clean off the top.
        asked = els.get("last:.user-bubble")
        if asked and asked["top"] < data["hostBar"]:
            problems.append(
                f"{where}: the question is {data['hostBar'] - asked['top']}px above "
                "the fold while its answer generates"
            )
        # And not the other way either. The slack that sits a *finished* short
        # conversation above the composer was also being applied to a question with
        # a "Reading…" row under it, which put the question halfway down the window
        # with the answer arriving into the bottom of it and the top half empty.
        # Reported as "way below the top of the page, which looks very off".
        ceiling = round(data["viewport"]["h"] * 0.4)
        if asked and asked["top"] > ceiling:
            problems.append(
                f"{where}: the question is {asked['top']}px down the window while "
                f"its answer generates (want no lower than {ceiling})"
            )

    for sel in INTERACTIVE:
        b = els.get(sel)
        # 'offscreen' is covered by the geometry checks above and is expected for
        # in-flow content once the page is scrolled. What this is here to catch is
        # a control that is on screen with something painted over it.
        if b and b["hit"] and b["hit"] != "offscreen":
            problems.append(f"{where}: {sel} is not clickable — {b['hit']} is on top")

    # The picker is the one control with no second home on the landing screen, so
    # it has to be reachable in every scenario and every scroll state.
    if picker and picker["hit"]:
        problems.append(f"{where}: the model picker is unreachable ({picker['hit']})")

    asked, answered = els.get(".user-bubble"), els.get(".st-key-answer-0")
    if asked and answered:
        gap = answered["top"] - asked["bottom"]
        low, high = GAP_QUESTION_TO_ANSWER
        if not low <= gap <= high:
            problems.append(
                f"{where}: {gap}px between the question and its answer "
                f"(want {low}–{high})"
            )

    # The bottom of the conversation, whatever ended it — a trailing failover
    # notice is part of it, and measuring only the answer above one is how the
    # space under it stayed dead while this harness reported a pass.
    newest = max(
        (b for sel, b in els.items()
         if b and sel in (".st-key-answer-5", ".st-key-answer-0", ".error-card",
                          ".st-key-error-actions", ".notice")),
        key=lambda b: b["bottom"], default=None,
    )
    reserved = data.get("reserved", {})
    # app.js publishes these in px. Still holding the stylesheet's rem fallback in
    # a state that loads app.js means it never ran, and every measured thing below
    # is then auditing a layout the app only has for one frame. Said out loud,
    # because as a gap number it reads like a spacing bug and is not one: it was a
    # `requestAnimationFrame` that never fired in a browser producing no frames.
    if state != "unmeasured" and reserved.get("bar", "").endswith("rem"):
        problems.append(
            f"{where}: app.js never measured the input bar (--bar-h is still "
            f"{reserved.get('bar')})"
        )

    if newest and bar:
        gap = bar["top"] - newest["bottom"]
        # What the page reserved, versus what the bar actually takes. When these
        # disagree the gap checks below are measuring a stale reservation, which
        # is a different bug from a stylesheet that reserved the wrong amount.
        room = (f"reserved --bar-h {reserved.get('bar', '?')} / --strip-h "
                f"{reserved.get('strip', '?')}, bar is really "
                f"{data['viewport']['h'] - bar['top']}px")
        # Scrolled to the very end, nothing may hide under the fixed input — and
        # on a page with nowhere to scroll, nothing may hide under it at all,
        # because the conversation is pinned to the bottom of what was reserved
        # and there is no scroll left to bring it back out.
        if gap < 0 and (state == "scrolled"
                        or (state in ("rest", "unmeasured")
                            and not data.get("canScroll", True))):
            problems.append(
                f"{where}: newest content is {-gap}px under the input bar ({room})"
            )
        # At rest and just-finished are the views a reader is actually left looking
        # at, so they are the ones that must not be a third of a screen of nothing.
        # A negative gap means the reply runs off the bottom, which is theirs to
        # scroll; this is only ever about empty space.
        #
        # Not the first frame: closing this space is app.js's job (it is measured
        # slack, put above the conversation), and that frame's job is only to not
        # hide anything, which the check above covers.
        if state in ("rest", "settled") and gap > MAX_TAIL_GAP:
            problems.append(
                f"{where}: {gap}px of dead space between the last message and the "
                f"input bar (want at most {MAX_TAIL_GAP}; {room})"
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
                # the first frame before app.js has measured the bar, at rest,
                # scrolled to the bottom, mid-generation (app.js pinning the
                # question), and just-finished (app.js closing the dead space the
                # pin left behind).
                if scenario.startswith("landing"):
                    states = ["unmeasured", "rest"]   # no turn to be in the middle of
                elif scenario == "in-flight":
                    states = ["generating"]           # it *is* the mid-turn screen
                else:
                    states = ["unmeasured", "rest", "scrolled", "generating",
                              "settled"]
                for state in states:
                    suffix = "" if state == "rest" else f"-{state}"
                    name = f"{scenario}-{scheme}-{width}{suffix}"
                    html = page(body, scheme, scroll=state == "scrolled",
                                generating=state == "generating",
                                pin=state == "settled",
                                script=state != "unmeasured",
                                sticky=scenario in STICKY_BAR)
                    data = render(name, html, width, height,
                                  shot=(scheme == "dark" and width == 1263
                                        and state == "rest"))
                    if data is None:
                        failures.append(f"{name}: render failed")
                        continue
                    checked += 1
                    failures.extend(audit(data, scenario, scheme, width, state))
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

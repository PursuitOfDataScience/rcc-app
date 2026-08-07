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
    between the last message and the input box.

It also, for a while, cheerfully passed a top bar that was completely unusable,
because the replica modelled Streamlit's header as a small right-aligned box
when it is really a full-width strip that takes every click underneath it. Two
checks came out of that and are the ones worth keeping honest:

  * every control is hit-tested with `elementFromPoint`, so "in the DOM with a
    sensible rectangle" is no longer mistaken for "a user can click it";
  * whatever the harness cannot see, it must not silently model away — a wrong
    model is worse than no model, because it reads as a pass.

Four states per screen: at rest, scrolled to the end, mid-generation, and just
finished. The real app.js runs in every one of them — the room the page leaves for
the input bar is built from measurements it publishes, so a replica without it
measures a layout the app never has — and the last two additionally exercise the
per-turn scroll pin and the settle that closes the space it leaves behind. (The
landing screen has no turn to be in the middle of, so it renders at rest only.)

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
    """The line under the input. Read from app.py so the two cannot drift apart —
    its line count is what decides how much room the page has to reserve."""
    match = re.search(r"^DISCLAIMER = \((.*?)\n\)", APP, re.S | re.M)
    return "".join(re.findall(r'"([^"]*)"', match.group(1))) if match else "(missing)"


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
   background: {BACKGROUNDS[scheme]}; padding: 1rem; z-index: {HOST_Z}; }}
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


def strip(clear: bool = True) -> str:
    """The controls under the input, and the AI disclaimer under those.

    Rendered last in the block, where app.py renders it, and as two nested keyed
    containers, which is what `st.container(key=…)` inside another one produces —
    the stylesheet turns the inner one into a row and that nesting is the thing
    it has to reach through. `clear` is False on the landing screen, where there
    is no conversation to throw away.
    """
    trash = ('<div class="element-container"><div class="stButton">'
             "<button><p>🗑️</p></button></div></div>") if clear else ""
    return f"""<div class="st-key-composer-strip" data-testid="stVerticalBlockBorderWrapper">
 <div data-testid="stVerticalBlock">
  <div class="st-key-controls" data-testid="stVerticalBlockBorderWrapper">
   <div data-testid="stVerticalBlock">
    <div class="element-container"><div data-testid="stPopover"><div class="stPopover">
      <button><p>Zen · deepseek-v4-flash-free</p></button>
    </div></div></div>
    <!-- About is a popover too, so the picker's own rules reach its trigger. The
         ellipsis ceiling in particular: modelled as a plain button, an ℹ️ that
         those rules had squashed would render fine here and be wrong in the app. -->
    <div class="element-container"><div data-testid="stPopover"><div class="stPopover">
      <button><p>ℹ️</p></button></div></div></div>
    {trash}
   </div></div>
  <div class="element-container"><div class="stMarkdown">
    <p class="ai-disclaimer">{DISCLAIMER}</p></div></div>
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

SCENARIOS = {
    "landing": f"""
<div class="element-container"><div class="stMarkdown">
  <div class="welcome">
    <h1 class="welcome-title">What can I help you with?</h1>
    <p class="welcome-subtitle">{SUBTITLE}</p>
  </div></div></div>
<div class="st-key-examples element-container">{_cards_html()}</div>"""
    + strip(clear=False),
    "answer": CHAT_MARKER + answer_block(0) + strip(),
    "short-answer": CHAT_MARKER + SHORT_ANSWER + strip(),
    "long-chat": CHAT_MARKER
    + "".join(answer_block(i) for i in range(6))
    + strip(),
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
PICKER = '.st-key-controls [data-testid="stPopover"] button'
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
    ".st-key-controls button",
    # The rightmost control in the strip, so the row is measured end to end: with
    # a model name in it, it is the widest thing under the input.
    "last:.st-key-controls button",
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
    PICKER, ".st-key-controls button", "last:.st-key-controls button", INPUT,
    ".st-key-retry button p", ".st-key-switch-model button p",
    *(f".st-key-example-card-{i} button p" for i in range(6)),
}

ELLIPSIS_OK = {PICKER, ".st-key-controls button"}

# How far apart things should be, in px. Both ends matter: the first of these was
# reported twice as "barely any spacing between the user and AI messages", at a
# measured 19–25px; the second as "such a big empty space" between the end of an
# answer and the input box, at a measured 121–566px.
GAP_QUESTION_TO_ANSWER = (30, 60)
# Only an upper bound: a reply taller than the window runs off the bottom, and
# that is the reader's to scroll, not dead space.
MAX_TAIL_GAP = 64


def page(body: str, scheme: str, scroll: bool, generating: bool = False,
         pin: bool = False, script: bool = True) -> str:
    """The replica, with or without app.js.

    `script=False` is the app's first frame: the stylesheet's own fallback for how
    much room the bar takes, before app.js has measured the real thing. It is a
    state a user sees, and it is the one CI caught an answer 2px underneath the
    input in — the two fallbacks disagreed with each other by 26px and every
    render that ran app.js papered over it.
    """
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{base_css(scheme)}</style><style>{theme_css(scheme)}</style></head><body>
<div data-testid="stHeader"></div><div id="host-bar"></div>
<div data-testid="stAppViewContainer">
  <div data-testid="stMain" class="main">
    <div data-testid="stMainBlockContainer" class="block-container">
      <div data-testid="stVerticalBlock">{body}</div></div></div>
  <div data-testid="stBottomBlockContainer">
    <div class="stChatInput"><div><textarea placeholder="Ask anything about RCC…"></textarea></div></div>
  </div></div>
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
    if newest and bar:
        gap = bar["top"] - newest["bottom"]
        reserved = data.get("reserved", {})
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
        # At rest, just-finished, and on the first frame are the views a reader is
        # actually left looking at, so they are the ones that must not be a third
        # of a screen of nothing. A negative gap means the reply runs off the
        # bottom, which is theirs to scroll; this is only ever about empty space.
        if state in ("rest", "settled", "unmeasured") and gap > MAX_TAIL_GAP:
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
                states = (["unmeasured", "rest"] if scenario == "landing"
                          else ["unmeasured", "rest", "scrolled", "generating",
                                "settled"])
                for state in states:
                    suffix = "" if state == "rest" else f"-{state}"
                    name = f"{scenario}-{scheme}-{width}{suffix}"
                    html = page(body, scheme, scroll=state == "scrolled",
                                generating=state == "generating",
                                pin=state == "settled",
                                script=state != "unmeasured")
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

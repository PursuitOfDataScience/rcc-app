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
  * that slack being applied while an answer was still generating, which put the
    question halfway down the window with the reply arriving into the bottom of it —
    which needed a model added here before it could be caught;
  * 46px of nothing between the last line typed and the bottom of the input box,
    which is the send button taking a row of its own once the text passes one line.
    The replica had no send button at all, so the box was always exactly as tall as
    its text and the bug was not expressible here;
  * three separate bugs in the attachment chips, the first time a chip was rendered
    here at all: the newest answer 5px behind one row of them and 38px behind two,
    because every spacing measurement in app.js went to the input bar's top edge and
    the chips are pinned above it; the chips floating 58px above the box on the first
    frame, from a `--bar-band` fallback tuned like a reservation when it is a
    position; and the chip's own text at 4.39:1 in light mode, which is under AA and
    had never been measured because the chip was the only thing using that colour as
    text. One screen, three bugs, none of them visible from reading the CSS.

The dead space at the end of a conversation outlived three rounds of fixes because
of a line in this file: the bar was modelled `position: fixed`, the stylesheet
reserved a bar's worth of room at the end of the page on the strength of it, and
that reservation *was* the dead space. Streamlit also ships it `sticky`, in the
flow, where it needs no room reserved at all. Five of the screens here are
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

The second of those caught this file itself. `--window-size` is the *outer* window,
so every height came back 87px short of the number asked for, and Chromium will not
open a headless window narrower than 500px however small a number it is given: the
414px phone in the width list was rendered at 500px for as long as the list existed,
and every failure it reported named a size it was not looking at. Both numbers are
measured at startup by `calibrate()` now, the window is asked for the chrome on top
of the viewport wanted, and any render whose viewport is not the one requested is
reported as a failure instead of being quietly measured.

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


# There was a `_disclaimer()` here that read the caveat line out of app.py so the two
# could not drift apart. The caveat line is gone from the app, so it is gone from here
# — not left pointing at nothing, which is how a check comes to pass on a placeholder.
# The lesson it taught is kept in `_subtitle()`'s neighbours: read the real string, or
# do not claim to be measuring it.

SUBTITLE = _subtitle()
CARDS = _card_labels()
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
/* The other place Streamlit's scrollbar can be: on the document, with stMain just
   a block that grows. It matters because it decides which element answers "does
   this page scroll?" — ask stMain in this shape and it says no however long the
   conversation is, which is how a screenful of slack ended up above one that
   scrolled. See `page(doc_scroll=…)`. */
.doc-scroll [data-testid="stMain"] {{ overflow: visible; height: auto; }}
.block-container {{ padding: 6rem 1rem 10rem; margin: 0 auto; }}
.stMarkdown h1 {{ font-size: 2.75rem; font-weight: 600; line-height: 1.2;
                 padding: 1.25rem 0 1rem; margin: 0; }}
.stMarkdown h2 {{ font-size: 1.75rem; line-height: 1.3; margin: 0 0 .5rem; }}
/* Streamlit sizes markdown paragraphs itself, at a specificity of (0,1,1) — one class
   and one type. A bare one-class rule loses to it, which is how the caveat line that
   used to sit under the input rendered at Streamlit's size and wrapped onto a second
   line while every render here passed: the replica had no paragraph size at all, so
   the app's rule won by default. Kept because `.welcome-subtitle` is still in that
   fight. */
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
/* Streamlit's send button: its own size, in the flow, and a flex item of the box
   alongside the textarea. Modelled at its real size because the height of the box is
   what it decides — an unstyled button is small enough to hide the row it takes. */
.stChatInput button {{ width: 36px; height: 36px; flex: 0 0 auto; border-radius: 8px;
   background: {'#3a3b46' if scheme == 'dark' else '#e6e6e9'}; color: inherit;
   border: 0; font: inherit; cursor: pointer; }}
.stChatInput button p {{ margin: 0; }}
/* The other way Streamlit stacks the inside of that box: the button in a row of its
   own *under* the textarea rather than beside it. Which one it is decides whether a
   box with a paragraph in it has a band of nothing under the last line — 46px of it
   in this shape, 2px in the row shape — and it is not visible from this repo, so both
   are rendered. See `page(column_input=…)`. */
.input-column .stChatInput > div {{ flex-direction: column !important;
   align-items: stretch !important; }}
.input-column .chat-actions {{ display: flex; justify-content: flex-end;
   align-items: center; padding: 4px 8px; }}
.stChatMessage {{ display: flex; }}
/* The overlay portal Streamlit renders popovers into, at the end of <body>. Modelled
   with BOTH of the things Streamlit gives it, because the app's own rules only matter
   in contrast to them:
     - it is positioned (floating-ui anchors the panel to its trigger), so it takes no
       space in the flow. Left static it added a slab to the end of the page and the
       slack above the conversation was measured against it — 476px of dead space that
       had nothing to do with the panel;
     - the body has a light background and dark text of Streamlit's own. That is the
       white slab a dark-mode reader saw, and a stylesheet that fails to override it
       has to LOSE here, or this screen proves nothing. */
#stFloatingOverlayPortal {{ position: fixed; right: 1rem; bottom: 8rem; z-index: {HOST_Z + 5}; }}
[data-testid="stPopoverBody"] {{ background: #ffffff; color: #31333F;
   padding: 0.75rem; border-radius: 8px; }}
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


def panel(legacy: bool = False) -> str:
    """The model picker with its panel OPEN, in the portal Streamlit renders it into.

    Modelled because it was not, and the stylesheet had a whole section aimed at an
    element no render had ever contained: the panel came out white on a dark page and
    nothing here could see it. It is not a descendant of anything else in the app —
    Streamlit portals it to the end of `<body>` — so a rule written as a descendant
    selector reaches nothing, which is exactly the failure this screen exists to catch.

    `legacy` is the pre-1.59 shape, when Streamlit was built on Base Web and the panel
    sat inside `[data-baseweb="popover"]`. 1.59 removed Base Web and renders into
    `#stFloatingOverlayPortal` instead. requirements.txt allows >=1.42, so both are
    live, and a stylesheet that only names one of them is half a fix.
    """
    rows = "".join(
        f'<div class="element-container"><div class="stButton">'
        f"<button><p>{label}</p></button></div></div>"
        for label in (
            "● Mistral · small-latest",
            "○ Mistral · medium-latest",
            "○ Zen · deepseek-v4-flash-free",
            "○ Zen · claude-opus-4-6",
        )
    )
    body = (
        '<div data-testid="stPopoverBody">'
        '<div data-testid="stCaptionContainer">'
        "Answering model · Zen models are free</div>"
        f"{rows}</div>"
    )
    if legacy:
        body = f'<div data-baseweb="popover"><div><div>{body}</div></div></div>'
    return (
        '<div id="stFloatingOverlayPortal" data-st-overlay-root="true">'
        f"{body}</div>"
    )


def chips(wrapped: bool = True) -> str:
    """Attachment chips, rendered where app.py renders them: above the controls.

    Modelled at all because they were not, and the consequence was a row of `fixed`
    elements nothing in this file had ever measured. Two of them, one with a long
    name, because the row wraps and a single short chip proves nothing about that.
    Both container shapes, for the reason `strip` renders both.
    """
    buttons = "".join(
        f'<div class="element-container"><div class="stButton">'
        f"<button><p>{label}</p></button></div></div>"
        for label in (
            "📝 slurm-12345.out · 8,412 characters  ✕",
            "🖼️ pasted-image.png · 184 KB image  ✕",
        )
    )
    if wrapped:
        return ('<div class="st-key-attachments element-container">'
                f'<div data-testid="stVerticalBlock">{buttons}</div></div>')
    return ('<div class="st-key-attachments" data-testid="stVerticalBlock">'
            f"{buttons}</div>")


def strip(clear: bool = True, wrapped: bool = True) -> str:
    """The controls under the input: Clear, then the model picker.

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
    # Clear, then the picker — app.py's order, and the order that puts the picker in
    # the corner next to the button that sends. There was a caveat line on the left of
    # this row too; it is gone, and with it the last thing under the input that was
    # not a control.
    controls = f"""
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

def landing(wrapped: bool = True) -> str:
    """The hero and the starter cards.

    The cards' container is rendered in the two shapes `st.container(key=…)` really
    produces — the key on a wrapper around the vertical block, or on the block itself.
    It used to be modelled as `.element-container`, which Streamlit never emits and
    which carries `width: 100%` in this replica: exactly the declaration the grid was
    missing. So the grid measured 780px here and collapsed to 585px in the app, with
    every card label wrapping to two lines, and no render could see it.
    """
    grid = _cards_html()
    if wrapped:
        cards = ('<div class="st-key-examples">'
                 f'<div data-testid="stVerticalBlock">{grid}</div></div>')
    else:
        cards = ('<div class="st-key-examples" data-testid="stVerticalBlock">'
                 f"{grid}</div>")
    return f"""
<div class="element-container"><div class="stMarkdown">
  <div class="welcome">
    <h1 class="welcome-title">What can I help you with?</h1>
    <p class="welcome-subtitle">{SUBTITLE}</p>
  </div></div></div>
{cards}"""

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
STICKY_BAR = {"landing-flat", "answer", "long-chat", "attached-flat"}

# Which screens put the scrollbar on the document rather than on stMain. Kept to
# one screen for the same reason as above: it costs a screen, not a doubling, and
# every state and width still passes through the shape.
DOC_SCROLL = {"doc-scroll"}

# Which screens render the model picker's panel open, and in which of the two shapes
# Streamlit has portalled it into. One screen each: the panel does not change with the
# conversation, so states and widths are what matter, not the page behind it.
OPEN_PICKER = {"picker-open": False, "picker-open-legacy": True}

# Which screens render the input with something in it rather than on its placeholder.
TYPED_INPUT = {"composing", "composing-column"}
# …and which of those stack the send button under the textarea rather than beside it.
COLUMN_INPUT = {"composing-column"}

# What was actually pasted in when the dead space got reported: a dictionary entry,
# several lines of it, in two scripts. Long enough to grow the box past one line at
# every width, which is the condition the bug needs.
TYPED = (
    "spurt — a sudden short burst of liquid, speed or activity — My son had a "
    "growth spurt over the summer. 喷出；一阵突发的活动或速度 — and a second line so "
    "the box is unambiguously taller than one row at every width this renders."
)

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
    "landing": landing(wrapped=True) + strip(clear=False, wrapped=True),
    "landing-flat": landing(wrapped=False) + strip(clear=False, wrapped=False),
    "answer": CHAT_MARKER + answer_block(0) + strip(wrapped=False),
    "short-answer": CHAT_MARKER + SHORT_ANSWER + strip(),
    "long-chat": CHAT_MARKER
    + "".join(answer_block(i) for i in range(6))
    + strip(wrapped=False),
    # The same long conversation with the scrollbar on the document instead of on
    # stMain (see DOC_SCROLL). Only one thing differs, and it is the thing that
    # decides whether app.js thinks this page has room to spare.
    "doc-scroll": CHAT_MARKER
    + "".join(answer_block(i) for i in range(6))
    + strip(wrapped=False),
    # A conversation with a half-written question still in the box. The only screen
    # where the input is not one line tall, and so the only one that can see what the
    # send button does to the height of the box it sits in.
    "composing": CHAT_MARKER + SHORT_ANSWER + strip(),
    # The same half-written question with the send button stacked under the text. This
    # is the shape the dead space appears in; the one above is the shape it does not.
    "composing-column": CHAT_MARKER + SHORT_ANSWER + strip(),
    # A conversation with files attached but not yet sent. The chips are `fixed` above
    # the input, and the page has to reserve room for them or they land on the newest
    # answer — which nothing here could have caught, because nothing here had a chip.
    "attached": CHAT_MARKER + SHORT_ANSWER + chips() + strip(),
    "attached-flat": CHAT_MARKER + SHORT_ANSWER + chips(wrapped=False) + strip(),
    # The picker, open. The page behind it is an ordinary answer; what is under test
    # is the panel, which lives outside every container this stylesheet reaches.
    "picker-open": CHAT_MARKER + SHORT_ANSWER + strip(),
    "picker-open-legacy": CHAT_MARKER + SHORT_ANSWER + strip(),
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
    # NB: the loop below gates these on width >= 641, because at phone widths nearly
    # everything wraps and a limit there would be noise. Anything that must hold at a
    # phone width belongs in NARROW_LINE_LIMITS instead, where the gate does not
    # apply — a budget listed only here is silently unenforced below 641px.
    **{f".st-key-example-card-{i} button p": 1 for i in range(6)},
}

# Line budgets that apply BELOW 641px too, where the general gate does not. Empty
# since the caveat line — the one element that had to hold at a phone width — was
# removed from under the input.
NARROW_LINE_LIMITS: dict[str, int] = {}

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
// Whichever element actually scrolls, not whichever one usually does. This
// replica gave `[data-testid="stMain"]` `overflow: auto` from the day it was
// written, and every measurement below took that for granted; the app has a
// shape where the document scrolls and stMain reports no overflow at all, and
// asking the element that is not the scrollport whether the page scrolls is
// what put a screenful of slack above a conversation that already scrolled.
// Falls back to stMain so a page with nowhere to scroll still measures.
function scrollport() {
  var el = document.querySelector('[data-testid="stMain"]');
  var candidates = [el, document.scrollingElement, document.documentElement];
  for (var i = 0; i < candidates.length; i++) {
    var c = candidates[i];
    if (c && c.scrollHeight > c.clientHeight + 1) return c;
  }
  return el;
}
var main = scrollport();
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
  // Re-resolved rather than reused from the pin above: app.js has run by now, and
  // the slack it added can be what made something start scrolling.
  var port = scrollport();
  // The popover panel's own background. Reported as a colour rather than folded into
  // the contrast numbers because the failure was not unreadable text — it was a white
  // slab on a dark page, which contrasts beautifully and looks awful.
  var panelEl = document.querySelector('[data-testid="stPopoverBody"]');
  var panelBg = panelEl ? getComputedStyle(panelEl).backgroundColor : '';
  var out = {viewport: {w: innerWidth, h: innerHeight}, hostBar: HOSTBAR,
           panelBg: panelBg,
           scrolled: port ? Math.round(port.scrollTop) : 0,
           // Whether there is anywhere to scroll to. A conversation shorter than
           // the window sits at the bottom of the space reserved for it, so if
           // that reservation is wrong it lands under the input with no scroll
           // available to reveal it.
           canScroll: !!port && port.scrollHeight - port.clientHeight > 1,
           // Whether it would scroll with the slack taken back out. app.js only
           // adds slack to a page too short to fill the window, so asking
           // "does it scroll?" of the padded page answers a question the padding
           // itself decides: enough slack makes any page scrollable, and the
           // check that reads it then fires on every page it succeeded on.
           canScrollUnfilled: !!port
             && port.scrollHeight - port.clientHeight
                - (parseFloat(root.getPropertyValue('--fill')) || 0) > 1,
           // Already as far down as the page goes. The scroll pin clamps to this,
           // so a question that looks low here is as high as it can be put.
           atEnd: !port || port.scrollHeight - port.clientHeight - port.scrollTop <= 2,
           docOverflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
           reserved: {bar: root.getPropertyValue('--bar-h').trim(),
                      // The bar alone, which is what the chips are anchored to. Named
                      // separately because a failure where the two disagree is a
                      // different bug from either of them being wrong.
                      band: root.getPropertyValue('--bar-band').trim(),
                      strip: root.getPropertyValue('--strip-h').trim(),
                      fill: root.getPropertyValue('--fill').trim()},
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
# The bordered box around the textarea, and the button that sends. Both measured so
# the space between the end of the text and the bottom of the box can be: in the flow
# the button takes a row of its own once the text passes one line, and that row is a
# band of nothing under what was typed.
INPUT_BOX = ".stChatInput > div"
SEND = '.stChatInput button:not(#paperclip-btn)'
# The attachment chips. `fixed` above the input, so they are part of the composer's
# footprint: whatever the page reserves at its end has to cover them too.
CHIPS = ".st-key-attachments"
# The popover panel and what is in it. Named because the panel is portalled to the end
# of <body>, so its colours come from nothing it is nested inside — if the stylesheet
# does not state them, Streamlit's default does, and on a dark page that was white.
PANEL = '[data-testid="stPopoverBody"]'
PANEL_BUTTON = '[data-testid="stPopoverBody"] button p'
PANEL_CAPTION = '[data-testid="stPopoverBody"] [data-testid="stCaptionContainer"]'

SELECTORS = [
    ".welcome-title", ".welcome-subtitle", ".user-bubble", "last:.user-bubble",
    ".error-card", ".notice", ".st-key-error-actions",
    ".error-title", ".error-body", ".sources-label",
    ".source-chip", ".st-key-answer-5", ".st-key-answer-0", ".stChatMessage pre",
    ".stChatMessage code", '[data-testid="stBottomBlockContainer"]',
    STRIP, INPUT, INPUT_BOX, SEND, CHIPS, ".st-key-attachments button",
    PANEL, PANEL_BUTTON, PANEL_CAPTION,
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
    SEND, PANEL_BUTTON,
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
# Room allowed between the last line of text in the input and the bottom of the box.
# The textarea carries 16px of its own bottom padding, so this is that plus a little
# rounding — anything more is a row of furniture, which is what the send button was
# taking once the text grew past one line.
MAX_INPUT_DEAD_SPACE = 20
# Room allowed between the attachment chips and the top of the input box. They are
# pinned 0.35rem above it; this is that plus the bar's own top padding and rounding.
# Rendered in the flow instead, they were most of a page away.
MAX_CHIP_GAP = 40


def page(body: str, scheme: str, scroll: bool, generating: bool = False,
         pin: bool = False, script: bool = True, sticky: bool = False,
         doc_scroll: bool = False, typed: bool = False,
         column_input: bool = False, portal: str = "") -> str:
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

    `doc_scroll` moves the scrollbar off stMain and onto the document. Nothing
    about the stylesheet changes; what changes is which element can answer "does
    this conversation scroll?", and a wrong answer there is how a page that
    scrolled got a screenful of slack padded on top of it.

    `typed` fills the input with a paragraph instead of leaving it on its placeholder.
    An empty box is one line tall and hides everything about how a full one behaves.

    `portal` is markup appended at the very end of `<body>`, where Streamlit renders
    overlays. Anything in there is outside every container this app styles, which is
    the whole reason it needs modelling separately.

    `column_input` stacks the send button under the textarea instead of beside it. In
    the row shape a full box has 2px under its last line; in the column shape it has
    46px, and 46px under what you just typed is what got reported as "an empty space
    between the bottom of the text and the bottom of the input text box". Both are
    rendered because which one Streamlit builds is not visible from this repo — and a
    fix tested only in the shape that cannot show the bug is not a tested fix.
    """
    # The send button is modelled because it is what decides the height of the box.
    # Left in the flow it is a sibling of the textarea, and once the text runs past one
    # line it lands on a row of its own underneath — a band of nothing between the last
    # line typed and the bottom of the box. The replica had no button at all, so the
    # box was always exactly as tall as its text and the bug could not appear here.
    #
    # `rows` stands in for Streamlit's auto-grow: a textarea does not grow to fit its
    # own value, so `typed` is what a box with a paragraph in it actually looks like.
    send = ('<button data-testid="stChatInputSubmitButton" aria-label="Send">'
            "<p>↑</p></button>")
    bar = ('<div data-testid="stBottom">'
           '<div data-testid="stBottomBlockContainer">'
           '<div class="stChatInput" data-testid="stChatInput"><div>'
           # The paperclip app.js injects. Without the test id above, `addPaperclip`
           # never fired here, so neither the button nor the `:not(#paperclip-btn)`
           # exclusion that keeps it out of the send button's corner was ever rendered.
           '<button id="paperclip-btn" type="button">📎</button>'
           + ('<textarea rows="6">' + TYPED + "</textarea>" if typed else
              '<textarea rows="1" placeholder="Ask anything about RCC…"></textarea>')
           + (f'<div class="chat-actions">{send}</div>' if column_input else send)
           + "</div></div></div></div>")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{base_css(scheme)}</style><style>{theme_css(scheme)}</style></head>
<body class="{'bar-sticky' if sticky else 'bar-fixed'}{' doc-scroll' if doc_scroll else ''}{' input-column' if column_input else ''}">
<div data-testid="stHeader"></div><div id="host-bar"></div>
<div data-testid="stAppViewContainer">
  <div data-testid="stMain" class="main">
    <div data-testid="stMainBlockContainer" class="block-container">
      <div data-testid="stVerticalBlock">{body}</div></div>
    {bar if sticky else ''}</div>
  {'' if sticky else bar}</div>
{'<div id="processing-signal" hidden></div>' if generating else ''}
{portal}
<script>window.__scrollBottom = {str(scroll).lower()}; window.__pinLast = {str(pin).lower()};</script>
{'<script>' + JS + '</script>' if script else ''}
{MEASURE.replace("HOSTBAR", str(HOST_BAR)).replace("TOPGAP", str(TOP_GAP)).replace("SELECTORS", json.dumps(SELECTORS))}
</body></html>"""


_PROBE = ('<!doctype html><html><body><script>document.title='
          'JSON.stringify({w:innerWidth,h:innerHeight})</script></body></html>')
# The phone this wants to render. Chromium will not open a headless window this
# narrow — 500px is as far as it goes — so what `calibrate()` returns for it is the
# narrowest real width available, and that is what goes in the width list.
PHONE_W, PHONE_H = 414, 896


def calibrate():
    """What viewport does `--window-size` actually produce?

    Not the one it asks for. `--window-size` is the *outer* window, so every height
    comes back short by the browser's own chrome, and Chromium will not open a window
    narrower than a floor of its own however small a number it is given. This harness
    asked for 414x896 for a year and rendered 500x809: the phone width it claimed to
    cover did not exist, and every failure it reported named a size it was not looking
    at. Measured here rather than hardcoded, because both numbers belong to whichever
    Chromium is installed.
    """
    path = os.path.join(HERE, "_calibrate.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_PROBE)
    def probe(w, h):
        out = subprocess.run(
            [CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             f"--window-size={w},{h}", "--virtual-time-budget=300", "--dump-dom",
             f"file://{path}"], capture_output=True, text=True, timeout=120).stdout
        start, end = out.find("<title>"), out.find("</title>")
        if start == -1:
            raise SystemExit("render_check: could not calibrate the viewport — "
                             f"{CHROME} produced no measurement")
        return json.loads(out[start + 7 : end])
    big = probe(1200, 1000)
    # The narrowest the phone entry can be is found by asking for a phone and seeing
    # what comes back — not by asking for 1x1, which read as the tidier way to find
    # the floor and returned a width of 0 on CI's Chromium: a window that degenerate
    # is one it declines to report rather than one it clamps, and every render then
    # failed at "asked for a 0px viewport". Where a Chromium does honour PHONE_W, this
    # gains the real phone width instead of settling for the floor.
    chrome_w, chrome_h = 1200 - big["w"], 1000 - big["h"]
    # Asked for twice on purpose. The first probe says what a phone request lands on;
    # the second asks for *that*, the way `render()` will, and takes what comes back.
    # Where the window has no borders the two agree and the second is a no-op, but
    # `render()` adds `chrome_w` to whatever it is given, so on a platform where that
    # is not zero the naive floor would be a width `render()` can never hit — and the
    # assertion downstream would turn that into 300 failures rather than one.
    phone = probe(PHONE_W + chrome_w, PHONE_H + chrome_h)
    narrow = probe(phone["w"] + chrome_w, PHONE_H + chrome_h)["w"]
    os.remove(path)
    if not 1 <= narrow <= 640:
        raise SystemExit(
            f"render_check: asked for a {PHONE_W}px-wide window and got {narrow}px. "
            "The narrow screen has to land under the 640px mobile breakpoint or the "
            "mobile rules go unrendered — fix this rather than auditing four desktop "
            "widths and calling one of them a phone."
        )
    return {"chrome_h": chrome_h, "chrome_w": chrome_w,
            "min_w": narrow, "min_h": phone["h"]}


VIEWPORT = None   # filled in by main(); {'chrome_h', 'chrome_w', 'min_w', 'min_h'}


def render(name, html, width, height, shot=False):
    path = os.path.join(HERE, f"{name}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    # `width`/`height` are the CSS viewport wanted, so the window has to be asked for
    # the chrome on top of it. Whether that landed is checked per render in main().
    pad_w = VIEWPORT["chrome_w"] if VIEWPORT else 0
    pad_h = VIEWPORT["chrome_h"] if VIEWPORT else 0
    cmd = [CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           f"--window-size={width + pad_w},{height + pad_h}",
           "--virtual-time-budget=1500"]
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
    # The state belongs in the label. Six identical-looking failures that named only
    # screen, theme and width could not be placed to a state at all, and the state is
    # what says whether app.js had run, whether an answer was in flight, and whether
    # the view had been scrolled — i.e. most of what a failure means.
    where = f"{scenario}/{scheme}/{width}px/{state}"
    generating = state == "generating"
    # "unmeasured" is the first frame, so it is at the top of the page like "rest":
    # the host-toolbar collision check below is meaningful in both.
    scrolled = state not in ("rest", "unmeasured")

    if data["docOverflowX"] > 0:
        problems.append(f"{where}: page scrolls sideways by {data['docOverflowX']}px")

    bar = els.get('[data-testid="stBottomBlockContainer"]')
    # The top of everything pinned at the bottom, not just of the bar. The attachment
    # chips sit above the bar and are `fixed` too, so a gap measured to the bar's top
    # would read as healthy while a chip sat on the newest answer. Every check below
    # that used to say "the input bar" now means "the composer", which is what a reader
    # sees: one block of furniture at the bottom of the page.
    chip_row = els.get(CHIPS)
    if bar and chip_row and chip_row["top"] < bar["top"]:
        bar = dict(bar, top=chip_row["top"])
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

    # The chips belong to the composer, immediately above the box. They used to render
    # in the flow, which put them under the starter cards in the middle of the page —
    # "at a random spot in the middle of the ui" — so both halves of that are checked:
    # above the input, and not adrift from it.
    box = els.get(INPUT_BOX)
    if chip_row and box:
        if chip_row["bottom"] > box["top"] + 1:
            problems.append(
                f"{where}: the attachment chips overlap the input box by "
                f"{chip_row['bottom'] - box['top']}px"
            )
        elif box["top"] - chip_row["bottom"] > MAX_CHIP_GAP:
            problems.append(
                f"{where}: the attachment chips are {box['top'] - chip_row['bottom']}px "
                f"above the input box (want at most {MAX_CHIP_GAP} — they are part of "
                f"the composer, not of the page)"
            )

    # The popover panel must belong to the page it is drawn over. It is portalled to
    # the end of <body>, so it inherits nothing from the app — and when the stylesheet
    # aimed only at a Base Web wrapper Streamlit had removed, what a dark-mode reader
    # got was a white slab: "completely white… very sharp and uncomfortable".
    panel_bg = data.get("panelBg", "")
    if panel_bg:
        rgb = [int(part) for part in re.findall(r"\d+", panel_bg)[:3]]
        if rgb:
            lightness = sum(rgb) / 3
            if scheme == "dark" and lightness > 90:
                problems.append(
                    f"{where}: the popover panel is {panel_bg} on a dark page "
                    f"(unthemed — it is portalled outside everything, so its colour "
                    f"has to be stated, not inherited)"
                )
            if scheme == "light" and lightness < 160:
                problems.append(
                    f"{where}: the popover panel is {panel_bg} on a light page"
                )

    # Inside the box: how much of it is neither text nor the room the text sits in.
    # With the send button in the flow it is a flex item beside the textarea, and once
    # the text passes one line it wraps onto a row of its own — leaving a band of
    # nothing between the last line typed and the bottom of the box. Out of the flow,
    # the box is as tall as its text and this is the padding, nothing more.
    box, area = els.get(INPUT_BOX), els.get(INPUT)
    if box and area:
        under = box["bottom"] - area["bottom"]
        if under > MAX_INPUT_DEAD_SPACE:
            problems.append(
                f"{where}: {under}px of nothing between the end of the text and the "
                f"bottom of the input box (want at most {MAX_INPUT_DEAD_SPACE})"
            )
    # And the button has to stay off the text it sits over now that it is out of the
    # flow: an absolute corner is only right if the text stops before it.
    send = els.get(SEND)
    if send and area and send["left"] < area["right"] - 1 and area["lines"] > 0:
        problems.append(
            f"{where}: the send button overlaps the text by "
            f"{area['right'] - send['left']}px"
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
        # And not the other way either. The slack that sits a *finished* short
        # conversation above the composer was also being applied to a question with
        # a "Reading…" row under it, which put the question halfway down the window
        # with the answer arriving into the bottom of it and the top half empty.
        # Reported as "way below the top of the page, which looks very off".
        # 0.35 rather than 0.4 of the window. At 0.4 this cleared the failure it
        # exists to catch by two pixels at 966×626 — a guard that passes by 2px is
        # one font metric away from not passing at all. With the slack suppressed
        # mid-turn the question sits ~100px down at every width, so the tighter
        # ceiling costs nothing and buys ~30px of margin at the narrowest window.
        ceiling = round(data["viewport"]["h"] * 0.35)
        # Not when the page is scrolled as far as it goes: the pin clamps to max
        # scroll, so on a conversation whose last turn is near the end of the
        # document the question cannot be lifted any higher and this would be
        # asking the layout for something the geometry forbids.
        if asked and asked["top"] > ceiling and not data.get("atEnd", False):
            problems.append(
                f"{where}: the question is {asked['top']}px down the window while "
                f"its answer generates (want no lower than {ceiling})"
            )

    # An OPEN popover is meant to cover the page: that is what an overlay is, and
    # clicking the thing underneath is how a reader dismisses it. So on the screens
    # that render one, the composer being covered is the feature, and what has to stay
    # reachable is the panel's own buttons — which are in INTERACTIVE and are checked.
    covered_by_overlay = (
        {INPUT, SEND, PICKER, STRIP, ".st-key-composer-strip button",
         "last:.st-key-composer-strip button"}
        if scenario.startswith("picker-open")
        else set()
    )
    for sel in INTERACTIVE - covered_by_overlay:
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

    # Slack above the conversation is for a page shorter than the window. On a page
    # that scrolls it is a gap at the TOP instead — reported as "the top and bottom
    # both have the problem" — and it got there because `fill()` asked stMain whether
    # the page scrolls rather than asking which element does.
    # Measured with the slack subtracted, not as the page stands: a short page that
    # took slack often scrolls *because* of it, and reading the padded page would
    # fire this on every page the slack was right for.
    fill = reserved.get("fill", "0px")
    if (state in ("rest", "settled") and data.get("canScrollUnfilled")
            and fill not in ("", "0px")):
        problems.append(
            f"{where}: {fill} of slack above a conversation that scrolls "
            f"without it (only a page shorter than the window has slack to take)"
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
    global VIEWPORT
    verbose = "-v" in sys.argv
    VIEWPORT = calibrate()
    # The narrowest entry is Chromium's own floor rather than a phone's width, because
    # a headless window will not go below it and a number it silently ignores is worse
    # than an honest one: this list said 414px for a year and rendered 500px. 500 is
    # still under the 640px mobile breakpoint, so the mobile rules are exercised — what
    # is not covered is a real 414px screen, and saying so is the point.
    # 660 is here because it is the tightest width for the starter cards: two
    # columns, just above the 640px breakpoint that would stack them, so the
    # longest label has the least room it ever gets. Without it the one-line rule
    # was unenforced across the whole 641-760 band.
    widths = [(1440, 1080), (1263, 900), (966, 626), (768, 900), (660, 900),
              (VIEWPORT["min_w"], PHONE_H)]
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
                elif scenario.startswith("picker-open"):
                    # The panel is the same whatever the conversation behind it is
                    # doing, so scrolling and generating would re-measure one slab.
                    states = ["unmeasured", "rest"]
                elif scenario.startswith("composing"):
                    # What these two are for is the inside of the input box, and that
                    # is the same whether the page is scrolled or an answer is in
                    # flight. Three more states each would be 60 renders and a minute
                    # of CI to re-measure an identical box.
                    states = ["unmeasured", "rest"]
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
                                sticky=scenario in STICKY_BAR,
                                doc_scroll=scenario in DOC_SCROLL,
                                typed=scenario in TYPED_INPUT,
                                column_input=scenario in COLUMN_INPUT,
                                portal=(panel(OPEN_PICKER[scenario])
                                        if scenario in OPEN_PICKER else ""))
                    data = render(name, html, width, height,
                                  shot=(scheme == "dark" and width == 1263
                                        and state == "rest"))
                    if data is None:
                        failures.append(f"{name}: render failed")
                        continue
                    checked += 1
                    # Every measurement below is only about the viewport it was taken
                    # in, so a viewport that is not the one asked for invalidates the
                    # render rather than failing a check inside it.
                    got = (data["viewport"]["w"], data["viewport"]["h"])
                    if got != (width, height):
                        failures.append(
                            f"{name}: asked for a {width}x{height} viewport and got "
                            f"{got[0]}x{got[1]} — nothing measured here is about the "
                            f"size it claims"
                        )
                        continue
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

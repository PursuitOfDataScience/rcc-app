#!/usr/bin/env python3
"""Render static/app.css against a replica of Streamlit's DOM and measure clipping.

Streamlit cannot always be installed where this repo is worked on, and the layout
bugs that have actually shipped were pure CSS. A faithful DOM replica plus real
headless Chromium gives ground truth instead of reasoning about specificity.

It found two live bugs that reading the CSS did not:
  * the newest answer sat 131px underneath the fixed chat input, because
    Streamlit's default `padding-bottom: 10rem` had been overridden to 1.5rem;
  * on a short viewport the first message scrolled under the host toolbar.

Usage:
    python tools/render_check.py                 # measure, print a report
    python tools/render_check.py "New subtitle"  # try alternative hero copy

Screenshots and generated HTML land next to the script. Requires a Chromium
binary; set SAGE_CHROME to override the path.
"""
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


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return handle.read()


CSS = _read("static", "app.css")

# Streamlit Community Cloud overlays an opaque toolbar at the top of the viewport.
HOST_BAR = 46

# The parts of Streamlit's own stylesheet that interact with ours.
STREAMLIT_BASE = """
* { box-sizing: border-box; }
body { margin: 0; background: #0e1117; color: #e5e7eb;
       font-family: "Source Sans Pro", system-ui, sans-serif; }
[data-testid="stAppViewContainer"] { min-height: 100vh; }
[data-testid="stMain"] { overflow: auto; height: 100vh; }
.block-container { padding: 6rem 1rem 10rem; margin: 0 auto; }
.stMarkdown h1 { font-size: 2.75rem; font-weight: 600; line-height: 1.2;
                 padding: 1.25rem 0 1rem; margin: 0; }
.stMarkdown p { margin: 0 0 1rem; }
.element-container { width: 100%; }
[data-testid="stVerticalBlock"] { display: flex; flex-direction: column; }
[data-testid="stHorizontalBlock"] { display: flex; flex-direction: row; }
[data-testid="stColumn"] { flex: 1; }
.stButton button { width: 100%; padding: 0.4rem 0.75rem; border-radius: 8px;
                   background: #262730; color: #e5e7eb; border: 1px solid #3a3b46;
                   font: inherit; cursor: pointer; }
[data-testid="stBottomBlockContainer"] { position: fixed; bottom: 0; left: 0;
                                         right: 0; background: #0e1117; padding: 1rem; }
.stChatInput > div { background: #262730; }
.stChatInput textarea { width: 100%; background: transparent; border: 0;
                        color: #e5e7eb; font: inherit; resize: none; }
/* Simulated host chrome */
#host-bar { position: fixed; top: 0; left: 0; right: 0; height: HOSTBARpx;
            background: #0e1117; z-index: 9999; }
""".replace("HOSTBAR", str(HOST_BAR))

def _subtitle_from_app():
    """Read the live hero copy out of app.py so the check never drifts from it."""
    source = _read("app.py")
    match = re.search(r'class="welcome-subtitle">(.*?)</p>', source, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else "(not found)"


SUBTITLE = _subtitle_from_app()

CARDS = "".join(
    f'''<div data-testid="stHorizontalBlock">
      <div data-testid="stColumn"><div class="st-key-example-card-{a} element-container">
        <div class="stButton"><button>{ta}</button></div></div></div>
      <div data-testid="stColumn"><div class="st-key-example-card-{b} element-container">
        <div class="stButton"><button>{tb}</button></div></div></div>
    </div>'''
    for a, b, ta, tb in [
        (0, 1, "🚀 How do I connect to Midway via SSH?", "💾 What are the storage quotas on Midway?"),
        (2, 3, "⚙️ How do I submit a batch job with sbatch?", "🐍 How do I set up a Python environment?"),
        (4, 5, "🎮 How do I run PyTorch on GPUs?", "📊 How do I check my allocation balance?"),
    ]
)

WELCOME_BODY = f"""
<div class="st-key-topbar element-container"><div data-testid="stHorizontalBlock">
  <div data-testid="stColumn"><div class="stButton"><button>ℹ️</button></div></div>
</div></div>
<div class="element-container"><div class="stMarkdown">
  <div class="welcome">
    <h1 class="welcome-title">What can I help you with?</h1>
    <p class="welcome-subtitle">SUBTITLE_TEXT</p>
  </div>
</div></div>
<div class="st-key-examples element-container">{CARDS}</div>
"""

CHAT_BODY = """
<div class="st-key-topbar element-container"><div data-testid="stHorizontalBlock">
  <div data-testid="stColumn"><div class="stButton"><button>ℹ️</button></div></div>
  <div data-testid="stColumn"><div class="stButton"><button>🗑️</button></div></div>
</div></div>
<div class="element-container"><div class="stMarkdown">
  <div class="chat-container"></div></div></div>
<div class="element-container"><div class="stMarkdown">
  <div class="user-message"><div class="user-bubble">How do I run PyTorch on GPUs?</div></div>
</div></div>
<div class="element-container"><div class="stMarkdown">
  <div class="error-card" role="alert">
    <div class="error-title">Could not complete that request</div>
    <div class="error-body">Something went wrong reaching the assistant. Please try again.</div>
  </div>
</div></div>
<div class="element-container"><div data-testid="stHorizontalBlock">
  <div data-testid="stColumn"></div>
  <div data-testid="stColumn"><div class="stButton"><button>↻ Try again</button></div></div>
  <div data-testid="stColumn"></div>
</div></div>
"""

MEASURE = """
<script>
function box(sel) {
  var el = document.querySelector(sel);
  if (!el) return null;
  var r = el.getBoundingClientRect();
  var cs = getComputedStyle(el);
  var lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
  return {top: Math.round(r.top), bottom: Math.round(r.bottom),
          height: Math.round(r.height), lines: Math.max(1, Math.round(r.height / lh)),
          scrollH: Math.round(el.scrollHeight), clientH: Math.round(el.clientHeight)};
}
var main = document.querySelector('[data-testid="stMain"]');
if (window.__scrollBottom && main) main.scrollTop = main.scrollHeight;
var out = {
  viewport: {w: innerWidth, h: innerHeight},
  hostBar: HOSTBAR,
  scrolled: main ? Math.round(main.scrollTop) : 0,
  overflows: main ? main.scrollHeight > main.clientHeight : false,
  els: {}
};
['.welcome-title', '.welcome-subtitle', '.user-bubble', '.error-card',
 '.st-key-example-card-5 button', '[data-testid="stBottomBlockContainer"]'
].forEach(function (s) { out.els[s] = box(s); });
document.title = JSON.stringify(out);
</script>
"""


def page(body, subtitle, scroll_bottom=False):
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{STREAMLIT_BASE}</style><style>{CSS}</style></head>
<body>
<div id="host-bar"></div>
<div data-testid="stAppViewContainer">
  <div data-testid="stMain" class="main">
    <div data-testid="stMainBlockContainer" class="block-container">
      <div data-testid="stVerticalBlock">{body.replace('SUBTITLE_TEXT', subtitle)}</div>
    </div>
  </div>
  <div data-testid="stBottomBlockContainer">
    <div class="stChatInput"><div><textarea placeholder="Ask anything about RCC…"></textarea></div></div>
    <p class="ai-disclaimer">Sage can make mistakes and cannot see your account or jobs.
       Verify commands against the linked docs.</p>
  </div>
</div>
<script>window.__scrollBottom = {str(scroll_bottom).lower()};</script>
{MEASURE.replace('HOSTBAR', str(HOST_BAR))}
</body></html>"""


def render(name, html, width, height, shot=False):
    path = os.path.join(HERE, f"{name}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    cmd = [
        CHROME, "--headless", "--no-sandbox", "--disable-gpu",
        "--hide-scrollbars", f"--window-size={width},{height}",
        "--virtual-time-budget=1500",
    ]
    if shot:
        cmd.append(f"--screenshot={os.path.join(HERE, name + '.png')}")
    cmd += ["--dump-dom", f"file://{path}"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    start, end = out.find("<title>"), out.find("</title>")
    if start == -1:
        return None
    raw = out[start + 7 : end]
    return json.loads(raw.replace("&quot;", '"').replace("&amp;", "&"))


def report(label, data):
    print(f"\n=== {label} — viewport {data['viewport']['w']}x{data['viewport']['h']}, "
          f"host bar {data['hostBar']}px, scrollTop {data['scrolled']} ===")
    for sel, b in data["els"].items():
        if not b:
            print(f"  {sel:44} (absent)")
            continue
        flags = []
        if b["top"] < data["hostBar"]:
            flags.append(f"UNDER HOST BAR by {data['hostBar'] - b['top']}px")
        if b["top"] < 0:
            flags.append("ABOVE VIEWPORT")
        if b["bottom"] > data["viewport"]["h"]:
            flags.append("BELOW FOLD")
        state = "  ".join(flags) or "ok"
        extra = f" lines={b['lines']}" if "subtitle" in sel else ""
        print(f"  {sel:44} top={b['top']:>5} bottom={b['bottom']:>5}{extra}  {state}")


if __name__ == "__main__":
    subtitle = sys.argv[1] if len(sys.argv) > 1 else SUBTITLE
    for label, body, w, h, scroll, shot in [
        ("LANDING 1263x900", WELCOME_BODY, 1263, 900, False, True),
        ("LANDING 966x626 (user's)", WELCOME_BODY, 966, 626, False, True),
        ("CHAT+ERROR 1263x337 (user's)", CHAT_BODY, 1263, 337, True, True),
        ("CHAT+ERROR 1263x900", CHAT_BODY, 1263, 900, True, True),
    ]:
        data = render(label.split()[0].lower() + str(w) + str(h), page(body, subtitle, scroll), w, h, shot)
        if data:
            report(label, data)
        else:
            print(f"\n=== {label}: RENDER FAILED ===")

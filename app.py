#!/usr/bin/env python3
"""
RCC User Guide AI Assistant - Streamlit App
A chatbot that answers questions using RCC documentation (RAG-only, no command-line tools).
File upload support for PDFs and text files via paperclip button.
Uses Mistral API for chat completion.
"""
import os
import re
import json
import streamlit as st
from io import BytesIO
from mistralai.client import Mistral
import traceback

import logging
log_level = os.getenv("LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.WARNING),
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- API Configuration ---
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

if not MISTRAL_API_KEY:
    st.error("❌ MISTRAL_API_KEY not found. Please set MISTRAL_API_KEY environment variable.")
    st.stop()

# Supported file types: PDF and text-based files (txt, md, py, json, csv)
# We extract text client-side and send to the model as plain text.
MISTRAL_MODEL = "mistral-small-latest"
# Docs bases default to the bundled snapshot (refreshed by refresh-docs.sh) but can point at a
# live mount in deployment via RCC_DOCS_PATH / RCC_WEB_PATH.
DOCS_BASE_PATH = os.getenv("RCC_DOCS_PATH", "./docs")
WEB_BASE_PATH = os.getenv("RCC_WEB_PATH", "./web")


def get_mistral_client():
    """Create a Mistral client."""
    if not MISTRAL_API_KEY:
        return None
    try:
        return Mistral(api_key=MISTRAL_API_KEY)
    except Exception as e:
        logger.error(f"Failed to create Mistral client: {e}")
        return None


# --- File Processing Functions ---
def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a PDF file."""
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pdf_text = ""
        for page in doc:
            pdf_text += page.get_text() + "\n"
        num_pages = len(doc)
        doc.close()
        return pdf_text, num_pages
    except ImportError:
        try:
            from pypdf import PdfReader
            pdf_reader = PdfReader(BytesIO(file_bytes))
            pdf_text = ""
            for page in pdf_reader.pages:
                text = page.extract_text()
                if text:
                    pdf_text += text + "\n"
            return pdf_text, len(pdf_reader.pages)
        except Exception as e:
            return f"Error extracting PDF text: {str(e)}", 0


def process_uploaded_file(uploaded_file):
    """Process an uploaded file and return content for the API."""
    filename = uploaded_file.name.lower()
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    
    if filename.endswith('.pdf'):
        pdf_text, num_pages = extract_pdf_text(file_bytes)
        if num_pages > 0:
            if len(pdf_text) > 30000:
                pdf_text = pdf_text[:30000] + "\n\n[... Document truncated due to length ...]"
            return {
                "type": "pdf",
                "filename": uploaded_file.name,
                "num_pages": num_pages,
                "text": pdf_text
            }
        else:
            return {"type": "error", "message": pdf_text}
    
    elif any(filename.endswith(ext) for ext in ['.txt', '.md', '.py', '.json', '.csv', '.yml', '.yaml']):
        try:
            text_content = file_bytes.decode('utf-8')
            if len(text_content) > 30000:
                text_content = text_content[:30000] + "\n\n[... File truncated due to length ...]"
            return {
                "type": "text",
                "filename": uploaded_file.name,
                "text": text_content
            }
        except UnicodeDecodeError:
            return {"type": "error", "message": f"Could not decode {uploaded_file.name} as text"}
    
    else:
        return {"type": "error", "message": f"Unsupported file type: {uploaded_file.name}"}


def build_message_content(user_text: str, file_data: dict = None) -> list:
    """Build message content array with text and optional file data."""
    content = []
    
    if file_data:
        if file_data["type"] == "pdf":
            pdf_context = f"""[Attached PDF: {file_data['filename']} ({file_data['num_pages']} pages)]

--- PDF Content ---
{file_data['text']}
--- End of PDF Content ---

User's question: {user_text}"""
            content.append({"type": "text", "text": pdf_context})
        
        elif file_data["type"] == "text":
            text_context = f"""[Attached file: {file_data['filename']}]

--- File Content ---
{file_data['text']}
--- End of File Content ---

User's question: {user_text}"""
            content.append({"type": "text", "text": text_context})
        
        elif file_data["type"] == "error":
            content.append({"type": "text", "text": f"[File upload error: {file_data['message']}]\n\n{user_text}"})
    else:
        content.append({"type": "text", "text": user_text})
    
    return content


# --- Documentation Index & Retrieval (RAG) ---
# The assistant discovers docs at query time via search_docs()/read_doc() instead of a
# hardcoded per-file tool list. Every file under docs/ and web/ is reachable, and the
# catalog can never drift out of sync with what is actually on disk.
ALLOWED_BASES = {
    "docs": DOCS_BASE_PATH,
    "web": WEB_BASE_PATH,
}
_DOC_EXT = {"docs": (".md",), "web": (".txt",)}
DOC_TRUNCATE_CHARS = 15000
SEARCH_RESULTS = 6


def _pretty_title(rel_path: str) -> str:
    """Human-readable title derived from a file path when a doc has no heading."""
    name = os.path.splitext(os.path.basename(rel_path))[0]
    name = name.replace("-", " ").replace("_", " ").strip()
    return (name[:1].upper() + name[1:]) if name else rel_path


def _extract_title(text: str, rel_path: str) -> str:
    """Best available title: scraped 'Title:' header, else first markdown heading, else filename."""
    for line in text.splitlines()[:15]:
        stripped = line.strip()
        # Scraped website pages start with 'URL:' / 'Title:' metadata.
        if stripped.startswith("Title:"):
            title = stripped[len("Title:"):].strip()
            # Drop the trailing site suffix, e.g. "... | Research Computing Center".
            title = title.split("|")[0].strip()
            if title:
                return title
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    # Fallback: first short, non-metadata line.
    for line in text.splitlines()[:15]:
        stripped = line.strip()
        if (stripped and len(stripped) < 120
                and not stripped.startswith(("#", "-", "*", "|", ">", "=", "URL:", "http"))):
            return stripped
    return _pretty_title(rel_path)


@st.cache_resource(show_spinner=False)
def build_doc_index():
    """Scan docs/ and web/ once and cache a lightweight in-memory search index."""
    index = []
    for source, base in ALLOWED_BASES.items():
        if not os.path.isdir(base):
            logger.warning(f"Doc base missing: {base}")
            continue
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.lower().endswith(_DOC_EXT[source]):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, base).replace(os.sep, "/")
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                except Exception as e:
                    logger.warning(f"Skipping unreadable doc {full}: {e}")
                    continue
                index.append({
                    "id": f"{source}/{rel}",
                    "source": source,
                    "path": rel,
                    "title": _extract_title(text, rel),
                    "text_lower": text.lower(),
                })
    logger.info(f"Doc index built: {len(index)} files")
    return index


def _tokenize(query: str):
    return [t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 1]


def _snippet(text_lower: str, terms, width: int = 220) -> str:
    """A short snippet around the first matched term (falls back to the document head)."""
    pos = -1
    for t in terms:
        p = text_lower.find(t)
        if p != -1 and (pos == -1 or p < pos):
            pos = p
    start = max(0, pos - 60) if pos > 0 else 0
    snippet = re.sub(r"\s+", " ", text_lower[start:start + width]).strip()
    return ("…" if start > 0 else "") + snippet + "…"


def search_docs(query: str, k: int = SEARCH_RESULTS):
    """Rank the docs/web tree against a query. Returns a list of result dicts."""
    terms = _tokenize(query)
    if not terms:
        return []
    index = build_doc_index()
    scored = []
    for entry in index:
        title_l = entry["title"].lower()
        path_l = entry["path"].lower()
        body = entry["text_lower"]
        score = 0
        for t in terms:
            if t in title_l:
                score += 8
            if t in path_l:
                score += 5
            occ = body.count(t)
            if occ:
                score += min(occ, 5)
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [
        {
            "id": entry["id"],
            "title": entry["title"],
            "source": entry["source"],
            "snippet": _snippet(entry["text_lower"], terms),
        }
        for _score, entry in scored[:k]
    ]


def format_search_results(results) -> str:
    """Format search results as text the model reads to decide what to read_doc."""
    if not results:
        return ("No matching RCC documentation was found. Try different keywords, or tell the "
                "user you couldn't find it in the RCC docs rather than guessing specifics.")
    lines = ["Top matching RCC documentation (call read_doc with the exact `path`):", ""]
    for r in results:
        lines.append(f"- path: {r['id']}")
        lines.append(f"  title: {r['title']}  (source: {r['source']})")
        lines.append(f"  snippet: {r['snippet']}")
    return "\n".join(lines)


def read_doc(doc_id: str) -> str:
    """Read a doc by its search_docs id ('docs/…md' or 'web/…txt') with a traversal guard."""
    if not doc_id or "/" not in doc_id:
        return ("Error: invalid document id. Pass the exact `path` from search_docs, e.g. "
                "'docs/slurm/sbatch.md' or 'web/faqs.txt'.")
    source, rel = doc_id.split("/", 1)
    base = ALLOWED_BASES.get(source)
    if not base:
        return f"Error: unknown source '{source}'. Use a `path` returned by search_docs."
    base_real = os.path.realpath(base)
    full_real = os.path.realpath(os.path.join(base, rel))
    # Path-traversal guard: the resolved path must stay inside the allowed base.
    if full_real != base_real and not full_real.startswith(base_real + os.sep):
        return "Error: access denied."
    if not os.path.isfile(full_real):
        return f"Error: document '{doc_id}' not found."
    try:
        with open(full_real, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading document: {e}"
    if len(content) > DOC_TRUNCATE_CHARS:
        content = content[:DOC_TRUNCATE_CHARS] + "\n\n[... Document truncated due to length ...]"
    return content


# --- Tool Definitions ---
TOOLS = [
    {
        "name": "search_docs",
        "description": (
            "Search official RCC documentation and website content for pages relevant to the "
            "user's question. Returns a ranked list of results, each with a `path`, title and "
            "snippet. Call this FIRST for any RCC how-to, policy, software, storage, Slurm, "
            "account, or connection question, then read the best result with read_doc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords or a natural-language question, e.g. 'sbatch GPU job' or 'storage quota'.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_doc",
        "description": (
            "Read the full text of one documentation page. Pass the exact `path` value returned "
            "by search_docs (for example 'docs/slurm/sbatch.md' or 'web/faqs.txt')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The exact `path` value from a search_docs result.",
                }
            },
            "required": ["path"],
        },
    },
]

# Mistral tools format (converted from Anthropic format)
MISTRAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"]
        }
    }
    for tool in TOOLS
]


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a retrieval tool and return the result as text for the model."""
    if tool_name == "search_docs":
        return format_search_results(search_docs(tool_input.get("query", "")))
    if tool_name == "read_doc":
        doc_id = tool_input.get("path", "")
        return f"=== DOCUMENT: {doc_id} ===\n\n{read_doc(doc_id)}"
    return f"Unknown tool: {tool_name}"


SYSTEM_PROMPT = """You are the RCC User Guide Assistant for the University of Chicago's Research Computing Center.

You answer from official RCC documentation using two tools:
- search_docs(query): find relevant documentation pages (returns paths, titles, and snippets)
- read_doc(path): read the full text of a page using an exact path from a search_docs result

WORKFLOW:
1. For any RCC question, call search_docs first with focused keywords.
2. Read the most relevant result(s) with read_doc before answering.
3. If the first search misses, refine the keywords and search again.
4. Base your answer on the retrieved content and cite specific commands and paths.

You can also analyze files that users upload (PDFs and text files: .txt, .md, .py, .json, .csv).

GUIDELINES:
- Be helpful, accurate, and concrete; prefer exact commands and paths from the docs.
- If the docs don't cover something, say so briefly rather than inventing specifics.
- NEVER include raw markdown/kramdown syntax like {:target="_blank"} in responses.
- Use ## or ### for section headers, never # (H1). Keep responses conversational, not document-like.

TOPICS: Accounts, SSH, Slurm jobs, storage, Python, R, MATLAB, GPUs, containers, and more."""


# --- Streamlit App ---
st.set_page_config(page_title="Sage", page_icon="🤖", layout="wide", initial_sidebar_state="collapsed")

# CSS with variables for theming and responsive design
st.markdown("""
<style>
    /* ===== CSS VARIABLES ===== */
    :root {
        /* Primary gradient — UChicago Maroon */
        --brand: #800000;
        --brand-rgb: 128 0 0;
        --gradient-start: #800000;
        --gradient-end: #a5122a;
        --gradient: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));

        /* Colors */
        --text-primary: #e5e7eb;
        --text-secondary: #9ca3af;
        --text-dark: #374151;
        --border-default: #e5e7eb;
        --border-focus: #800000;

        /* Shadows */
        --shadow-sm: 0 2px 8px rgba(128, 0, 0, 0.3);
        --shadow-md: 0 4px 15px rgba(0, 0, 0, 0.1);
        --shadow-lg: 0 8px 25px rgba(128, 0, 0, 0.2);

        /* Spacing */
        --space-xs: 0.25rem;
        --space-sm: 0.5rem;
        --space-md: 1rem;
        --space-lg: 1.5rem;
        --space-xl: 2rem;

        /* Sizing */
        --content-max: min(820px, 90vw);
        --input-max: min(780px, 85vw);
        --user-bubble-max: 75%;
        --radius-sm: 8px;
        --radius-md: 16px;
        --radius-lg: 24px;

        /* Transitions */
        --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }

    /* ===== BASE RESETS ===== */
    .stDeployButton, #MainMenu, footer {display: none !important;}
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display: none !important;}

    .main .block-container {
        padding-top: 0 !important;
        padding-bottom: 0;
        max-width: var(--content-max);
    }

    [data-testid="stVerticalBlock"] > div {
        margin-bottom: 0 !important;
        padding-bottom: 0 !important;
    }

    [data-testid="stVerticalBlock"] { gap: 0 !important; }
    .stMarkdown { margin: 0 !important; padding: 0 !important; }
    .element-container { margin: 0 !important; padding: 0 !important; }

    [data-testid="stMainBlockContainer"] { padding-top: 0 !important; }

    html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        overflow-x: hidden !important;
    }

    /* ===== TRASH BUTTON ===== */
    .st-key-trash-wrapper {
        position: fixed;
        top: 10px;
        right: 20px;
        z-index: 1000;
    }

    .st-key-trash-wrapper .stButton > button {
        background: rgba(31, 41, 55, 0.8) !important;
        border: 1px solid #374151 !important;
        border-radius: var(--radius-sm) !important;
        padding: 6px 10px !important;
        min-height: 36px !important;
        min-width: 36px !important;
        backdrop-filter: blur(8px);
        transition: var(--transition) !important;
    }

    .st-key-trash-wrapper .stButton > button:hover {
        background: rgba(239, 68, 68, 0.2) !important;
        border-color: #ef4444 !important;
    }

    /* ===== WELCOME SCREEN ===== */
    .welcome-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        padding: clamp(1rem, 3vw, 1.5rem) var(--space-md);
        margin-top: clamp(7vh, 12vw, 14vh);
        margin-bottom: 0.5rem;
        animation: fadeInDown 0.6s ease-out;
    }

    @keyframes fadeInDown {
        from { opacity: 0; transform: translateY(-20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .welcome-title {
        font-size: clamp(1.6rem, 4.5vw, 2.4rem);
        font-weight: 700;
        letter-spacing: -0.01em;
        color: var(--brand); /* solid fallback if background-clip is unsupported */
        background: var(--gradient);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: var(--space-sm);
        animation: fadeInUp 0.6s ease-out 0.3s both;
    }

    .welcome-subtitle {
        font-size: clamp(0.9rem, 2vw, 1.05rem);
        color: var(--text-secondary);
        max-width: 34rem;
        margin: 0 auto var(--space-md);
        line-height: 1.55;
        animation: fadeInUp 0.6s ease-out 0.4s both;
    }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* ===== EXAMPLES GRID ===== */
    .st-key-examples-grid {
        max-width: min(560px, 85vw);
        margin: 0 auto;
        padding: 0 var(--space-md);
    }

    .st-key-examples-grid [data-testid="stHorizontalBlock"] {
        gap: 0.6rem !important;
        margin-bottom: 0.6rem !important;
    }

    .st-key-examples-grid .stButton button {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-align: center !important;
        width: 100% !important;
        /* Fixed height so every card is identical regardless of question length. */
        height: 66px !important;
        min-height: 66px !important;
        padding: 10px 16px !important;
        background: linear-gradient(145deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.02) 100%);
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 14px !important;
        font-size: clamp(0.76rem, 1.8vw, 0.88rem) !important;
        font-weight: 500 !important;
        line-height: 1.3 !important;
        color: var(--text-primary) !important;
        transition: var(--transition) !important;
        backdrop-filter: blur(10px);
        box-shadow: var(--shadow-md) !important;
        /* Resting state is visible; the animation only fades it in. */
        opacity: 1;
        transform: translateY(0);
        animation: exampleFadeIn 0.5s ease-out both;
    }

    /* Kill default paragraph margins inside the button so text centers cleanly. */
    .st-key-examples-grid .stButton button p { margin: 0 !important; }

    .st-key-examples-grid .stButton button:nth-child(1) { animation-delay: 0.3s; }
    .st-key-examples-grid .stButton button:nth-child(2) { animation-delay: 0.45s; }

    @keyframes exampleFadeIn {
        from { opacity: 0; transform: translateY(25px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .st-key-examples-grid .stButton button:hover {
        background: linear-gradient(145deg, rgba(128, 0, 0, 0.25) 0%, rgba(165, 18, 42, 0.25) 100%);
        border-color: rgba(128, 0, 0, 0.5) !important;
        transform: translateY(-3px) !important;
        box-shadow: var(--shadow-lg) !important;
    }

    .st-key-examples-grid .stButton button:active {
        transform: translateY(-1px) !important;
    }

    /* ===== CHAT INPUT ===== */
    .stChatInput {
        max-width: var(--input-max) !important;
        margin: 0 auto !important;
        position: relative !important;
        z-index: 100 !important;
    }

    [data-testid="stChatInput"] {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }

    [data-testid="stChatInput"] ~ *,
    * + [data-testid="stChatInput"] {
        margin-bottom: 0 !important;
        padding-bottom: 0 !important;
    }

    .stChatInput > div {
        border-radius: var(--radius-lg) !important;
        border: 2px solid var(--border-default) !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1) !important;
        min-height: 56px !important;
        display: flex !important;
        align-items: center !important;
        padding-left: 50px !important;
        position: relative !important;
        z-index: 100 !important;
        transition: var(--transition) !important;
    }

    .stChatInput > div:focus-within {
        border-color: var(--border-focus) !important;
        box-shadow: 0 4px 20px rgba(128, 0, 0, 0.25) !important;
    }

    .stChatInput textarea {
        font-size: clamp(0.95rem, 2.5vw, 1.1rem) !important;
        padding: 16px 24px !important;
        line-height: 1.5 !important;
        display: flex !important;
        align-items: center !important;
        min-height: 24px !important;
        height: auto !important;
        resize: none !important;
        vertical-align: middle !important;
        position: relative !important;
        z-index: 101 !important;
    }

    .stChatInput textarea:not(:focus) {
        padding-top: 16px !important;
        padding-bottom: 16px !important;
    }

    .stChatInput textarea::placeholder {
        font-size: clamp(0.95rem, 2.5vw, 1.1rem) !important;
        color: var(--text-secondary) !important;
        line-height: 1.5 !important;
    }

    .stChatInput div[data-baseweb="textarea"] { padding: 0 !important; }
    .stChatInput div[data-baseweb="base-input"] {
        min-height: 56px !important;
        display: flex !important;
        align-items: center !important;
    }

    /* ===== FILE UPLOADER (hidden) ===== */
    [data-testid="stFileUploader"] {
        position: absolute !important;
        width: 1px !important;
        height: 1px !important;
        padding: 0 !important;
        margin: -1px !important;
        overflow: hidden !important;
        clip: rect(0, 0, 0, 0) !important;
        white-space: nowrap !important;
        border: 0 !important;
    }

    /* ===== USER MESSAGES ===== */
    .user-message {
        display: flex;
        justify-content: flex-end;
        margin: clamp(1.5rem, 3vw, 2.5rem) 0 clamp(0.75rem, 2vw, 1.25rem) 0;
        padding-right: clamp(0.25rem, 2vw, 1rem);
    }

    .user-bubble, .user-bubble-with-attachment {
        background: var(--gradient);
        color: white;
        padding: 12px 18px;
        border-radius: 18px 18px 4px 18px;
        font-size: clamp(0.85rem, 2vw, 0.95rem);
        line-height: 1.5;
        max-width: var(--user-bubble-max);
        box-shadow: var(--shadow-sm);
        overflow-wrap: break-word !important;
        word-wrap: break-word !important;
    }

    .attachment-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: rgba(255,255,255,0.2);
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        margin-bottom: 8px;
    }

    /* ===== ASSISTANT MESSAGES ===== */
    .assistant-wrapper {
        margin: clamp(0.5rem, 1.5vw, 1rem) 0 clamp(1.5rem, 4vw, 3rem) 0;
    }

    .stChatMessage {
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
        max-width: 100% !important;
        width: auto !important;
    }

    /* Constrain assistant markdown content */
    .stChatMessage p {
        max-width: 100% !important;
        overflow-wrap: break-word !important;
        word-wrap: break-word !important;
        margin-top: 0 !important;
    }

    .stChatMessage p:first-child {
        margin-top: 0 !important;
    }

    .stChatMessage > div {
        margin-top: 0 !important;
    }

    /* Chat message content */
    .stChatMessage > div:nth-child(2) {
        max-width: 100% !important;
        flex: 1 !important;
    }

    /* Constrain code blocks to content width so copy button positions correctly */
    .stChatMessage div[data-testid="stCodeBlock"] {
        position: relative !important;
        width: fit-content !important;
        max-width: min(700px, 80vw) !important;
        min-width: min(140px, 45vw) !important;
    }

    .stChatMessage div[data-testid="stCodeBlock"] pre {
        max-width: 100% !important;
        overflow-x: auto !important;
    }

    .stChatMessage div[data-testid="stCodeBlock"] code {
        max-width: 100% !important;
    }

    /* Hide Streamlit's native copy button - we replace it with our own */
    .stChatMessage div[data-testid="stCodeBlock"] > button,
    .stChatMessage div[data-testid="stCodeBlock"] > div > button {
        display: none !important;
    }

    /* Hide assistant avatar - cleaner layout */
    .stChatMessage [data-testid="chatAvatarIcon-assistant"],
    .stChatMessage img[data-testid="chatAvatarIcon-assistant"] {
        display: none !important;
    }
    .stChatMessage > div:first-child {
        width: 0 !important;
        min-width: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        overflow: hidden !important;
    }

    /* ===== CHAT CONTAINER ===== */
    .chat-container {
        padding-bottom: 100px;
        padding-top: 0;
    }

    /* Reduce space below chat input */
    [data-testid="stBottomBlockContainer"] {
        padding-bottom: 0.5rem !important;
    }

    /* Fine-print AI disclaimer, pinned just below the chat input */
    [data-testid="stBottomBlockContainer"]::after {
        content: "AI can make mistakes. Please double-check important responses.";
        display: block;
        text-align: center;
        font-size: 0.7rem;
        line-height: 1.3;
        color: var(--text-secondary);
        opacity: 0.75;
        padding: 6px 1rem 0;
    }

    /* Tone down response headers in chat */
    .stChatMessage h1 { font-size: 1.4rem !important; }
    .stChatMessage h2 { font-size: 1.2rem !important; }
    .stChatMessage h3 { font-size: 1.05rem !important; }

    /* Soften inline code in chat */
    .stChatMessage code:not(pre code) {
        background: rgba(128, 0, 0, 0.15) !important;
        color: #f0a8ac !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 0.88em !important;
    }

    /* Hide Streamlit dev button */
    [data-testid="manage-app-button"] { display: none !important; }

    .chat-container > div:first-child {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }

    /* First user message - tighter to top */
    .chat-container > div:first-child .user-message {
        margin-top: 0 !important;
    }

    /* ===== STATUS & STREAMING ===== */
    .search-status {
        padding: 0.25rem 1rem;
        margin: 0.75rem 0 1.5rem 0;
        display: flex;
        align-items: center;
        gap: 8px;
        max-width: var(--user-bubble-max);
    }

    .search-text {
        color: var(--brand); /* solid fallback if background-clip is unsupported */
        background: linear-gradient(
            90deg,
            var(--gradient-start) 0%,
            var(--gradient-end) 50%,
            var(--gradient-start) 100%
        );
        background-size: 200% 100%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: shimmer 1.5s ease-in-out infinite;
        font-weight: 600;
        font-size: clamp(0.85rem, 2vw, 0.95rem);
    }

    @keyframes shimmer {
        0% { background-position: 100% 0; }
        100% { background-position: -100% 0; }
    }

    /* Streaming dots animation */
    .streaming-dots {
        display: inline-flex;
        gap: 4px;
        margin-left: 8px;
    }

    .streaming-dots span {
        width: 6px;
        height: 6px;
        background: var(--gradient-start);
        border-radius: 50%;
        animation: bounceDot 1.4s ease-in-out infinite;
    }

    .streaming-dots span:nth-child(1) { animation-delay: 0s; }
    .streaming-dots span:nth-child(2) { animation-delay: 0.2s; }
    .streaming-dots span:nth-child(3) { animation-delay: 0.4s; }

    @keyframes bounceDot {
        0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
        40% { transform: scale(1); opacity: 1; }
    }

    /* Pulsing circle icon */
    .search-status .spinner {
        display: inline-block;
        width: 10px;
        height: 10px;
        background: var(--gradient);
        border-radius: 50%;
        animation: pulse 1.5s ease-in-out infinite;
    }

    @keyframes pulse {
        0%, 100% { transform: scale(0.6); opacity: 0.4; }
        50% { transform: scale(1.1); opacity: 1; }
    }

    /* ===== ERROR HANDLING ===== */
    .error-container {
        background: linear-gradient(135deg, rgba(239, 68, 68, 0.15) 0%, rgba(220, 38, 38, 0.1) 100%);
        border: 1px solid rgba(239, 68, 68, 0.3);
        border-radius: var(--radius-md);
        padding: var(--space-md) var(--space-lg);
        margin: var(--space-md) 0;
        text-align: center;
    }

    .error-icon {
        font-size: 1.5rem;
        margin-bottom: var(--space-sm);
    }

    .error-message {
        color: #fef2f2;
        font-size: 0.95rem;
        margin-bottom: var(--space-md);
    }

    .error-container .stButton > button {
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
        border: none !important;
        border-radius: var(--radius-sm) !important;
        padding: 8px 20px !important;
        color: white !important;
        font-weight: 500 !important;
        transition: var(--transition) !important;
    }

    .error-container .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3) !important;
    }

    /* ===== HIDE ANCHOR LINKS ===== */
    .stMarkdown a.header-anchor,
    .stMarkdown h1 a, .stMarkdown h2 a, .stMarkdown h3 a,
    .stMarkdown h4 a, .stMarkdown h5 a, .stMarkdown h6 a,
    a[href^="#"], a:empty {
        display: none !important;
    }

    /* ===== RESPONSIVE: MOBILE ===== */
    @media (max-width: 640px) {
        .st-key-examples-grid [data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
            gap: 0.5rem !important;
        }

        .st-key-examples-grid .stButton button {
            width: 100% !important;
        }

        .user-message {
            padding-right: 0 !important;
        }

        .user-bubble, .user-bubble-with-attachment {
            max-width: 85%;
        }

        .st-key-trash-wrapper {
            top: 5px;
            right: 10px;
        }
    }

    /* ===== RESPONSIVE: TABLET ===== */
    @media (min-width: 641px) and (max-width: 1024px) {
        .st-key-examples-grid {
            max-width: min(560px, 85vw);
        }
    }

    /* ===== KEYBOARD FOCUS (incl. JS-injected buttons) ===== */
    #paperclip-btn:focus-visible,
    .rcc-copy-btn:focus-visible,
    .stChatInput button:focus-visible,
    .stButton button:focus-visible {
        outline: 2px solid var(--border-focus) !important;
        outline-offset: 2px !important;
    }

    /* ===== LIGHT MODE ===== */
    @media (prefers-color-scheme: light) {
        :root {
            --text-primary: #374151;
            --text-secondary: #6b7280;
            --text-dark: #1f2937;
            --border-default: #d1d5db;
        }

        .st-key-examples-grid .stButton button {
            background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #e2e8f0 !important;
            color: var(--text-dark) !important;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.06) !important;
        }

        .st-key-examples-grid .stButton button:hover {
            background: linear-gradient(145deg, #fbeaec 0%, #f6d9dd 100%);
            border-color: #c98a92 !important;
        }

        .error-container {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, rgba(220, 38, 38, 0.05) 100%);
            border-color: rgba(239, 68, 68, 0.2);
        }

        .error-message {
            color: #991b1b;
        }

        .stChatInput > div {
            border-color: #d1d5db !important;
        }

        /* Light mode: inline code */
        .stChatMessage code:not(pre code) {
            background: rgba(128, 0, 0, 0.12) !important;
            color: #8a1020 !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# JavaScript for paperclip button, scroll control, send-blocking, and animations
import streamlit.components.v1 as components
components.html("""
<script>
(function() {
    const doc = window.parent.document;
    let initialized = false;

    function updateScrollBehavior() {
        const chatContainer = doc.querySelector('.chat-container');
        const appContainer = doc.querySelector('[data-testid="stAppViewContainer"]');
        const mainContainer = doc.querySelector('[data-testid="stMain"]');
        const hasChat = !!chatContainer;

        if (appContainer) appContainer.style.overflow = hasChat ? 'auto' : 'hidden';
        if (mainContainer) mainContainer.style.overflow = hasChat ? 'auto' : 'hidden';
        doc.body.style.overflow = hasChat ? 'auto' : 'hidden';
    }

    function addPaperclipButton() {
        const chatInput = doc.querySelector('[data-testid="stChatInput"]');
        if (!chatInput || doc.getElementById('paperclip-btn')) return;

        const btn = doc.createElement('button');
        btn.id = 'paperclip-btn';
        btn.type = 'button';
        btn.innerHTML = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';
        btn.title = 'Attach file (PDF, TXT, MD, PY, JSON, CSV)';
        btn.setAttribute('aria-label', 'Attach a file (PDF, TXT, MD, PY, JSON, CSV)');
        btn.style.cssText = 'position:absolute;left:12px;top:50%;transform:translateY(-50%);z-index:1000;background:transparent;border:none;cursor:pointer;padding:8px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#6b7280;transition:all 0.2s;';

        btn.onmouseenter = function() { this.style.background='rgba(128,0,0,0.1)'; this.style.color='#800000'; };
        btn.onmouseleave = function() { this.style.background='transparent'; this.style.color='#6b7280'; };

        btn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            const fileInput = doc.querySelector('[data-testid="stFileUploader"] input[type="file"]');
            if (fileInput) fileInput.click();
        };

        chatInput.style.position = 'relative';
        chatInput.insertBefore(btn, chatInput.firstChild);
    }

    function styleAttachmentChip() {
        const buttons = doc.querySelectorAll('.stButton button');
        let chipButton = null;
        let chipContainer = null;

        buttons.forEach(btn => {
            if (btn.innerText && btn.innerText.includes('✕')) {
                chipButton = btn;
                chipContainer = btn.closest('.stButton');
            }
        });

        if (!chipButton || !chipContainer || chipButton.dataset.styled === 'true') return;
        chipButton.dataset.styled = 'true';

        chipButton.style.cssText = `
            background: linear-gradient(135deg, rgba(34, 197, 94, 0.2) 0%, rgba(34, 197, 94, 0.1) 100%) !important;
            border: 1px solid rgba(34, 197, 94, 0.4) !important;
            border-radius: 16px !important;
            padding: 6px 14px !important;
            color: #22c55e !important;
            font-size: 0.8rem !important;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1) !important;
            width: auto !important;
            min-width: auto !important;
            display: inline-flex !important;
            align-items: center !important;
            cursor: pointer !important;
            margin: 0 !important;
        `;

        chipContainer.style.cssText = 'width: auto !important; display: inline-block !important; margin: 0 !important; padding: 0 !important;';

        let parent = chipContainer.parentElement;
        let levelsUp = 0;
        while (parent && parent !== doc.body && levelsUp < 5) {
            if (parent.getAttribute && parent.getAttribute('data-testid') === 'stVerticalBlock') {
                parent.style.cssText = 'max-width: min(800px, 95vw) !important; margin: 0 auto !important; padding: 0 1rem !important; display: flex !important; justify-content: flex-start !important; gap: 0 !important;';
                break;
            }
            parent = parent.parentElement;
            levelsUp++;
        }

        chipButton.addEventListener('mouseenter', function() {
            this.style.background = 'linear-gradient(135deg, rgba(239, 68, 68, 0.2) 0%, rgba(239, 68, 68, 0.1) 100%)';
            this.style.borderColor = 'rgba(239, 68, 68, 0.5)';
            this.style.color = '#ef4444';
        });

        chipButton.addEventListener('mouseleave', function() {
            this.style.background = 'linear-gradient(135deg, rgba(34, 197, 94, 0.2) 0%, rgba(34, 197, 94, 0.1) 100%)';
            this.style.borderColor = 'rgba(34, 197, 94, 0.4)';
            this.style.color = '#22c55e';
        });
    }

    // Animate example buttons with staggered delays
    function animateExampleButtons() {
        const allButtons = doc.querySelectorAll('.stButton button');
        const exampleButtons = [];

        allButtons.forEach(btn => {
            const text = btn.innerText || '';
            if (text.includes('How do I') || text.includes('What are the')) {
                exampleButtons.push(btn);
            }
        });

        if (exampleButtons.length === 0) return;

        const delays = [0.3, 0.45, 0.6, 0.75, 0.9, 1.05];

        exampleButtons.forEach((btn, idx) => {
            if (btn.dataset.animated === 'true') return;
            btn.dataset.animated = 'true';
            btn.style.animationDelay = (delays[idx] || 0) + 's';

            btn.addEventListener('mouseenter', function() {
                this.style.background = 'linear-gradient(145deg, rgba(128, 0, 0, 0.25) 0%, rgba(165, 18, 42, 0.25) 100%)';
                this.style.borderColor = 'rgba(128, 0, 0, 0.5)';
                this.style.transform = 'translateY(-3px)';
                this.style.boxShadow = '0 8px 25px rgba(128, 0, 0, 0.25)';
            });

            btn.addEventListener('mouseleave', function() {
                this.style.background = 'linear-gradient(145deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.03) 100%)';
                this.style.borderColor = 'rgba(255,255,255,0.12)';
                this.style.transform = 'translateY(0)';
                this.style.boxShadow = '0 4px 15px rgba(0, 0, 0, 0.1)';
            });
        });
    }

    // Fix copy button position in code blocks
    function fixCodeBlockCopyButtons() {
        var codeBlocks = doc.querySelectorAll('.stChatMessage div[data-testid="stCodeBlock"]');
        codeBlocks.forEach(function(block) {
            if (block.dataset.copyFixed === 'true') return;
            var pre = block.querySelector('pre');
            var code = block.querySelector('code');
            if (!pre || !code) return;

            // Create our own copy button
            var COPY_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
            var CHECK_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
            var copyBtn = doc.createElement('button');
            copyBtn.type = 'button';
            copyBtn.className = 'rcc-copy-btn';
            copyBtn.innerHTML = COPY_SVG;
            copyBtn.title = 'Copy to clipboard';
            copyBtn.setAttribute('aria-label', 'Copy code to clipboard');
            copyBtn.style.cssText = 'position:absolute;top:8px;right:8px;z-index:10;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:6px;padding:4px 6px;cursor:pointer;color:#6b7280;display:flex;align-items:center;justify-content:center;transition:all 0.2s;';

            copyBtn.onmouseenter = function() {
                this.style.background = 'rgba(255,255,255,0.2)';
                this.style.color = '#e5e7eb';
            };
            copyBtn.onmouseleave = function() {
                this.style.background = 'rgba(255,255,255,0.1)';
                this.style.color = '#6b7280';
            };

            function copyText(text) {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    return navigator.clipboard.writeText(text);
                }
                // Fallback for insecure (http) contexts without the async clipboard API.
                return new Promise(function(resolve, reject) {
                    try {
                        var ta = doc.createElement('textarea');
                        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
                        doc.body.appendChild(ta); ta.focus(); ta.select();
                        var ok = doc.execCommand('copy');
                        doc.body.removeChild(ta);
                        ok ? resolve() : reject();
                    } catch (err) { reject(err); }
                });
            }

            copyBtn.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                var text = code.innerText || code.textContent || '';
                copyText(text).then(function() {
                    copyBtn.innerHTML = CHECK_SVG;
                    copyBtn.setAttribute('aria-label', 'Copied to clipboard');
                    setTimeout(function() {
                        copyBtn.innerHTML = COPY_SVG;
                        copyBtn.setAttribute('aria-label', 'Copy code to clipboard');
                    }, 2000);
                }).catch(function() {});
            };

            // pre is the dark box - make it the positioning context
            pre.style.setProperty('position', 'relative', 'important');
            pre.appendChild(copyBtn);

            block.dataset.copyFixed = 'true';
        });
    }

    // Block send button and Enter key during processing; grey out send button
    function blockSendDuringProcessing() {
        var isProcessing = !!doc.getElementById('processing-signal');
        var chatInputContainer = doc.querySelector('[data-testid="stChatInput"]');
        if (!chatInputContainer) return;

        // Use a persistent style tag to override Streamlit's button color during processing
        var styleId = 'processing-send-block-style';
        var existingStyle = doc.getElementById(styleId);
        var sendBtn = chatInputContainer.querySelector('button');
        if (isProcessing) {
            if (!existingStyle) {
                var style = doc.createElement('style');
                style.id = styleId;
                style.textContent = '[data-testid="stChatInput"] button { background: #374151 !important; opacity: 0.5 !important; pointer-events: none !important; cursor: not-allowed !important; }';
                doc.head.appendChild(style);
            }
            // Expose the disabled state to assistive tech, not just visually.
            if (sendBtn) sendBtn.setAttribute('aria-disabled', 'true');
        } else {
            if (existingStyle) {
                existingStyle.remove();
            }
            if (sendBtn) sendBtn.removeAttribute('aria-disabled');
        }

        // Block Enter key from submitting during processing
        var textarea = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (textarea && !textarea.dataset.sendBlocked) {
            textarea.dataset.sendBlocked = 'true';
            textarea.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    var processing = !!doc.getElementById('processing-signal');
                    if (processing) {
                        e.preventDefault();
                        e.stopPropagation();
                        e.stopImmediatePropagation();
                        return false;
                    }
                }
            }, true);
        }
    }

    function init() {
        updateScrollBehavior();
        addPaperclipButton();
        styleAttachmentChip();
        animateExampleButtons();
        fixCodeBlockCopyButtons();
        blockSendDuringProcessing();
        initialized = true;
    }

    // Use requestAnimationFrame for faster initial render
    function scheduleInit() {
        if (!initialized) {
            requestAnimationFrame(init);
            setTimeout(scheduleInit, 50);
        }
    }
    scheduleInit();

    // Auto-scroll ONLY while a response is generating, and only if the user is already
    // near the bottom — so they can freely scroll up to read earlier messages.
    var lastScrollTime = 0;
    var NEAR_BOTTOM_PX = 140;
    function autoScroll() {
        var now = Date.now();
        if (now - lastScrollTime < 150) return;
        lastScrollTime = now;

        // Don't pin the page once generation has finished.
        if (!doc.getElementById('processing-signal')) return;

        var targets = [
            doc.querySelector('[data-testid="stAppViewContainer"]'),
            doc.querySelector('[data-testid="stMain"]'),
            doc.documentElement,
            doc.body
        ];

        for (var i = 0; i < targets.length; i++) {
            var el = targets[i];
            if (el && el.scrollHeight > el.clientHeight) {
                var distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
                if (distanceFromBottom <= NEAR_BOTTOM_PX) {
                    el.scrollTop = el.scrollHeight;
                }
            }
        }
    }

    // Keep scrolling during streaming - poll for new content
    setInterval(autoScroll, 200);

    // Auto-focus on typing — press any character key and start typing in the chat box.
    doc.addEventListener('keydown', function(e) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.ctrlKey || e.altKey || e.metaKey) return;
        const ignore = ['Escape','Tab','CapsLock','Shift','Control','Alt','Meta','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','F1','F2','F3','F4','F5','F6','F7','F8','F9','F10','F11','F12'];
        if (ignore.includes(e.key)) return;
        const input = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (input) input.focus();
    });

    // Lightweight observer - only for scroll and attachment chip
    const observer = new MutationObserver(function() {
        updateScrollBehavior();
        if (!doc.getElementById('paperclip-btn')) addPaperclipButton();
        styleAttachmentChip();
        animateExampleButtons();
        fixCodeBlockCopyButtons();
        blockSendDuringProcessing();
        autoScroll();
    });
    observer.observe(doc.body, { childList: true, subtree: true });
})();
</script>
""", height=0)

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "processing" not in st.session_state:
    st.session_state.processing = False
if "mistral_client" not in st.session_state:
    st.session_state.mistral_client = get_mistral_client()
if "uploaded_file_data" not in st.session_state:
    st.session_state.uploaded_file_data = None
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# Debug indicator (shows API status at startup)
logger.info(f"Mistral client initialized: {st.session_state.mistral_client is not None}")
logger.info(f"MISTRAL_API_KEY set: {bool(MISTRAL_API_KEY)}")

# --- Mistral API Helper Functions ---
def mistral_collect_response(stream):
    """Collect response from Mistral streaming API."""
    tool_calls_dict = {}
    content_buffer = ""
    message = None
    
    try:
        for chunk in stream:
            # Match the working pattern from mistral_tool_calling.py
            if not chunk.data or not chunk.data.choices:
                continue
            
            delta = chunk.data.choices[0].delta
            
            # Extract content
            if delta.content:
                content_buffer += delta.content
            
            # Extract tool calls
            if delta.tool_calls:
                for tool_call_delta in delta.tool_calls:
                    idx = tool_call_delta.index
                    if idx not in tool_calls_dict:
                        tool_calls_dict[idx] = {
                            "id": tool_call_delta.id or "",
                            "name": "",
                            "arguments": ""
                        }
                    
                    if tool_call_delta.id:
                        tool_calls_dict[idx]["id"] = tool_call_delta.id
                    
                    if tool_call_delta.function:
                        if tool_call_delta.function.name:
                            tool_calls_dict[idx]["name"] = tool_call_delta.function.name
                        if tool_call_delta.function.arguments:
                            tool_calls_dict[idx]["arguments"] += tool_call_delta.function.arguments
            
            # Store the last message for later use
            if hasattr(chunk.data.choices[0], 'message'):
                message = chunk.data.choices[0].message
                
    except Exception as e:
        logger.error(f"Error in mistral_collect_response: {e}")
        logger.debug(traceback.format_exc())
        raise
    
    # Convert tool_calls_dict to list format compatible with the app
    tool_use_blocks = []
    for tc in tool_calls_dict.values():
        if tc["name"]:
            try:
                tool_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                tool_input = {}
            tool_use_blocks.append({
                "id": tc["id"],
                "name": tc["name"],
                "input": tool_input
            })
    
    # Create a mock response object similar to Anthropic format
    from types import SimpleNamespace
    mock_content = [SimpleNamespace(type="text", text=content_buffer)] if content_buffer else []
    response = SimpleNamespace(content=mock_content)
    
    logger.debug(f"Mistral response collected: text_len={len(content_buffer)}, tool_calls={len(tool_use_blocks)}")
    
    return content_buffer, tool_use_blocks, response

def mistral_stream_generator(stream):
    """Generator that yields text chunks from Mistral streaming API for st.write_stream()."""
    tool_calls_dict = {}
    content_buffer = ""
    final_message_container = [None]
    tool_use_blocks = []
    
    def generator():
        nonlocal content_buffer
        try:
            for chunk in stream:
                # Match the working pattern from mistral_tool_calling.py
                if not chunk.data or not chunk.data.choices:
                    continue
                
                delta = chunk.data.choices[0].delta
                
                # Extract content and yield for streaming
                if delta.content:
                    content_buffer += delta.content
                    yield delta.content
                
                # Extract tool calls
                if delta.tool_calls:
                    for tool_call_delta in delta.tool_calls:
                        idx = tool_call_delta.index
                        if idx not in tool_calls_dict:
                            tool_calls_dict[idx] = {
                                "id": tool_call_delta.id or "",
                                "name": "",
                                "arguments": ""
                            }
                        
                        if tool_call_delta.id:
                            tool_calls_dict[idx]["id"] = tool_call_delta.id
                        
                        if tool_call_delta.function:
                            if tool_call_delta.function.name:
                                tool_calls_dict[idx]["name"] = tool_call_delta.function.name
                            if tool_call_delta.function.arguments:
                                tool_calls_dict[idx]["arguments"] += tool_call_delta.function.arguments
                                
        except Exception as e:
            logger.error(f"Error in mistral_stream_generator: {e}")
            logger.debug(traceback.format_exc())
            raise
        
        # After stream ends, process tool calls
        for tc in tool_calls_dict.values():
            if tc["name"]:
                try:
                    tool_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    tool_input = {}
                tool_use_blocks.append({
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tool_input
                })
        
        # Create mock response
        from types import SimpleNamespace
        mock_content = [SimpleNamespace(type="text", text=content_buffer)] if content_buffer else []
        final_message_container[0] = SimpleNamespace(content=mock_content)
    
    return generator(), tool_use_blocks, final_message_container


def extract_display_text(content):
    """Extract displayable text from message content."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        texts = []
        for block in content:
            if hasattr(block, 'type') and block.type == "text" and block.text:
                texts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                texts.append(block["text"])
        return "\n".join(texts)
    return ""


def wrap_generator_clear_status(gen, placeholder):
    """Wrap a generator to clear a status placeholder on the first yielded chunk."""
    first = True
    for chunk in gen:
        if first:
            placeholder.empty()
            first = False
        yield chunk
    if first:
        # Generator was empty, still need to clear
        placeholder.empty()


RCC_DOCS_BASE_URL = "https://rcc-uchicago.github.io/user-guide/"

def fix_markdown_links(text):
    """Convert internal doc links to real RCC documentation URLs; drop unresolvable ones."""
    def replace_link(match):
        link_text = match.group(1)
        link_target = match.group(2)

        if link_target.startswith(('http://', 'https://', 'mailto:')):
            return match.group(0)

        # search_docs ids look like 'docs/slurm/sbatch.md' or 'web/faqs.txt'.
        target = link_target
        if target.startswith('docs/'):
            target = target[len('docs/'):]
        elif target.startswith('web/'):
            # Website pages have no stable per-page docs URL; link to the guide root.
            return f'[{link_text}]({RCC_DOCS_BASE_URL})'

        if target.endswith('.md'):
            clean_path = target[:-3].lstrip('/')
            return f'[{link_text}]({RCC_DOCS_BASE_URL}{clean_path}/)'

        if target.startswith('#') or target == '':
            return link_text

        return f'[{link_text}]({RCC_DOCS_BASE_URL})'

    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, text)


def get_file_icon(filename: str) -> str:
    """Get appropriate icon for file type."""
    ext = filename.lower().split('.')[-1]
    icons = {
        'pdf': '📄', 'txt': '📝', 'md': '📝', 'py': '🐍', 'json': '📋', 'csv': '📊',
    }
    return icons.get(ext, '📎')


def render_user_message(content, file_info=None):
    """Render user message with optional file attachment."""
    escaped = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
    
    if file_info:
        icon = get_file_icon(file_info['filename'])
        file_badge = f'<div class="attachment-badge">{icon} {file_info["filename"]}</div>'
        st.markdown(f'<div class="user-message"><div class="user-bubble-with-attachment">{file_badge}{escaped}</div></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="user-message"><div class="user-bubble">{escaped}</div></div>', unsafe_allow_html=True)


def render_assistant_message(content):
    """Render assistant message."""
    content = fix_markdown_links(content)
    st.markdown('<div class="assistant-wrapper">', unsafe_allow_html=True)
    with st.chat_message("assistant"):
        st.markdown(content)
    st.markdown('</div>', unsafe_allow_html=True)


has_messages = len(st.session_state.messages) > 0

# Example questions
EXAMPLE_QUESTIONS = [
    ("🚀", "How do I connect to Midway via SSH?"),
    ("💾", "What are the storage quotas on Midway?"),
    ("⚙️", "How do I submit a batch job with sbatch?"),
    ("🐍", "How do I set up a Python environment?"),
    ("🎮", "How do I run PyTorch on GPUs?"),
    ("📊", "How do I check my allocation balance?"),
]

if not has_messages:
    # Welcome screen
    st.markdown('''
    <div class="welcome-container">
        <h1 class="welcome-title">What can I help you with?</h1>
        <p class="welcome-subtitle">Ask about accounts, SSH, Slurm jobs, storage, and software at the UChicago Research Computing Center — answered from the official docs.</p>
    </div>
    ''', unsafe_allow_html=True)

    # Example questions grid — the keyed container gives it a stable .st-key-examples-grid
    # class so the CSS actually scopes to these buttons.
    with st.container(key="examples-grid"):
        for row_start in range(0, len(EXAMPLE_QUESTIONS), 2):
            cols = st.columns(2, gap="medium")
            for offset, col in enumerate(cols):
                idx = row_start + offset
                if idx >= len(EXAMPLE_QUESTIONS):
                    continue
                icon, question = EXAMPLE_QUESTIONS[idx]
                with col:
                    if st.button(f"{icon} {question}", key=f"ex_{idx}", use_container_width=True):
                        st.session_state.messages.append({"role": "user", "content": question})
                        st.session_state.processing = True
                        # Don't let a stray attachment leak into an example question.
                        st.session_state.uploaded_file_data = None
                        st.session_state.uploader_key += 1
                        st.rerun()

else:
    # Chat mode — clear-chat button pinned top-right (keyed container so CSS applies)
    with st.container(key="trash-wrapper"):
        if st.button("🗑️", key="clear", help="Clear chat"):
            st.session_state.messages = []
            st.session_state.processing = False
            st.session_state.uploaded_file_data = None
            st.session_state.uploader_key += 1  # Reset the file uploader
            st.rerun()
    
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
    
    # When processing, skip the last user message in history since it will be rendered
    # by the processing block along with the streaming response
    messages_to_render = st.session_state.messages
    if st.session_state.processing and messages_to_render and messages_to_render[-1]["role"] == "user":
        messages_to_render = messages_to_render[:-1]
    
    for msg in messages_to_render:
        if msg["role"] == "user":
            display_text = msg.get("display_text", msg["content"] if isinstance(msg["content"], str) else "")
            file_info = msg.get("file_info")
            render_user_message(display_text, file_info)
        elif msg["role"] == "assistant" and msg.get("is_final"):
            text = extract_display_text(msg["content"])
            if text:
                render_assistant_message(text)
    
    # Display a friendly error message (the raw exception is logged server-side, not shown).
    if "last_error" in st.session_state:
        st.markdown('''
        <div class="error-container" role="alert">
            <div class="error-icon" aria-hidden="true">⚠️</div>
            <div class="error-message">Something went wrong reaching the assistant. Please try again.</div>
        </div>
        ''', unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("🔄 Try Again", key="dismiss_error", use_container_width=True):
                del st.session_state.last_error
                # Actually retry: re-run the failed question if it's still the last message.
                if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
                    st.session_state.processing = True
                st.rerun()
    
    st.markdown('</div>', unsafe_allow_html=True)

# Hidden file uploader
uploaded_file = st.file_uploader(
    "Upload",
    type=['pdf', 'txt', 'md', 'py', 'json', 'csv'],
    key=f"file_uploader_{st.session_state.uploader_key}",
    label_visibility="collapsed"
)

if uploaded_file is not None and st.session_state.uploaded_file_data is None:
    file_data = process_uploaded_file(uploaded_file)
    st.session_state.uploaded_file_data = file_data

# Surface a failed upload and clear it so it can't silently contaminate the next message.
if st.session_state.uploaded_file_data and st.session_state.uploaded_file_data.get("type") == "error":
    st.error(f"⚠️ {st.session_state.uploaded_file_data.get('message', 'Could not read that file.')}")
    st.session_state.uploaded_file_data = None
    st.session_state.uploader_key += 1

# Show attachment status as a compact chip above the chat input
if st.session_state.uploaded_file_data and st.session_state.uploaded_file_data.get("type") != "error":
    file_data = st.session_state.uploaded_file_data
    icon = get_file_icon(file_data.get("filename", "file"))
    filename = file_data.get("filename", "file")
    
    if st.button(f"{icon} {filename}  ✕", key="remove_attachment", type="secondary"):
        st.session_state.uploaded_file_data = None
        st.session_state.uploader_key += 1
        st.rerun()

# Chat input - always enabled so users can type while waiting for a response
# JS blocks the send button and Enter key during processing
prompt = st.chat_input("Ask any question about RCC...")

if prompt:
    file_data = st.session_state.uploaded_file_data
    message_content = build_message_content(prompt, file_data)
    
    msg_to_store = {
        "role": "user",
        "content": message_content,
        "display_text": prompt
    }
    
    if file_data and file_data["type"] != "error":
        msg_to_store["file_info"] = {
            "filename": file_data.get("filename", "file"),
            "type": file_data["type"]
        }
    
    st.session_state.messages.append(msg_to_store)
    st.session_state.processing = True
    st.session_state.uploaded_file_data = None
    st.session_state.uploader_key += 1  # Reset file uploader to clear attachment
    
    st.rerun()

# Process
if st.session_state.processing:
    # Hidden signal element that JS uses to detect processing state
    st.markdown('<div id="processing-signal" style="display:none"></div>', unsafe_allow_html=True)

    # Display user message first
    last_user_msg = st.session_state.messages[-1]
    display_text = last_user_msg.get("display_text", last_user_msg["content"] if isinstance(last_user_msg["content"], str) else "")
    file_info = last_user_msg.get("file_info")
    render_user_message(display_text, file_info)
    
    # Show initial status message with streaming indicator
    status_placeholder = st.empty()

    def show_status(text):
        status_placeholder.empty()
        sparkle_svg = '<span class="spinner" aria-hidden="true"></span>'
        with status_placeholder.container():
            st.markdown('<div class="assistant-wrapper">', unsafe_allow_html=True)
            with st.chat_message("assistant"):
                st.markdown(
                    f'<div class="search-status" role="status" aria-live="polite">{sparkle_svg}<span class="search-text">{text}</span><div class="streaming-dots" aria-hidden="true"><span></span><span></span><span></span></div></div>',
                    unsafe_allow_html=True
                )
            st.markdown('</div>', unsafe_allow_html=True)

    show_status("Thinking")
    
    # Debug: Log which client is available
    logger.debug(f"Mistral client available: {st.session_state.mistral_client is not None}")
    
    try:
        # Build the Mistral conversation with FULL history (user AND assistant turns) so
        # the model remembers its own prior answers on follow-up questions.
        mistral_conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in st.session_state.messages:
            if m["role"] == "user":
                content = m["content"]
                if isinstance(content, str):
                    mistral_conversation.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    text_parts = [b.get("text", "") for b in content
                                  if isinstance(b, dict) and b.get("type") == "text"]
                    if text_parts:
                        mistral_conversation.append({"role": "user", "content": " ".join(text_parts)})
            elif m["role"] == "assistant" and m.get("is_final"):
                atext = extract_display_text(m["content"])
                if atext:
                    mistral_conversation.append({"role": "assistant", "content": atext})

        logger.debug(f"Mistral conversation has {len(mistral_conversation)} messages")

        MAX_TOOL_ROUNDS = 6

        def _new_stream():
            return st.session_state.mistral_client.chat.stream(
                model=MISTRAL_MODEL,
                messages=mistral_conversation,
                tools=MISTRAL_TOOLS,
                tool_choice="auto",
            )

        def _render_answer(text):
            """Render (or re-render) the final answer with links fixed."""
            answer_area.empty()
            with answer_area.container():
                st.markdown('<div class="assistant-wrapper">', unsafe_allow_html=True)
                with st.chat_message("assistant"):
                    st.markdown(fix_markdown_links(text))
                st.markdown('</div>', unsafe_allow_html=True)

        # Stream the FIRST turn live. If the model asks for tools, this turn's text is
        # empty/preliminary and we resolve tools before answering; if not, the streamed text
        # IS the answer, so a plain question costs a single completion instead of two.
        answer_area = st.empty()
        with answer_area.container():
            st.markdown('<div class="assistant-wrapper">', unsafe_allow_html=True)
            with st.chat_message("assistant"):
                gen, tool_use_blocks, _final = mistral_stream_generator(_new_stream())
                streamed_text = st.write_stream(wrap_generator_clear_status(gen, status_placeholder))
            st.markdown('</div>', unsafe_allow_html=True)

        final_text = streamed_text or ""
        pre_text = streamed_text or ""

        if not tool_use_blocks:
            # No tools needed — re-render once with links fixed to avoid a broken-link flash.
            if final_text:
                _render_answer(final_text)
        else:
            rounds = 0
            while tool_use_blocks:
                if rounds >= MAX_TOOL_ROUNDS:
                    logger.warning("Max tool rounds reached; stopping tool loop.")
                    if not final_text:
                        final_text = ("I wasn't able to finish looking that up. "
                                      "Please try rephrasing your question.")
                    break
                rounds += 1
                answer_area.empty()
                show_status("Searching documentation")

                mistral_conversation.append({
                    "role": "assistant",
                    "content": pre_text,
                    "tool_calls": [
                        {
                            "id": tb["id"],
                            "type": "function",
                            "function": {"name": tb["name"], "arguments": json.dumps(tb["input"])},
                        }
                        for tb in tool_use_blocks
                    ],
                })
                for tb in tool_use_blocks:
                    tool_result = execute_tool(tb["name"], tb["input"])
                    mistral_conversation.append({
                        "role": "tool",
                        "tool_call_id": tb["id"],
                        "name": tb["name"],
                        "content": tool_result,
                    })

                # Next turn: another tool round, or the final answer.
                response_text, tool_use_blocks, _resp = mistral_collect_response(_new_stream())
                pre_text = response_text or ""
                if response_text:
                    final_text = response_text

            status_placeholder.empty()
            _render_answer(final_text)

        # Persist the final assistant text (JSON-serializable content).
        if final_text:
            st.session_state.messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": final_text}],
                "is_final": True,
            })
        # Clear any previous error
        if "last_error" in st.session_state:
            del st.session_state.last_error

    except Exception as e:
        status_placeholder.empty()
        error_msg = str(e)
        logger.error(f"Request failed: {error_msg}")
        logger.debug(traceback.format_exc())
        # Store error in session state so it persists after rerun
        st.session_state.last_error = error_msg
        # Keep the user message so they can see what they asked
        # Don't pop the message - let the user see it
    finally:
        st.session_state.processing = False
        st.rerun()

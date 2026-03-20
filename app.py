#!/usr/bin/env python3
"""
RCC User Guide AI Assistant - Streamlit App
A chatbot that answers questions using RCC documentation (RAG-only, no command-line tools).
File upload support for PDFs and text files via paperclip button.
Includes Mistral API as backup when primary MiniMax API fails.
"""
import os
import sys
import json
import random
import anthropic
import streamlit as st
from io import BytesIO
from mistralai.client import Mistral
import traceback

# --- API Configuration ---
# Primary API: MiniMax (via Anthropic SDK)
MINIMAX_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# Backup API: Mistral
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

if not MINIMAX_API_KEY and not MISTRAL_API_KEY:
    st.error("❌ No API keys found. Please set ANTHROPIC_API_KEY and/or MISTRAL_API_KEY.")
    st.stop()

# Show warning if only one API is available
if MINIMAX_API_KEY and not MISTRAL_API_KEY:
    pass  # Primary available, backup not - still functional
elif MISTRAL_API_KEY and not MINIMAX_API_KEY:
    pass  # Only backup available - will use it as primary

# Supported file types: PDF and text-based files (txt, md, py, json, csv)
# We extract text client-side and send to the model as plain text.
MINIMAX_MODEL = "MiniMax-M2.7"
MISTRAL_MODEL = "mistral-large-latest"
DOCS_BASE_PATH = "./docs"
WEB_BASE_PATH = "./web"


def get_minimax_client():
    """Create an Anthropic client configured for MiniMax."""
    if not MINIMAX_API_KEY:
        return None
    try:
        return anthropic.Anthropic(
            api_key=MINIMAX_API_KEY,
            base_url="https://api.minimax.io/anthropic"
        )
    except Exception as e:
        print(f"Failed to create MiniMax client: {e}")
        return None


def get_mistral_client():
    """Create a Mistral client as backup."""
    if not MISTRAL_API_KEY:
        return None
    try:
        return Mistral(api_key=MISTRAL_API_KEY)
    except Exception as e:
        print(f"Failed to create Mistral client: {e}")
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


# --- Documentation Reader (RAG) ---
def read_document(file_path: str, base_path: str = None) -> str:
    """Read a markdown or text document and return its contents."""
    if base_path is None:
        base_path = DOCS_BASE_PATH
    full_path = os.path.join(base_path, file_path)
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if len(content) > 15000:
            content = content[:15000] + "\n\n[... Document truncated due to length ...]"
        return content
    except FileNotFoundError:
        return f"Error: Document '{file_path}' not found."
    except Exception as e:
        return f"Error reading document: {str(e)}"


def read_web_document(file_path: str) -> str:
    """Read a web-scraped text document and return its contents."""
    return read_document(file_path, WEB_BASE_PATH)


# --- Document path mappings ---
DOC_PATHS = {
    "read_accounts_doc": "101/accounts.md",
    "read_connecting_doc": "101/connecting.md",
    "read_jobs_tutorial_doc": "101/jobs.md",
    "read_allocations_doc": "101/allocations.md",
    "read_software_tutorial_doc": "101/software.md",
    "read_data_tutorial_doc": "101/data.md",
    "read_policies_doc": "101/policies.md",
    "read_glossary_doc": "101/glossary.md",
    "read_mistakes_doc": "101/mistakes.md",
    "read_helpdesk_doc": "101/helpdesk.md",
    "read_ecosystems_doc": "101/ecosystems.md",
    "read_clusters_doc": "clusters.md",
    "read_partitions_doc": "partitions.md",
    "read_beagle3_doc": "beagle3-overview.md",
    "read_slurm_main_doc": "slurm/main.md",
    "read_sinteractive_doc": "slurm/sinteractive.md",
    "read_sbatch_doc": "slurm/sbatch.md",
    "read_slurm_faq_doc": "slurm/faq.md",
    "read_storage_main_doc": "storage/main.md",
    "read_storage_faq_doc": "storage/faq.md",
    "read_ssh_main_doc": "ssh/main.md",
    "read_ssh_advanced_doc": "ssh/advance.md",
    "read_ssh_faq_doc": "ssh/faq.md",
    "read_thinlinc_doc": "thinlinc/main.md",
    "read_ondemand_doc": "open_ondemand/open_ondemand.md",
    "read_globus_transfer_doc": "globus/transfer-files.md",
    "read_globus_share_doc": "globus/share-files.md",
    "read_samba_doc": "samba.md",
    "read_software_index_doc": "software/index.md",
    "read_python_doc": "software/apps-and-envs/python.md",
    "read_tensorflow_pytorch_doc": "software/apps-and-envs/tf-and-torch.md",
    "read_r_doc": "software/apps-and-envs/r.md",
    "read_matlab_doc": "software/apps-and-envs/matlab.md",
    "read_singularity_doc": "software/apps-and-envs/singularity.md",
    "read_compilers_doc": "software/compilers.md",
    "read_software_faq_doc": "software/faq.md",
    "read_alphafold_doc": "software/apps-and-envs/alphafold.md",
    "read_gromacs_doc": "software/apps-and-envs/gromacs.md",
    "read_lammps_doc": "software/apps-and-envs/lammps.md",
    "read_gaussian_doc": "software/apps-and-envs/gaussian.md",
    "read_midwayr3_overview_doc": "midwayR3/overview.md",
    "read_skyway_doc": "skyway-overview.md",
    "read_gis_doc": "gis/index.md",
    "read_databases_doc": "databases/main.md",
}

WEB_DOC_PATHS = {
    "read_web_about_rcc": "about-rcc.txt",
    "read_web_advisory_committees": "about-rcc_advisory-committees.txt",
    "read_web_ai_spotlight": "about-rcc_artificial-intelligence-spotlight-mind-bytes-2018.txt",
    "read_web_director_welcome": "about-rcc_director's-welcome.txt",
    "read_web_rcc_team": "about-rcc_our-team.txt",
    "read_web_user_policy": "about-rcc_rcc-user-policy.txt",
    "read_web_oversight_committee": "about-rcc_research-computing-oversight-committee.txt",
    "read_web_vision_mission": "about-rcc_vision-mission.txt",
    "read_web_access": "access.txt",
    "read_web_accounts_allocations": "accounts-allocations.txt",
    "read_web_grants_publications": "grants-publications.txt",
    "read_web_acknowledging_rcc": "grants-publications_acknowledging-the-RCC.txt",
    "read_web_facilities_resources": "grants-publications_facilities-and-resources-documents.txt",
    "read_web_pi_proposals": "grants-publications_for-PI-proposals.txt",
    "read_web_grant_support": "grants-publications_grant-support.txt",
    "read_web_hardware_quotes": "grants-publications_hardware-quotes.txt",
    "read_web_publications_list": "grants-publications_list-of-publications.txt",
    "read_web_publications": "grants-publications_publications.txt",
    "read_web_support_letters": "grants-publications_support-letters.txt",
    "read_web_resources": "resources.txt",
    "read_web_hpc_resources": "resources_high-performance-computing.txt",
    "read_web_hosted_data": "resources_hosted-data.txt",
    "read_web_networking": "resources_networking.txt",
    "read_web_software_resources": "resources_software.txt",
    "read_web_storage_backup": "resources_storage-and-backup.txt",
    "read_web_support_services": "support-and-services.txt",
    "read_web_cpp": "support-and-services_cluster-partnership-program.txt",
    "read_web_consultant_partnership": "support-and-services_consultant-partnership-program.txt",
    "read_web_consulting_support": "support-and-services_consulting-and-technical-support.txt",
    "read_web_data_management": "support-and-services_data-management.txt",
    "read_web_data_sharing": "support-and-services_data-sharing-services.txt",
    "read_web_midway2_services": "support-and-services_midway2.txt",
    "read_web_new_faculty": "support-and-services_new-faculty-program.txt",
    "read_web_outreach": "support-and-services_outreach.txt",
    "read_web_workshops_training": "support-and-services_workshops-and-training.txt",
    "read_web_faqs": "faqs.txt",
    "read_web_index": "index.txt",
    "read_web_midway2": "midway2.txt",
    "read_web_news_events": "news-and-events.txt",
    "read_web_software": "software.txt",
    "read_web_system_details": "system-details.txt",
    "read_web_workshops": "workshops.txt",
    "read_web_workshops_events": "workshops-events.txt",
    "read_web_data_viz_committee": "data-visualization-initiative-advisory-committee.txt",
    "read_web_team": "team.txt",
    "read_web_bayesian_forest": "bayesian-forest-cities-full-data.txt",
    "read_web_big_data_worms": "big-data-sleeping-worms-and-electronic-chef.txt",
    "read_web_our_work": "our-work-color.txt",
    "read_web_tools_resources": "tools-resources-color.txt",
    "read_web_incidence": "incidence.txt",
    "read_web_mpmri": "mpMRI.txt",
    "read_web_pirads": "pirads.txt",
    "read_web_publications_page": "publications.txt",
    "read_web_takecourse": "takecourse.txt",
    "read_web_user_guide_page": "user-guide.txt",
}


# --- Tool Definitions ---
TOOLS = [
    {"name": "read_accounts_doc", "description": "Read documentation about RCC accounts. COVERS: Account types, applying for accounts, CNetID, sponsors, external collaborators.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_connecting_doc", "description": "Read documentation about connecting to RCC clusters. COVERS: SSH, ThinLinc, Open OnDemand, SAMBA, Globus protocols.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_jobs_tutorial_doc", "description": "Read beginner tutorial for running jobs. COVERS: sinteractive, sbatch basics, squeue.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_allocations_doc", "description": "Read documentation about allocations and service units. COVERS: SUs, checking balance, usage tracking.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_software_tutorial_doc", "description": "Read beginner tutorial for software setup. COVERS: module commands, Python environments, pip.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_data_tutorial_doc", "description": "Read beginner tutorial for data management. COVERS: /project, /scratch, data download.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_policies_doc", "description": "Read RCC policies and terms of use. COVERS: Usage policies, data security, restricted data.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_glossary_doc", "description": "Read HPC glossary. COVERS: Definitions of HPC terms.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_mistakes_doc", "description": "Read common mistakes to avoid. COVERS: Quota issues, conda mistakes, login node misuse.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_helpdesk_doc", "description": "Read how to get help from RCC. COVERS: Contact info, what to include in requests.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_ecosystems_doc", "description": "Read overview of RCC clusters. COVERS: Midway2, Midway3, Beagle3, DaLI, etc.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_clusters_doc", "description": "Read hardware specs for clusters. COVERS: Node configs, cores, memory, GPUs.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_partitions_doc", "description": "Read about Slurm partitions. COVERS: Partition configs, QoS limits.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_beagle3_doc", "description": "Read about Beagle3 cluster. COVERS: Biomedical research, A100/A40 GPUs.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_slurm_main_doc", "description": "Read main Slurm documentation. COVERS: Job scheduling, interactive vs batch.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_sinteractive_doc", "description": "Read about interactive jobs. COVERS: sinteractive options, debug QoS.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_sbatch_doc", "description": "Read about batch job submission. COVERS: sbatch scripts, job arrays, MPI, GPU jobs.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_slurm_faq_doc", "description": "Read Slurm FAQ. COVERS: Common job issues and solutions.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_storage_main_doc", "description": "Read storage documentation. COVERS: home, project, scratch, quotas, snapshots.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_storage_faq_doc", "description": "Read storage FAQ. COVERS: Quota issues, file recovery, sharing.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_ssh_main_doc", "description": "Read SSH documentation. COVERS: SSH commands, SCP, rsync, Duo 2FA.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_ssh_advanced_doc", "description": "Read advanced SSH options. COVERS: X11, SSH keys, port forwarding.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_ssh_faq_doc", "description": "Read SSH FAQ. COVERS: Connection troubleshooting.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_thinlinc_doc", "description": "Read ThinLinc documentation. COVERS: Remote desktop, GUI access.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_ondemand_doc", "description": "Read Open OnDemand documentation. COVERS: Web portal, Jupyter, RStudio.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_globus_transfer_doc", "description": "Read Globus file transfer docs. COVERS: Large file transfers, endpoints.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_globus_share_doc", "description": "Read Globus sharing docs. COVERS: Sharing with collaborators.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_samba_doc", "description": "Read SAMBA documentation. COVERS: Mounting RCC directories locally.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_software_index_doc", "description": "Read software/modules documentation. COVERS: module commands, available software.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_python_doc", "description": "Read Python documentation. COVERS: Python, conda, pip, environments.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_tensorflow_pytorch_doc", "description": "Read TensorFlow/PyTorch docs. COVERS: GPU computing, CUDA setup.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_r_doc", "description": "Read R documentation. COVERS: R, RStudio, packages.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_matlab_doc", "description": "Read MATLAB documentation. COVERS: MATLAB on Midway.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_singularity_doc", "description": "Read Singularity documentation. COVERS: Containers, Docker images.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_compilers_doc", "description": "Read compiler documentation. COVERS: GCC, Intel, compilation.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_software_faq_doc", "description": "Read software FAQ. COVERS: Software issues, conflicts.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_alphafold_doc", "description": "Read AlphaFold documentation. COVERS: Protein structure prediction.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_gromacs_doc", "description": "Read GROMACS documentation. COVERS: Molecular dynamics.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_lammps_doc", "description": "Read LAMMPS documentation. COVERS: Molecular dynamics.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_gaussian_doc", "description": "Read Gaussian documentation. COVERS: Quantum chemistry.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_midwayr3_overview_doc", "description": "Read MidwayR3 documentation. COVERS: Secure computing, HIPAA.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_skyway_doc", "description": "Read Skyway documentation. COVERS: Cloud bursting, AWS/GCP.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_gis_doc", "description": "Read GIS documentation. COVERS: Geospatial analysis.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_databases_doc", "description": "Read database documentation. COVERS: Available databases.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_about_rcc", "description": "Read about RCC from website. COVERS: History, mission, services.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_rcc_team", "description": "Read about RCC staff. COVERS: Team members, expertise.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_vision_mission", "description": "Read RCC vision/mission. COVERS: Strategic goals.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_access", "description": "Read about RCC access. COVERS: Eligibility, requirements.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_accounts_allocations", "description": "Read about accounts/allocations. COVERS: Account types, allocation process.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_acknowledging_rcc", "description": "Read how to acknowledge RCC. COVERS: Citation text for publications.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_grant_support", "description": "Read about grant support. COVERS: How RCC helps with grants.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_hpc_resources", "description": "Read about HPC resources. COVERS: Hardware, capabilities.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_storage_backup", "description": "Read about storage/backup. COVERS: Storage systems, recovery.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_support_services", "description": "Read about support services. COVERS: Walk-in lab, consulting.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_cpp", "description": "Read about Cluster Partnership Program. COVERS: Dedicated hardware purchase.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_workshops_training", "description": "Read about workshops. COVERS: Training schedule, topics.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_web_faqs", "description": "Read website FAQs. COVERS: Common questions.", "input_schema": {"type": "object", "properties": {}, "required": []}},
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
    """Execute a documentation tool and return the result."""
    if tool_name in DOC_PATHS:
        doc_path = DOC_PATHS[tool_name]
        content = read_document(doc_path)
        return f"=== DOCUMENT: {doc_path} ===\n\n{content}"
    elif tool_name in WEB_DOC_PATHS:
        doc_path = WEB_DOC_PATHS[tool_name]
        content = read_web_document(doc_path)
        return f"=== WEB CONTENT: {doc_path} ===\n\n{content}"
    return f"Unknown tool: {tool_name}"


SYSTEM_PROMPT = """You are the RCC User Guide Assistant for the University of Chicago's Research Computing Center.

You have DOCUMENTATION TOOLS available that retrieve official RCC documentation:
- read_*_doc tools that retrieve markdown documentation files
- read_web_* tools that retrieve content from the RCC website

You can also analyze files that users upload:
- PDF documents: You will receive the extracted text content
- Text files (.txt, .md, .py, .json, .csv): You will receive the file contents

GUIDELINES:
- Use documentation tools to answer questions about RCC systems and procedures
- When users upload files, analyze them and provide helpful information
- Be helpful, accurate, and cite specific commands when possible
- NEVER include raw markdown syntax like {:target="_blank"} in responses

TOPICS: Accounts, SSH, Slurm jobs, storage, Python, R, MATLAB, GPUs, containers, and more."""


# --- Streamlit App ---
st.set_page_config(page_title="Sage", page_icon="🤖", layout="wide", initial_sidebar_state="collapsed")

# CSS with variables for theming and responsive design
st.markdown("""
<style>
    /* ===== CSS VARIABLES ===== */
    :root {
        /* Primary gradient */
        --gradient-start: #667eea;
        --gradient-end: #764ba2;
        --gradient: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));

        /* Colors */
        --text-primary: #e5e7eb;
        --text-secondary: #9ca3af;
        --text-dark: #374151;
        --border-default: #e5e7eb;
        --border-focus: #667eea;

        /* Shadows */
        --shadow-sm: 0 2px 8px rgba(102, 126, 234, 0.3);
        --shadow-md: 0 4px 15px rgba(0, 0, 0, 0.1);
        --shadow-lg: 0 8px 25px rgba(102, 126, 234, 0.2);

        /* Spacing */
        --space-xs: 0.25rem;
        --space-sm: 0.5rem;
        --space-md: 1rem;
        --space-lg: 1.5rem;
        --space-xl: 2rem;

        /* Sizing */
        --content-max: min(900px, 95vw);
        --input-max: min(800px, 95vw);
        --bubble-max: 70%;
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

    [data-testid="stMainBlockContainer"] { padding-top: 0.5rem !important; }

    html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        overflow-x: hidden !important;
    }

    /* ===== TRASH BUTTON ===== */
    .trash-btn-wrapper {
        position: fixed;
        top: 10px;
        right: 20px;
        z-index: 1000;
    }

    .trash-btn-wrapper .stButton > button {
        background: rgba(31, 41, 55, 0.8) !important;
        border: 1px solid #374151 !important;
        border-radius: var(--radius-sm) !important;
        padding: 6px 10px !important;
        min-height: 36px !important;
        min-width: 36px !important;
        backdrop-filter: blur(8px);
        transition: var(--transition) !important;
    }

    .trash-btn-wrapper .stButton > button:hover {
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
        padding: var(--space-lg) var(--space-md);
        margin-top: 8vh;
        animation: fadeInDown 0.6s ease-out;
    }

    @keyframes fadeInDown {
        from { opacity: 0; transform: translateY(-20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .welcome-icon {
        font-size: clamp(2rem, 5vw, 3rem);
        margin-bottom: var(--space-sm);
        animation: bounceIn 0.8s ease-out 0.2s both;
    }

    @keyframes bounceIn {
        0% { opacity: 0; transform: scale(0.3); }
        50% { transform: scale(1.1); }
        70% { transform: scale(0.9); }
        100% { opacity: 1; transform: scale(1); }
    }

    .welcome-title {
        font-size: clamp(1.5rem, 4vw, 2.2rem);
        font-weight: 600;
        background: var(--gradient);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: var(--space-xl);
        animation: fadeInUp 0.6s ease-out 0.3s both;
    }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* ===== EXAMPLES GRID ===== */
    .examples-grid-wrapper {
        max-width: min(680px, 90vw);
        margin: 0 auto;
        padding: 0 var(--space-md);
    }

    .examples-grid-wrapper [data-testid="stHorizontalBlock"] {
        gap: 0.75rem !important;
        margin-bottom: 0.6rem !important;
    }

    .examples-grid-wrapper .stButton button {
        background: linear-gradient(145deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.03) 100%);
        border: 1px solid rgba(255,255,255,0.12) !important;
        border-radius: var(--radius-md) !important;
        padding: 12px 16px !important;
        text-align: center !important;
        font-size: clamp(0.75rem, 2vw, 0.88rem) !important;
        color: var(--text-primary) !important;
        height: auto !important;
        min-height: auto !important;
        transition: var(--transition) !important;
        backdrop-filter: blur(10px);
        box-shadow: var(--shadow-md) !important;
        opacity: 0;
        transform: translateY(25px);
        animation: exampleFadeIn 0.5s ease-out forwards;
    }

    .examples-grid-wrapper .stButton button:nth-child(1) { animation-delay: 0.3s; }
    .examples-grid-wrapper .stButton button:nth-child(2) { animation-delay: 0.45s; }

    @keyframes exampleFadeIn {
        to { opacity: 1; transform: translateY(0); }
    }

    .examples-grid-wrapper .stButton button:hover {
        background: linear-gradient(145deg, rgba(102, 126, 234, 0.25) 0%, rgba(118, 75, 162, 0.25) 100%);
        border-color: rgba(102, 126, 234, 0.5) !important;
        transform: translateY(-3px) !important;
        box-shadow: var(--shadow-lg) !important;
    }

    .examples-grid-wrapper .stButton button:active {
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
        box-shadow: 0 4px 20px rgba(102, 126, 234, 0.25) !important;
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
        margin: clamp(1rem, 3vw, 2rem) 0 clamp(0.5rem, 2vw, 1rem) 0;
        padding-right: clamp(0.25rem, 2vw, 1rem);
    }

    .user-bubble, .user-bubble-with-attachment {
        background: var(--gradient);
        color: white;
        padding: 12px 18px;
        border-radius: 18px 18px 4px 18px;
        font-size: clamp(0.85rem, 2vw, 0.95rem);
        line-height: 1.5;
        max-width: var(--bubble-max);
        box-shadow: var(--shadow-sm);
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
        margin: clamp(0.5rem, 2vw, 1rem) 0 clamp(1rem, 3vw, 2rem) 0;
    }

    .stChatMessage {
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
    }

    .stChatMessage [data-testid="chatAvatarIcon-assistant"] {
        background: var(--gradient) !important;
    }

    /* ===== TOOL BADGE ===== */
    .tool-badge {
        display: inline-block;
        background: #f0f9ff;
        color: #0369a1;
        padding: 3px 8px;
        border-radius: 10px;
        font-size: 0.7rem;
        margin-bottom: 6px;
        border: 1px solid #bae6fd;
    }

    /* ===== CHAT CONTAINER ===== */
    .chat-container {
        padding-bottom: clamp(80px, 15vh, 140px);
        margin-top: 0;
        padding-top: 0.5rem;
    }

    .chat-container > div:first-child {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }

    /* ===== STATUS & STREAMING ===== */
    .search-status {
        padding: 0.5rem 1rem;
        margin: 0.5rem 0;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .search-text {
        background: var(--gradient);
        background-size: 200% 100%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: shimmer 1.5s ease-in-out infinite;
        font-weight: 500;
        font-size: clamp(0.8rem, 2vw, 0.9rem);
    }

    @keyframes shimmer {
        0% { background-position: 100% 0; }
        50% { background-position: 0% 0; }
        100% { background-position: 100% 0; }
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
        .examples-grid-wrapper [data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
            gap: 0.5rem !important;
        }

        .examples-grid-wrapper .stButton button {
            width: 100% !important;
        }

        .user-message {
            padding-right: 0 !important;
        }

        .user-bubble, .user-bubble-with-attachment {
            max-width: 85%;
        }

        .trash-btn-wrapper {
            top: 5px;
            right: 10px;
        }
    }

    /* ===== RESPONSIVE: TABLET ===== */
    @media (min-width: 641px) and (max-width: 1024px) {
        .examples-grid-wrapper {
            max-width: min(600px, 92vw);
        }
    }

    /* ===== LIGHT MODE ===== */
    @media (prefers-color-scheme: light) {
        :root {
            --text-primary: #374151;
            --text-secondary: #6b7280;
            --text-dark: #1f2937;
            --border-default: #d1d5db;
        }

        .examples-grid-wrapper .stButton button {
            background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #e2e8f0 !important;
            color: var(--text-dark) !important;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.06) !important;
        }

        .examples-grid-wrapper .stButton button:hover {
            background: linear-gradient(145deg, #eef2ff 0%, #e0e7ff 100%);
            border-color: #a5b4fc !important;
        }

        .tool-badge {
            background: #f0f9ff;
            color: #0369a1;
            border-color: #bae6fd;
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
    }

    /* ===== DARK MODE TOOL BADGE ===== */
    @media (prefers-color-scheme: dark) {
        .tool-badge {
            background: #1e3a5f;
            color: #7dd3fc;
            border-color: #0369a1;
        }
    }
</style>
""", unsafe_allow_html=True)

# JavaScript for paperclip button, scroll control, and animations
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
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';
        btn.title = 'Attach file (PDF, TXT, MD, PY, JSON, CSV)';
        btn.style.cssText = 'position:absolute;left:12px;top:50%;transform:translateY(-50%);z-index:1000;background:transparent;border:none;cursor:pointer;padding:8px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#9ca3af;transition:all 0.2s;';

        btn.onmouseenter = function() { this.style.background='rgba(102,126,234,0.1)'; this.style.color='#667eea'; };
        btn.onmouseleave = function() { this.style.background='transparent'; this.style.color='#9ca3af'; };

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

    function init() {
        updateScrollBehavior();
        addPaperclipButton();
        styleAttachmentChip();
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

    // Auto-scroll in chat mode
    function autoScroll() {
        const chatContainer = doc.querySelector('.chat-container');
        if (chatContainer) {
            window.parent.scrollTo({ top: doc.body.scrollHeight, behavior: 'smooth' });
        }
    }

    // Auto-focus on typing
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
if "minimax_client" not in st.session_state:
    st.session_state.minimax_client = get_minimax_client()
if "mistral_client" not in st.session_state:
    st.session_state.mistral_client = get_mistral_client()
if "uploaded_file_data" not in st.session_state:
    st.session_state.uploaded_file_data = None
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "using_backup" not in st.session_state:
    st.session_state.using_backup = False

# Debug indicator (shows API status at startup)
print(f"[STARTUP] MiniMax client initialized: {st.session_state.minimax_client is not None}")
print(f"[STARTUP] Mistral client initialized: {st.session_state.mistral_client is not None}")
print(f"[STARTUP] ANTHROPIC_API_KEY set: {bool(MINIMAX_API_KEY)}")
print(f"[STARTUP] MISTRAL_API_KEY set: {bool(MISTRAL_API_KEY)}")

def collect_stream_response(stream):
    """Collect full response from streaming API."""
    full_text = ""
    tool_use_blocks = []
    current_tool = None
    current_tool_input = ""

    try:
        with stream as s:
            for event in s:
                if event.type == "content_block_start":
                    if hasattr(event.content_block, 'type') and event.content_block.type == "tool_use":
                        current_tool = {"id": event.content_block.id, "name": event.content_block.name, "input": {}}
                        current_tool_input = ""
                elif event.type == "content_block_delta":
                    if hasattr(event.delta, 'type'):
                        if event.delta.type == "text_delta":
                            full_text += event.delta.text
                        elif event.delta.type == "input_json_delta" and current_tool:
                            current_tool_input += event.delta.partial_json
                elif event.type == "content_block_stop":
                    if current_tool:
                        try:
                            current_tool["input"] = json.loads(current_tool_input) if current_tool_input else {}
                        except json.JSONDecodeError:
                            current_tool["input"] = {}
                        tool_use_blocks.append(current_tool)
                        current_tool = None
                elif event.type == "message_stop":
                    break
            final_message = s.get_final_message()
    except Exception as e:
        # Re-raise with more context - this helps identify MiniMax API errors
        error_str = str(e)
        # Check for MiniMax-specific error codes
        if any(code in error_str for code in ['1002', '2045', '2056', '1001', '1024', '1033', '1039', '429']):
            print(f"MiniMax API error detected: {error_str}")
        raise  # Re-raise to trigger fallback
    
    return full_text, tool_use_blocks, final_message



def stream_response_generator(stream):
    """
    Generator that yields text chunks from the streaming API for use with st.write_stream().
    Also collects tool use blocks and returns them via a mutable container.
    
    Returns: generator that yields text chunks
    """
    tool_use_blocks = []
    current_tool = None
    current_tool_input = ""
    final_message_container = [None]  # Mutable container to store final message
    
    def generator():
        nonlocal current_tool, current_tool_input
        try:
            with stream as s:
                for event in s:
                    if event.type == "content_block_start":
                        if hasattr(event.content_block, 'type') and event.content_block.type == "tool_use":
                            current_tool = {"id": event.content_block.id, "name": event.content_block.name, "input": {}}
                            current_tool_input = ""
                    elif event.type == "content_block_delta":
                        if hasattr(event.delta, 'type'):
                            if event.delta.type == "text_delta":
                                # Yield text chunks for streaming display
                                yield event.delta.text
                            elif event.delta.type == "input_json_delta" and current_tool:
                                current_tool_input += event.delta.partial_json
                    elif event.type == "content_block_stop":
                        if current_tool:
                            try:
                                current_tool["input"] = json.loads(current_tool_input) if current_tool_input else {}
                            except json.JSONDecodeError:
                                current_tool["input"] = {}
                            tool_use_blocks.append(current_tool)
                            current_tool = None
                    elif event.type == "message_stop":
                        break
                final_message_container[0] = s.get_final_message()
        except Exception as e:
            # Re-raise with more context
            error_str = str(e)
            if any(code in error_str for code in ['1002', '2045', '2056', '1001', '1024', '1033', '1039', '429']):
                print(f"MiniMax API error in streaming: {error_str}")
            raise
    
    return generator(), tool_use_blocks, final_message_container



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
        print(f"Error in mistral_collect_response: {e}")
        print(traceback.format_exc())
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
    
    print(f"[DEBUG] Mistral response collected: text_len={len(content_buffer)}, tool_calls={len(tool_use_blocks)}")
    
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
            print(f"Error in mistral_stream_generator: {e}")
            print(traceback.format_exc())
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


def call_minimax_api(client, messages, tools, system_prompt, collect_only=False):
    """Call MiniMax API with tool support. Returns (text, tool_blocks, response) or generator tuple."""
    try:
        stream = client.messages.stream(
            model=MINIMAX_MODEL,
            max_tokens=8192,
            system=system_prompt,
            messages=messages,
            tools=tools
        )
    except Exception as e:
        error_str = str(e)
        print(f"MiniMax API call failed at stream creation: {error_str}")
        print(traceback.format_exc())
        raise  # Re-raise to trigger fallback
    
    if collect_only:
        return collect_stream_response(stream)
    else:
        return stream_response_generator(stream)



def call_mistral_api(client, messages, tools, system_prompt, collect_only=False):

    """Call Mistral API with tool support. Returns (text, tool_blocks, response) or generator tuple."""
    # Convert messages for Mistral format
    mistral_messages = [{"role": "system", "content": system_prompt}]
    
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        
        if role == "user":
            # Handle both string content and list content
            if isinstance(content, str):
                mistral_messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Check if it's tool results
                if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                    # Convert tool results to Mistral format
                    for tool_result in content:
                        mistral_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_result.get("tool_use_id", "unknown"),
                            "name": tool_result.get("name", "unknown"),
                            "content": str(tool_result.get("content", ""))
                        })
                else:
                    # Regular content list - extract text
                    text_content = ""
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_content += block.get("text", "")
                        elif isinstance(block, dict) and "text" in block:
                            text_content += block.get("text", "")
                    if text_content:
                        mistral_messages.append({"role": "user", "content": text_content})
        
        elif role == "assistant":
            if isinstance(content, str):
                if content:  # Only add non-empty content
                    mistral_messages.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                # Extract text from content blocks and handle tool calls
                text_content = ""
                tool_calls_to_add = []
                
                for block in content:
                    # Handle SimpleNamespace objects (from Anthropic response)
                    if hasattr(block, 'type'):
                        if block.type == "text" and hasattr(block, 'text'):
                            text_content += block.text
                        elif block.type == "tool_use":
                            # This is a tool call - need to track for Mistral format
                            tool_calls_to_add.append({
                                "id": getattr(block, 'id', 'unknown'),
                                "type": "function",
                                "function": {
                                    "name": getattr(block, 'name', 'unknown'),
                                    "arguments": json.dumps(getattr(block, 'input', {}))
                                }
                            })
                    # Handle dict objects
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            text_content += block.get("text", "")
                        elif block.get("type") == "tool_use":
                            tool_calls_to_add.append({
                                "id": block.get("id", "unknown"),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", "unknown"),
                                    "arguments": json.dumps(block.get("input", {}))
                                }
                            })
                
                # Build assistant message
                if tool_calls_to_add:
                    assistant_msg = {
                        "role": "assistant",
                        "content": text_content if text_content else "",
                        "tool_calls": tool_calls_to_add
                    }
                    mistral_messages.append(assistant_msg)
                elif text_content:
                    mistral_messages.append({"role": "assistant", "content": text_content})
    
    # Debug: Log Mistral messages being sent
    print(f"[DEBUG] Mistral API call - Number of messages: {len(mistral_messages)}")
    print(f"[DEBUG] Mistral API call - Tools: {len(tools) if tools else 0}")
    # Log message roles for debugging
    for i, m in enumerate(mistral_messages):
        role = m.get('role', 'unknown')
        has_tool_calls = 'tool_calls' in m
        content_preview = str(m.get('content', ''))[:50] if m.get('content') else '(empty)'
        print(f"[DEBUG]   Message {i}: role={role}, has_tool_calls={has_tool_calls}, content={content_preview}...")
    
    # Make the API call
    try:
        stream = client.chat.stream(
            model=MISTRAL_MODEL,
            messages=mistral_messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None
        )
    except Exception as e:
        print(f"[DEBUG] Mistral API call failed at stream creation: {str(e)}")
        print(traceback.format_exc())
        raise
    
    if collect_only:
        return mistral_collect_response(stream)
    else:
        return mistral_stream_generator(stream)


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


def format_tool_names(tool_names):
    """Format tool names."""
    if not tool_names:
        return ""
    tool_counts = {}
    for name in tool_names:
        display_name = name.replace('read_', '').replace('_doc', '').replace('_', ' ').title()
        tool_counts[display_name] = tool_counts.get(display_name, 0) + 1
    return ", ".join(f"{n} (×{c})" if c > 1 else n for n, c in tool_counts.items())


RCC_DOCS_BASE_URL = "https://rcc-uchicago.github.io/user-guide/"

def fix_markdown_links(text):
    """Convert broken internal links to real RCC documentation URLs."""
    import re
    
    def replace_link(match):
        link_text = match.group(1)
        link_target = match.group(2)
        
        if link_target.startswith(('http://', 'https://')):
            return match.group(0)
        
        if link_target in DOC_PATHS:
            doc_path = DOC_PATHS[link_target].replace('.md', '')
            return f'[{link_text}]({RCC_DOCS_BASE_URL}{doc_path}/)'
        
        for tool_name, doc_path in DOC_PATHS.items():
            if link_target == doc_path or link_target == doc_path.replace('.md', ''):
                clean_path = doc_path.replace('.md', '')
                return f'[{link_text}]({RCC_DOCS_BASE_URL}{clean_path}/)'
        
        if link_target.endswith('.md'):
            clean_path = link_target.replace('.md', '')
            return f'[{link_text}]({RCC_DOCS_BASE_URL}{clean_path}/)'
        
        return link_text
    
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, text)
    return text


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


def render_assistant_message(content, tool_names=None):
    """Render assistant message."""
    content = fix_markdown_links(content)
    st.markdown('<div class="assistant-wrapper">', unsafe_allow_html=True)
    with st.chat_message("assistant"):
        if tool_names:
            st.markdown(f'<span class="tool-badge">📚 {format_tool_names(tool_names)}</span>', unsafe_allow_html=True)
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
        <div class="welcome-icon">📚 ✨ 🎯</div>
        <h1 class="welcome-title">What can I help you with?</h1>
    </div>
    ''', unsafe_allow_html=True)
    
    # Example questions grid using Streamlit columns with custom styling
    st.markdown('<div class="examples-grid-wrapper">', unsafe_allow_html=True)
    
    # Row 1
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        if st.button(f"{EXAMPLE_QUESTIONS[0][0]} {EXAMPLE_QUESTIONS[0][1]}", key="ex_0", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": EXAMPLE_QUESTIONS[0][1]})
            st.session_state.processing = True
            st.rerun()
    with col2:
        if st.button(f"{EXAMPLE_QUESTIONS[1][0]} {EXAMPLE_QUESTIONS[1][1]}", key="ex_1", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": EXAMPLE_QUESTIONS[1][1]})
            st.session_state.processing = True
            st.rerun()
    
    # Row 2
    col3, col4 = st.columns(2, gap="medium")
    with col3:
        if st.button(f"{EXAMPLE_QUESTIONS[2][0]} {EXAMPLE_QUESTIONS[2][1]}", key="ex_2", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": EXAMPLE_QUESTIONS[2][1]})
            st.session_state.processing = True
            st.rerun()
    with col4:
        if st.button(f"{EXAMPLE_QUESTIONS[3][0]} {EXAMPLE_QUESTIONS[3][1]}", key="ex_3", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": EXAMPLE_QUESTIONS[3][1]})
            st.session_state.processing = True
            st.rerun()
    
    # Row 3
    col5, col6 = st.columns(2, gap="medium")
    with col5:
        if st.button(f"{EXAMPLE_QUESTIONS[4][0]} {EXAMPLE_QUESTIONS[4][1]}", key="ex_4", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": EXAMPLE_QUESTIONS[4][1]})
            st.session_state.processing = True
            st.rerun()
    with col6:
        if st.button(f"{EXAMPLE_QUESTIONS[5][0]} {EXAMPLE_QUESTIONS[5][1]}", key="ex_5", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": EXAMPLE_QUESTIONS[5][1]})
            st.session_state.processing = True
            st.rerun()
    
    st.markdown('</div>', unsafe_allow_html=True)

else:
    # Chat mode - trash button fixed at top right
    st.markdown('<div class="trash-btn-wrapper">', unsafe_allow_html=True)
    if st.button("🗑️", key="clear", help="Clear chat"):
        st.session_state.messages = []
        st.session_state.processing = False
        st.session_state.uploaded_file_data = None
        st.session_state.uploader_key += 1  # Reset the file uploader
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    
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
                render_assistant_message(text, msg.get("tool_names"))
    
    # Display any stored error message with custom styling
    if "last_error" in st.session_state:
        st.markdown(f'''
        <div class="error-container">
            <div class="error-icon">⚠️</div>
            <div class="error-message">Error: {st.session_state.last_error}</div>
        </div>
        ''', unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("🔄 Try Again", key="dismiss_error", use_container_width=True):
                # Remove the last user message that caused the error
                if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
                    st.session_state.messages.pop()
                del st.session_state.last_error
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

# Show attachment status as a compact chip above the chat input
if st.session_state.uploaded_file_data and st.session_state.uploaded_file_data.get("type") != "error":
    file_data = st.session_state.uploaded_file_data
    icon = get_file_icon(file_data.get("filename", "file"))
    filename = file_data.get("filename", "file")
    
    if st.button(f"{icon} {filename}  ✕", key="remove_attachment", type="secondary"):
        st.session_state.uploaded_file_data = None
        st.session_state.uploader_key += 1
        st.rerun()

# Chat input
prompt = st.chat_input("Ask any question about RCC...", disabled=st.session_state.processing)

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
    # Display user message first
    last_user_msg = st.session_state.messages[-1]
    display_text = last_user_msg.get("display_text", last_user_msg["content"] if isinstance(last_user_msg["content"], str) else "")
    file_info = last_user_msg.get("file_info")
    render_user_message(display_text, file_info)
    
    # Show initial status message with streaming indicator
    status_placeholder = st.empty()
    status_messages = ["🧠 Contemplating...", "✨ Vibing...", "⏳ Brewing...", "🎨 Crafting...", "🔧 Tinkering..."]
    status_placeholder.markdown(
        f'<div class="search-status"><span class="search-text">{random.choice(status_messages)}</span><div class="streaming-dots"><span></span><span></span><span></span></div></div>',
        unsafe_allow_html=True
    )
    
    api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    all_tool_names = []
    using_backup = False
    minimax_error_msg = None
    
    # Debug: Log which clients are available
    print(f"[DEBUG] MiniMax client available: {st.session_state.minimax_client is not None}")
    print(f"[DEBUG] Mistral client available: {st.session_state.mistral_client is not None}")
    
    try:
        # Try MiniMax API first (primary) if client is available
        minimax_succeeded = False
        
        if st.session_state.minimax_client:
            try:
                print("[DEBUG] Attempting MiniMax API call...")
                # First API call - collect to check for tool calls
                response_text, tool_use_blocks, response = call_minimax_api(
                    st.session_state.minimax_client, api_messages, TOOLS, SYSTEM_PROMPT, collect_only=True
                )
                print(f"[DEBUG] MiniMax API call succeeded. Response length: {len(response_text)}, Tool calls: {len(tool_use_blocks)}")
                all_tool_names.extend([tb["name"] for tb in tool_use_blocks])
                
                # Handle tool calls in a loop
                while tool_use_blocks:
                    api_messages.append({"role": "assistant", "content": response.content})
                    tool_results = [{"type": "tool_result", "tool_use_id": tb["id"], "content": execute_tool(tb["name"], tb["input"])} for tb in tool_use_blocks]
                    api_messages.append({"role": "user", "content": tool_results})
                    
                    response_text, tool_use_blocks, response = call_minimax_api(
                        st.session_state.minimax_client, api_messages, TOOLS, SYSTEM_PROMPT, collect_only=True
                    )
                    all_tool_names.extend([tb["name"] for tb in tool_use_blocks])
                
                minimax_succeeded = True
                print("[DEBUG] MiniMax processing complete, minimax_succeeded=True")
                
            except Exception as e:
                # MiniMax failed - store error and try backup
                minimax_error_msg = str(e)
                print(f"[DEBUG] MiniMax API failed: {minimax_error_msg}")
                print(traceback.format_exc())
                minimax_succeeded = False
        else:
            print("[DEBUG] MiniMax client not available, skipping to backup")
        
        # If MiniMax failed or not available, try Mistral backup
        if not minimax_succeeded:
            print(f"[DEBUG] minimax_succeeded={minimax_succeeded}, checking for Mistral backup...")
            if st.session_state.mistral_client:
                print(f"[DEBUG] Switching to Mistral backup API...")
                # Don't show "switching" message to user - keep the original status message
                using_backup = True
                
                # For Mistral, build messages in Mistral-native format from scratch
                # Only take the actual user messages (strings), not the complex Anthropic format
                mistral_conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
                for m in st.session_state.messages:
                    if m["role"] == "user":
                        content = m["content"]
                        if isinstance(content, str):
                            mistral_conversation.append({"role": "user", "content": content})
                        elif isinstance(content, list):
                            # Extract text from content list
                            text_parts = []
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                            if text_parts:
                                mistral_conversation.append({"role": "user", "content": " ".join(text_parts)})
                
                all_tool_names = []
                
                try:
                    print("[DEBUG] Attempting Mistral API call...")
                    print(f"[DEBUG] Mistral conversation has {len(mistral_conversation)} messages")
                    
                    # First API call - collect to check for tool calls
                    stream = st.session_state.mistral_client.chat.stream(
                        model=MISTRAL_MODEL,
                        messages=mistral_conversation,
                        tools=MISTRAL_TOOLS,
                        tool_choice="auto"
                    )
                    response_text, tool_use_blocks, response = mistral_collect_response(stream)
                    print(f"[DEBUG] Mistral API call succeeded. Response length: {len(response_text)}, Tool calls: {len(tool_use_blocks)}")
                    all_tool_names.extend([tb["name"] for tb in tool_use_blocks])
                    
                    # Handle tool calls in a loop (using Mistral-native format)
                    while tool_use_blocks:
                        # Add assistant message with tool_calls in Mistral format
                        assistant_msg = {
                            "role": "assistant",
                            "content": response_text if response_text else "",
                            "tool_calls": [
                                {
                                    "id": tb["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tb["name"],
                                        "arguments": json.dumps(tb["input"])
                                    }
                                }
                                for tb in tool_use_blocks
                            ]
                        }
                        mistral_conversation.append(assistant_msg)
                        
                        # Add tool results in Mistral format
                        for tb in tool_use_blocks:
                            tool_result = execute_tool(tb["name"], tb["input"])
                            mistral_conversation.append({
                                "role": "tool",
                                "tool_call_id": tb["id"],
                                "name": tb["name"],
                                "content": tool_result
                            })
                        
                        # Get next response
                        stream = st.session_state.mistral_client.chat.stream(
                            model=MISTRAL_MODEL,
                            messages=mistral_conversation,
                            tools=MISTRAL_TOOLS,
                            tool_choice="auto"
                        )
                        response_text, tool_use_blocks, response = mistral_collect_response(stream)
                        all_tool_names.extend([tb["name"] for tb in tool_use_blocks])
                    
                    # Store the api_messages for streaming later (for consistency with rest of code)
                    api_messages = mistral_conversation
                        
                except Exception as mistral_error:
                    # Both APIs failed
                    print(f"[DEBUG] Mistral API failed: {mistral_error}")
                    print(traceback.format_exc())
                    error_msg = f"Backup API also failed: {mistral_error}"
                    if minimax_error_msg:
                        error_msg = f"Primary API failed: {minimax_error_msg}. {error_msg}"
                    raise Exception(error_msg)
            else:
                # No backup available
                if minimax_error_msg:
                    raise Exception(f"Primary API failed: {minimax_error_msg}. No backup API configured.")
                else:
                    raise Exception("No API client available. Please set ANTHROPIC_API_KEY or MISTRAL_API_KEY.")
        
        # Clear the status message
        status_placeholder.empty()
        
        # Display the final response with real streaming
        if all_tool_names:
            st.markdown('<div class="assistant-wrapper">', unsafe_allow_html=True)
            with st.chat_message("assistant"):
                st.markdown(f'<span class="tool-badge">📚 {format_tool_names(all_tool_names)}</span>', unsafe_allow_html=True)
                
                # Use appropriate API for streaming based on which one succeeded
                if using_backup:
                    # For Mistral backup, make a fresh streaming call with the conversation so far
                    stream = st.session_state.mistral_client.chat.stream(
                        model=MISTRAL_MODEL,
                        messages=api_messages,  # api_messages is already mistral_conversation
                        tools=MISTRAL_TOOLS,
                        tool_choice="auto"
                    )
                    gen, _, final_msg_container = mistral_stream_generator(stream)
                    streamed_text = st.write_stream(gen)
                    response = final_msg_container[0]
                else:
                    # Try MiniMax for streaming, fallback to Mistral if it fails
                    try:
                        gen, _, final_msg_container = call_minimax_api(
                            st.session_state.minimax_client, api_messages, TOOLS, SYSTEM_PROMPT, collect_only=False
                        )
                        streamed_text = st.write_stream(gen)
                        response = final_msg_container[0]
                    except Exception as stream_error:
                        # Fallback to Mistral for streaming - build Mistral conversation from scratch
                        if st.session_state.mistral_client:
                            print(f"MiniMax streaming failed, using Mistral: {stream_error}")
                            mistral_conv = [{"role": "system", "content": SYSTEM_PROMPT}]
                            for m in st.session_state.messages:
                                if m["role"] == "user" and isinstance(m["content"], str):
                                    mistral_conv.append({"role": "user", "content": m["content"]})
                            stream = st.session_state.mistral_client.chat.stream(
                                model=MISTRAL_MODEL,
                                messages=mistral_conv,
                                tools=MISTRAL_TOOLS,
                                tool_choice="auto"
                            )
                            gen, _, final_msg_container = mistral_stream_generator(stream)
                            streamed_text = st.write_stream(gen)
                            response = final_msg_container[0]
                        else:
                            raise
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="assistant-wrapper">', unsafe_allow_html=True)
            with st.chat_message("assistant"):
                # Use appropriate API for streaming based on which one succeeded
                if using_backup:
                    # For Mistral backup, make a fresh streaming call
                    stream = st.session_state.mistral_client.chat.stream(
                        model=MISTRAL_MODEL,
                        messages=api_messages,  # api_messages is already mistral_conversation
                        tools=MISTRAL_TOOLS,
                        tool_choice="auto"
                    )
                    gen, _, final_msg_container = mistral_stream_generator(stream)
                    streamed_text = st.write_stream(gen)
                    response = final_msg_container[0]
                else:
                    # Try MiniMax for streaming, fallback to Mistral if it fails
                    try:
                        gen, _, final_msg_container = call_minimax_api(
                            st.session_state.minimax_client, api_messages, TOOLS, SYSTEM_PROMPT, collect_only=False
                        )
                        streamed_text = st.write_stream(gen)
                        response = final_msg_container[0]
                    except Exception as stream_error:
                        # Fallback to Mistral for streaming - build Mistral conversation from scratch
                        if st.session_state.mistral_client:
                            print(f"MiniMax streaming failed, using Mistral: {stream_error}")
                            mistral_conv = [{"role": "system", "content": SYSTEM_PROMPT}]
                            for m in st.session_state.messages:
                                if m["role"] == "user" and isinstance(m["content"], str):
                                    mistral_conv.append({"role": "user", "content": m["content"]})
                            stream = st.session_state.mistral_client.chat.stream(
                                model=MISTRAL_MODEL,
                                messages=mistral_conv,
                                tools=MISTRAL_TOOLS,
                                tool_choice="auto"
                            )
                            gen, _, final_msg_container = mistral_stream_generator(stream)
                            streamed_text = st.write_stream(gen)
                            response = final_msg_container[0]
                        else:
                            raise
            st.markdown('</div>', unsafe_allow_html=True)

        # Store the final response in session state
        if response and response.content:
            st.session_state.messages.append({"role": "assistant", "content": response.content, "tool_names": all_tool_names, "is_final": True})
        # Clear any previous error
        if "last_error" in st.session_state:
            del st.session_state.last_error

    except Exception as e:
        status_placeholder.empty()
        error_msg = str(e)
        print(f"Final error: {error_msg}")
        print(traceback.format_exc())
        # Store error in session state so it persists after rerun
        st.session_state.last_error = error_msg
        # Keep the user message so they can see what they asked
        # Don't pop the message - let the user see it
    finally:
        st.session_state.processing = False
        st.rerun()

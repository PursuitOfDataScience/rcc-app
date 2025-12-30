#!/usr/bin/env python3
"""
RCC User Guide AI Assistant - Streamlit App
A chatbot that answers questions using RCC documentation (RAG-only, no command-line tools).
Now with file upload support for PDFs and images.
"""
import os
import sys
import json
import random
import base64
import anthropic
import streamlit as st
from io import BytesIO

# --- API Configuration ---
API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    st.error("❌ ANTHROPIC_API_KEY environment variable not set.")
    st.stop()

MODEL = "MiniMax-M2.1"
DOCS_BASE_PATH = "./docs"
WEB_BASE_PATH = "./web"


def get_client():
    """Create an Anthropic client configured for MiniMax."""
    return anthropic.Anthropic(
        api_key=API_KEY,
        base_url="https://api.minimax.io/anthropic"
    )


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


def encode_image_to_base64(file_bytes: bytes) -> str:
    """Encode image bytes to base64 string."""
    return base64.standard_b64encode(file_bytes).decode("utf-8")


def get_image_media_type(filename: str) -> str:
    """Get the media type based on file extension."""
    ext = filename.lower().split('.')[-1]
    media_types = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'webp': 'image/webp',
    }
    return media_types.get(ext, 'image/png')


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
    
    elif any(filename.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
        base64_data = encode_image_to_base64(file_bytes)
        media_type = get_image_media_type(filename)
        return {
            "type": "image",
            "filename": uploaded_file.name,
            "media_type": media_type,
            "base64_data": base64_data
        }
    
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
        if file_data["type"] == "image":
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": file_data["media_type"],
                    "data": file_data["base64_data"]
                }
            })
            text_with_context = f"[Attached image: {file_data['filename']}]\n\n{user_text}"
            content.append({"type": "text", "text": text_with_context})
        
        elif file_data["type"] == "pdf":
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
- Images: You can view and analyze images directly
- Text files: You will receive the file contents

GUIDELINES:
- Use documentation tools to answer questions about RCC systems and procedures
- When users upload files, analyze them and provide helpful information
- Be helpful, accurate, and cite specific commands when possible
- NEVER include raw markdown syntax like {:target="_blank"} in responses

TOPICS: Accounts, SSH, Slurm jobs, storage, Python, R, MATLAB, GPUs, containers, and more."""


# --- Streamlit App ---
st.set_page_config(page_title="Sage", page_icon="🤖", layout="wide", initial_sidebar_state="collapsed")

# CSS
st.markdown("""
<style>
    html, body {height: 100%;}
    .stDeployButton, #MainMenu, footer {display: none !important; visibility: hidden !important;}
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display: none !important;}
    body.welcome-page { overflow: hidden; }
    
    .main .block-container {
        padding-top: 0.5rem;
        padding-bottom: 0;
        max-width: 1000px;
    }
    
    [data-testid="stVerticalBlock"] > div {
        margin-bottom: 0 !important;
    }
    
    /* Welcome screen */
    .welcome-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-height: calc(100vh - 220px);
        text-align: center;
        padding: 1.25rem 1rem 0;
        gap: 0.35rem;
    }
    
    .welcome-icon {
        font-size: 3.5rem;
        margin-bottom: 0.35rem;
    }
    
    .welcome-title {
        font-size: 2.1rem;
        font-weight: 600;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.5rem;
    }
    
    /* Chat input */
    .chat-input-row {
        position: relative;
        max-width: 900px;
        margin: 0.5rem auto 0 auto;
    }
    
    .stChatInput {
        max-width: 900px !important;
        margin: 0 auto !important;
        position: relative;
    }
    
    .stChatInput > div {
        border-radius: 24px !important;
        border: 2px solid #e5e7eb !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1) !important;
        min-height: 56px !important;
        display: flex !important;
        align-items: center !important;
        padding-left: 64px !important;
        position: relative !important;
    }
    
    .stChatInput > div:focus-within {
        border-color: #667eea !important;
        box-shadow: 0 4px 20px rgba(102, 126, 234, 0.25) !important;
    }
    
    .stChatInput textarea {
        font-size: 1.1rem !important;
        padding: 16px 24px !important;
        line-height: 1.5 !important;
        display: flex !important;
        align-items: center !important;
        min-height: 24px !important;
        height: auto !important;
        resize: none !important;
        vertical-align: middle !important;
    }
    
    .stChatInput textarea:not(:focus) {
        padding-top: 16px !important;
        padding-bottom: 16px !important;
    }
    
    .stChatInput textarea::placeholder {
        font-size: 1.1rem !important;
        color: #9ca3af !important;
        line-height: 1.5 !important;
    }
    
    .stChatInput div[data-baseweb="textarea"] {
        padding: 0 !important;
    }
    
    .stChatInput div[data-baseweb="base-input"] {
        min-height: 56px !important;
        display: flex !important;
        align-items: center !important;
    }
    
    /* Example buttons - animated cards */
    .question-card {
        background: linear-gradient(145deg, #0f172a 0%, #111827 45%, #0b1224 100%) !important;
        border: 1px solid #1f2937 !important;
        border-radius: 16px !important;
        padding: 14px 18px !important;
        text-align: left !important;
        font-size: 0.95rem !important;
        color: #e5e7eb !important;
        height: auto !important;
        min-height: 58px !important;
        letter-spacing: 0.01em;
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255,255,255,0.02) !important;
        position: relative;
        overflow: hidden;
        opacity: 0;
        transform: translateY(26px) scale(0.97);
        animation: questionRise 0.7s cubic-bezier(0.22, 1, 0.36, 1) forwards;
        animation-delay: calc(var(--card-order, 0) * 0.1s);
        transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
    }
    
    .question-card::after {
        content: "";
        position: absolute;
        inset: 0;
        background: radial-gradient(circle at 20% 20%, rgba(94, 234, 212, 0.12), transparent 35%),
                    radial-gradient(circle at 80% 0%, rgba(129, 140, 248, 0.16), transparent 30%);
        pointer-events: none;
    }
    
    @keyframes questionRise {
        to { opacity: 1; transform: translateY(0) scale(1); }
    }
    
    .question-card:hover {
        border-color: #6366f1 !important;
        transform: translateY(-2px) scale(1.01);
        box-shadow: 0 16px 40px rgba(99, 102, 241, 0.25);
    }
    
    .question-card:active {
        transform: translateY(0) scale(0.995);
    }
    
    /* User message */
    .user-message {
        display: flex;
        justify-content: flex-end;
        margin: 0.5rem 0 1rem 0;
        padding-right: 1rem;
    }
    
    .user-bubble, .user-bubble-with-attachment {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 12px 18px;
        border-radius: 18px 18px 4px 18px;
        font-size: 0.95rem;
        line-height: 1.5;
        max-width: 70%;
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
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
    
    /* Assistant message */
    .assistant-wrapper {
        margin: 0.5rem 0 1rem 0;
    }
    
    .stChatMessage {
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
    }
    
    .stChatMessage [data-testid="chatAvatarIcon-assistant"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    }
    
    /* Hide anchor links */
    .stMarkdown a.header-anchor,
    .stMarkdown h1 a, .stMarkdown h2 a, .stMarkdown h3 a,
    .stMarkdown h4 a, .stMarkdown h5 a, .stMarkdown h6 a,
    a[href^="#"], a:empty {
        display: none !important;
    }
    
    /* Tool badge */
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
    
    /* Chat container */
    .chat-container {
        padding-bottom: 120px;
        margin-top: 0;
    }
    
    /* Status animation */
    .search-status {
        padding: 0.5rem 1rem;
        margin: 0.5rem 0;
    }
    
    .search-text {
        background: linear-gradient(90deg, #667eea, #764ba2, #667eea);
        background-size: 200% 100%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: shimmer 1.5s ease-in-out infinite;
        font-weight: 500;
        font-size: 0.9rem;
    }
    
    @keyframes shimmer {
        0% { background-position: 100% 0; }
        50% { background-position: 0% 0; }
        100% { background-position: 100% 0; }
    }
    
    /* File uploader as paperclip */
    [data-testid="stFileUploader"] {
        width: 44px;
        margin: 0;
        position: absolute;
        left: 12px;
        bottom: 10px;
        z-index: 10;
    }
    
    [data-testid="stFileUploader"] section {
        padding: 0 !important;
        border: 1px solid #1f2937 !important;
        border-radius: 12px !important;
        background: linear-gradient(135deg, #111827 0%, #0f172a 100%) !important;
        min-height: 44px !important;
        box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
        position: relative;
        overflow: hidden;
    }
    
    [data-testid="stFileUploader"] section > div:not([data-testid]) {
        display: none !important;
    }
    
    [data-testid="stFileUploader"] section input[type="file"] {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        opacity: 0;
        cursor: pointer;
    }
    
    [data-testid="stFileUploader"] section::after {
        content: "📎";
        display: flex;
        align-items: center;
        justify-content: center;
        color: #e5e7eb;
        font-size: 1.05rem;
        width: 100%;
        height: 100%;
    }
    
    /* Attachment preview */
    .attachment-preview-bar {
        max-width: 900px;
        margin: 0.25rem auto 0.25rem auto;
        padding: 0 1rem;
    }
    
    .attachment-preview {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 8px 14px;
        border-radius: 16px;
        font-size: 0.85rem;
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
    }
    
    /* Paste hint */
    .paste-hint {
        text-align: center;
        color: #9ca3af;
        font-size: 0.75rem;
        margin-top: 0.35rem;
        opacity: 0.8;
    }
    
    @media (prefers-color-scheme: dark) {
        .tool-badge {
            background: #1e3a5f;
            color: #7dd3fc;
            border-color: #0369a1;
        }
        [data-testid="stFileUploader"] section {
            border-color: #30364f !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "processing" not in st.session_state:
    st.session_state.processing = False
if "client" not in st.session_state:
    st.session_state.client = get_client()
if "uploaded_file_data" not in st.session_state:
    st.session_state.uploaded_file_data = None

# JavaScript for drag/drop, paste, auto-focus, and welcome layout
import streamlit.components.v1 as components


def collect_stream_response(stream):
    """Collect full response from streaming API."""
    full_text = ""
    tool_use_blocks = []
    current_tool = None
    current_tool_input = ""

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
    return full_text, tool_use_blocks, final_message


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
        'pdf': '📄', 'png': '🖼️', 'jpg': '🖼️', 'jpeg': '🖼️', 'gif': '🖼️', 'webp': '🖼️',
        'txt': '📝', 'md': '📝', 'py': '🐍', 'json': '📋', 'csv': '📊',
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


# Example questions - ORIGINAL full text
EXAMPLES = [
    ("🚀", "How do I connect to Midway via SSH?"),
    ("💾", "What are the storage quotas on Midway?"),
    ("⚙️", "How do I submit a batch job with sbatch?"),
    ("🐍", "How do I set up a Python environment?"),
    ("🎮", "How do I run PyTorch on GPUs?"),
    ("📊", "How do I check my allocation balance?"),
]

has_messages = len(st.session_state.messages) > 0

components.html(f"""
<script>
(function() {{
    const doc = window.parent.document;
    const hasMessages = {str(has_messages).lower()};
    const exampleButtons = {json.dumps([f"{icon}  {question}" for icon, question in EXAMPLES])};
    
    // Toggle welcome overflow
    doc.body.classList.toggle('welcome-page', !hasMessages);
    
    // Move uploader next to chat input
    const fileUploader = doc.querySelector('[data-testid="stFileUploader"]');
    const chatInput = doc.querySelector('[data-testid="stChatInput"]');
    if (fileUploader && chatInput && !chatInput.contains(fileUploader)) {{
        chatInput.prepend(fileUploader);
    }}

    // Decorate example buttons and stagger animations
    const buttons = Array.from(doc.querySelectorAll('button'));
    const welcomeButtons = buttons.filter(btn => exampleButtons.includes(btn.innerText.trim())).slice(0, 6);
    welcomeButtons.forEach((btn, idx) => {{
        btn.classList.add('question-card');
        btn.style.setProperty('--card-order', idx);
    }});

    // Paste to file input
    doc.addEventListener('paste', function(e) {{
        const items = e.clipboardData?.items || [];
        for (let i = 0; i < items.length; i++) {{
            if (items[i].type && items[i].type.indexOf('image') !== -1) {{
                const file = items[i].getAsFile();
                const fileInput = doc.querySelector('input[type="file"]');
                if (fileInput && file) {{
                    const dt = new DataTransfer();
                    dt.items.add(file);
                    fileInput.files = dt.files;
                    fileInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
                break;
            }}
        }}
    }});

    // Auto-focus chat input on key press
    doc.addEventListener('keydown', function(e) {{
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.ctrlKey || e.altKey || e.metaKey) return;
        const ignore = ['Escape', 'Tab', 'CapsLock', 'Shift', 'Control', 'Alt', 'Meta', 
                        'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
                        'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12'];
        if (ignore.includes(e.key)) return;
        const input = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (input) input.focus();
    }});

    // Scroll positioning
    if (hasMessages) {{
        window.parent.scrollTo({{ top: doc.body.scrollHeight, behavior: 'smooth' }});
    }} else {{
        window.parent.scrollTo({{ top: 0, behavior: 'auto' }});
    }}
}})();
</script>
""", height=0)

if not has_messages:
    # Welcome screen
    st.markdown('''
    <div class="welcome-container">
        <div class="welcome-icon">📚 ✨ 🎯</div>
        <h1 class="welcome-title">What can I help you with?</h1>
    </div>
    ''', unsafe_allow_html=True)
    
    # ORIGINAL 2-column layout with full questions
    cols = st.columns(2)
    for i, (icon, question) in enumerate(EXAMPLES):
        with cols[i % 2]:
            if st.button(f"{icon}  {question}", key=f"ex_{i}", use_container_width=True):
                st.session_state.messages.append({"role": "user", "content": question})
                st.session_state.processing = True
                st.rerun()

else:
    # Chat mode
    _, col2 = st.columns([20, 1])
    with col2:
        if st.button("🗑️", key="clear", help="Clear"):
            st.session_state.messages = []
            st.session_state.processing = False
            st.session_state.uploaded_file_data = None
            st.rerun()
    
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            display_text = msg.get("display_text", msg["content"] if isinstance(msg["content"], str) else "")
            file_info = msg.get("file_info")
            render_user_message(display_text, file_info)
        elif msg["role"] == "assistant" and msg.get("is_final"):
            text = extract_display_text(msg["content"])
            if text:
                render_assistant_message(text, msg.get("tool_names"))
    st.markdown('</div>', unsafe_allow_html=True)

# File uploader (paperclip button beside input)
uploaded_file = st.file_uploader(
    "Attach a file",
    type=['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'txt', 'md', 'py', 'json', 'csv'],
    key="file_uploader",
    label_visibility="collapsed",
    help="Attach PDFs, images, or text files (limit 200MB per file)."
)

if uploaded_file is not None and st.session_state.uploaded_file_data is None:
    file_data = process_uploaded_file(uploaded_file)
    st.session_state.uploaded_file_data = file_data

# Attachment preview
if st.session_state.uploaded_file_data and st.session_state.uploaded_file_data.get("type") != "error":
    file_data = st.session_state.uploaded_file_data
    icon = get_file_icon(file_data.get("filename", "file"))
    
    col1, col2 = st.columns([10, 1])
    with col1:
        st.markdown(f'''
        <div class="attachment-preview-bar">
            <div class="attachment-preview">
                <span>{icon}</span>
                <span>{file_data.get("filename", "file")}</span>
            </div>
        </div>
        ''', unsafe_allow_html=True)
    with col2:
        if st.button("✕", key="remove_attachment", help="Remove"):
            st.session_state.uploaded_file_data = None
            st.rerun()

# Hint
if not has_messages:
    st.markdown('<div class="paste-hint">💡 Click the paperclip to attach a file or paste an image (Ctrl+V)</div>', unsafe_allow_html=True)

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
    
    st.rerun()

# Process
if st.session_state.processing:
    status_messages = ["🧠 Contemplating...", "✨ Vibing...", "⏳ Brewing...", "🎨 Crafting...", "🔧 Tinkering..."]
    st.markdown(f'<div class="search-status"><span class="search-text">{random.choice(status_messages)}</span></div>', unsafe_allow_html=True)
    
    api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    
    try:
        stream = st.session_state.client.messages.stream(model=MODEL, max_tokens=8192, system=SYSTEM_PROMPT, messages=api_messages, tools=TOOLS)
        response_text, tool_use_blocks, response = collect_stream_response(stream)
        all_tool_names = [tb["name"] for tb in tool_use_blocks]

        while tool_use_blocks:
            api_messages.append({"role": "assistant", "content": response.content})
            tool_results = [{"type": "tool_result", "tool_use_id": tb["id"], "content": execute_tool(tb["name"], tb["input"])} for tb in tool_use_blocks]
            api_messages.append({"role": "user", "content": tool_results})
            
            stream = st.session_state.client.messages.stream(model=MODEL, max_tokens=8192, system=SYSTEM_PROMPT, messages=api_messages, tools=TOOLS)
            response_text, tool_use_blocks, response = collect_stream_response(stream)
            all_tool_names.extend([tb["name"] for tb in tool_use_blocks])

        if response and response.content:
            st.session_state.messages.append({"role": "assistant", "content": response.content, "tool_names": all_tool_names, "is_final": True})

    except Exception as e:
        st.error(f"Error: {e}")
        if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
            st.session_state.messages.pop()
    finally:
        st.session_state.processing = False
        st.rerun()

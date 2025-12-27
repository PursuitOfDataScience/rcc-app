#!/usr/bin/env python3
"""
RCC User Guide AI Assistant - Streamlit App
A chatbot that answers questions using RCC documentation (RAG-only, no command-line tools).
"""
import os
import sys
import json
import anthropic
import streamlit as st
import streamlit.components.v1 as components

# --- API Configuration ---
API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    st.error("❌ ANTHROPIC_API_KEY environment variable not set.")
    st.stop()

MODEL = "MiniMax-M2.1-lightning"
DOCS_BASE_PATH = "./docs"
WEB_BASE_PATH = "./web"


def get_client():
    """Create an Anthropic client configured for MiniMax."""
    return anthropic.Anthropic(
        api_key=API_KEY,
        base_url="https://api.minimax.io/anthropic"
    )


# --- Documentation Reader (RAG) ---
def read_document(file_path: str, base_path: str = None) -> str:
    """Read a markdown or text document and return its contents."""
    if base_path is None:
        base_path = DOCS_BASE_PATH
    full_path = os.path.join(base_path, file_path)
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Truncate if too long (to fit in context)
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

# Web content path mappings (scraped from RCC website)
WEB_DOC_PATHS = {
    # About RCC section
    "read_web_about_rcc": "about-rcc.txt",
    "read_web_advisory_committees": "about-rcc_advisory-committees.txt",
    "read_web_ai_spotlight": "about-rcc_artificial-intelligence-spotlight-mind-bytes-2018.txt",
    "read_web_director_welcome": "about-rcc_director's-welcome.txt",
    "read_web_rcc_team": "about-rcc_our-team.txt",
    "read_web_user_policy": "about-rcc_rcc-user-policy.txt",
    "read_web_oversight_committee": "about-rcc_research-computing-oversight-committee.txt",
    "read_web_vision_mission": "about-rcc_vision-mission.txt",
    
    # Access and accounts
    "read_web_access": "access.txt",
    "read_web_accounts_allocations": "accounts-allocations.txt",
    
    # Grants and publications
    "read_web_grants_publications": "grants-publications.txt",
    "read_web_acknowledging_rcc": "grants-publications_acknowledging-the-RCC.txt",
    "read_web_facilities_resources": "grants-publications_facilities-and-resources-documents.txt",
    "read_web_pi_proposals": "grants-publications_for-PI-proposals.txt",
    "read_web_grant_support": "grants-publications_grant-support.txt",
    "read_web_hardware_quotes": "grants-publications_hardware-quotes.txt",
    "read_web_publications_list": "grants-publications_list-of-publications.txt",
    "read_web_publications": "grants-publications_publications.txt",
    "read_web_support_letters": "grants-publications_support-letters.txt",
    
    # Resources
    "read_web_resources": "resources.txt",
    "read_web_hpc_resources": "resources_high-performance-computing.txt",
    "read_web_hosted_data": "resources_hosted-data.txt",
    "read_web_networking": "resources_networking.txt",
    "read_web_software_resources": "resources_software.txt",
    "read_web_storage_backup": "resources_storage-and-backup.txt",
    
    # Support and services
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
    
    # Other pages
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
    
    # Research showcase/case studies
    "read_web_bayesian_forest": "bayesian-forest-cities-full-data.txt",
    "read_web_big_data_worms": "big-data-sleeping-worms-and-electronic-chef.txt",
    "read_web_our_work": "our-work-color.txt",
    "read_web_tools_resources": "tools-resources-color.txt",
    
    # Medical/research specific
    "read_web_incidence": "incidence.txt",
    "read_web_mpmri": "mpMRI.txt",
    "read_web_pirads": "pirads.txt",
    "read_web_publications_page": "publications.txt",
    "read_web_takecourse": "takecourse.txt",
    "read_web_user_guide_page": "user-guide.txt",
}


# --- Tool Definitions (Documentation only) ---
TOOLS = [
    {
        "name": "read_accounts_doc",
        "description": """Read documentation about RCC accounts and how to apply for them.
        
COVERS: How to apply for RCC accounts (PI accounts, general user accounts, education accounts), 
CNetID credentials, account types, account FAQs, how external collaborators can get access,
password management, multiple affiliations, what to do when leaving UChicago.

USE WHEN: User asks about creating accounts, getting access to RCC, CNetID, account types,
sponsor requirements, education accounts, or account-related procedures.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_connecting_doc",
        "description": """Read documentation about connecting to and accessing RCC clusters.
        
COVERS: Overview of connection methods (SSH, ThinLinc, Open OnDemand, SAMBA, Globus, HTTP),
RCC account credentials, supported protocols comparison table, basic SSH/SFTP usage.

USE WHEN: User asks about how to connect to Midway, access methods, what protocols are available,
or needs an overview of connection options.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_jobs_tutorial_doc",
        "description": """Read the beginner tutorial for running jobs on compute nodes.
        
COVERS: Basic tutorial for checking allocations (rcchelp balance), starting interactive sessions
with sinteractive, loading python modules, creating and running simple Python scripts, 
submitting basic batch jobs with sbatch, checking job queue with squeue.

USE WHEN: User is a beginner asking how to run their first job, needs a simple tutorial,
or wants basic examples of sinteractive and sbatch.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_allocations_doc",
        "description": """Read documentation about allocations and service units (SUs).
        
COVERS: What allocations are, what service units (SUs) are, how to obtain allocations,
how SU consumption is calculated, checking remaining SUs with 'accounts balance' command,
reviewing allocation usage with 'accounts usage', storage allocations, MyRCC portal.

USE WHEN: User asks about service units, SUs, allocations, compute credits, checking balance,
or how resource usage is tracked/charged.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_software_tutorial_doc",
        "description": """Read the beginner tutorial for setting up software on Midway.
        
COVERS: Using 'module avail' and 'module load', loading Python, creating Python virtual 
environments in /project, installing packages with pip, building software from source,
loading compilers and MPI libraries for compilation.

USE WHEN: User is new and asks how to get started with software, load modules, or set up
their first environment.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_data_tutorial_doc",
        "description": """Read the beginner tutorial for data management on Midway.
        
COVERS: Brief overview of storage locations (/project, /project2, /scratch), recommendation
to put input/output data in these locations, basic data download commands (git clone, wget).

USE WHEN: User is new and asks about where to put their data or basic data preparation.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_policies_doc",
        "description": """Read RCC terms of use and policies documentation.
        
COVERS: General usage policies (responsibility, legality, ethics, respect, confidentiality,
security, monitoring), user account and password policies, data management policies,
restricted research data guidelines, data integrity and retention.

USE WHEN: User asks about RCC policies, terms of use, what is/isn't allowed, data security
requirements, or restricted data handling.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_glossary_doc",
        "description": """Read the HPC glossary of terms.
        
COVERS: Definitions of: batch job, compute cluster, compute node, core, distributed memory,
FLOPS, GPU, HPC, Infiniband, job, login node, modules, node, OpenMP, partition, shared memory,
Slurm, socket, SSH, walltime.

USE WHEN: User asks what a specific HPC term means or needs terminology explained.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_mistakes_doc",
        "description": """Read documentation about common mistakes to avoid on RCC clusters.
        
COVERS: Storage quota issues, conda environment installation mistakes (use /project not /home),
running jobs on login nodes (DON'T!), no internet access in batch jobs, using too many cores
for serial jobs, GPU allocation for non-GPU codes, using outdated GCC, scratch space I/O.

USE WHEN: User is having issues, making errors, or asks about best practices and what to avoid.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_helpdesk_doc",
        "description": """Read documentation about getting help from RCC support.
        
COVERS: How to contact RCC help desk, what information to include in help requests
(module list, sbatch scripts, error messages, job IDs, working directory).

USE WHEN: User asks how to get help, contact support, or report issues.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_ecosystems_doc",
        "description": """Read overview of RCC's HPC systems and clusters.
        
COVERS: Overview of all RCC clusters including Midway2, Midway3, Midway3-AMD, MidwaySSD, 
DaLI, Beagle3, KICP, GM4, MidwayR family, Skyway. Describes which clusters are shared vs 
restricted, what each is optimized for.

USE WHEN: User asks what clusters are available, differences between clusters, or which
cluster to use for their work.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_clusters_doc",
        "description": """Read detailed hardware specifications for Midway2 and Midway3 clusters.
        
COVERS: Midway3 specs (Intel Cascade Lake nodes with 48 cores, 192GB RAM; GPU nodes with
V100, RTX6000, A100; big memory nodes with 768GB-1.5TB; AMD nodes with 128 cores).
Midway2 specs (Intel Broadwell nodes with 28 cores, 64GB RAM; K80 GPU nodes).

USE WHEN: User asks about hardware specs, node configurations, how many cores/GPUs available,
memory per node, or cluster architecture.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_partitions_doc",
        "description": """Read documentation about Slurm partitions and their configurations.
        
COVERS: What partitions are, how to list partitions (sinfo command), partition configurations
for Midway2, Midway3, Beagle3. Quality of Service (QoS) limits: max nodes/user, max CPUs/user,
max jobs/user, max wall time. Private/CPP partitions.

USE WHEN: User asks about partitions, which partition to use, partition limits, QoS,
or resource limits per partition.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_beagle3_doc",
        "description": """Read documentation about Beagle3 cluster for biomedical research.
        
COVERS: What Beagle3 is (NIH-funded GPU cluster for biomedical research, cryo-EM, molecular
simulations), hardware specs (44 nodes with Intel Gold 6346 CPUs, NVIDIA A100/A40 GPUs),
how to gain access, partitions, QoS options.

USE WHEN: User asks about Beagle3, biomedical computing, cryo-EM, molecular dynamics,
or A100/A40 GPU access.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_slurm_main_doc",
        "description": """Read main SLURM documentation for running jobs on RCC clusters.
        
COVERS: Service units and allocations overview, what Slurm is and how it works as a scheduler,
difference between interactive (sinteractive) vs batch (sbatch) jobs, job limits and QoS.

USE WHEN: User asks about Slurm basics, how job scheduling works, or differences between
interactive and batch jobs.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_sinteractive_doc",
        "description": """Read documentation about interactive jobs with sinteractive.
        
COVERS: How to request interactive sessions, default parameters (2 hour time limit),
sinteractive command options (--time, --nodes, --exclusive, --partition, --account),
debug QoS for quick testing (15 min, no SU charge), memory requests.

USE WHEN: User asks about interactive sessions, sinteractive command, getting a node
for interactive work, or debug QoS.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_sbatch_doc",
        "description": """Read comprehensive documentation about batch job submission.
        
COVERS: SBATCH script format and directives, job monitoring (squeue, scontrol, sacct),
job state codes, job reason codes, pausing/resuming jobs, canceling jobs (scancel).
EXAMPLES: Single core jobs, GPU jobs, large-memory jobs, MPI jobs, hybrid MPI/OpenMP jobs,
job arrays for parameter sweeps, GNU Parallel, dependency jobs, cron-like jobs.

USE WHEN: User asks about sbatch scripts, batch job examples, job monitoring, job status,
MPI jobs, GPU jobs, job arrays, or parallel job submission.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_slurm_faq_doc",
        "description": """Read Slurm frequently asked questions.
        
COVERS: How to submit jobs, logging into compute nodes, running jobs in parallel,
job limits, using multiple accounts, getting email notifications for jobs,
running jobs longer than max wall time, cron jobs, why jobs aren't starting,
why jobs fail quickly, memory limit errors, compiler support, MPI versions.

USE WHEN: User has a Slurm-related question or issue not covered in main docs.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_storage_main_doc",
        "description": """Read main storage documentation for RCC clusters.
        
COVERS: Storage layout (home, project, project2, beagle3, scratch directories),
storage quotas (soft/hard limits, grace periods) - home: 30GB, scratch: 100GB soft/5TB hard.
High-performance storage, global scratch, local scratch ($TMPDIR).
Cost-effective Data Storage (CDS). Snapshots for data recovery.

USE WHEN: User asks about storage locations, quotas, scratch space, backups, snapshots,
data recovery, or storage limits.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_storage_faq_doc",
        "description": """Read storage frequently asked questions.
        
COVERS: Checking storage usage, what to do when over quota, moving files between directories,
requesting more storage, sharing files with others, recovering accidentally deleted files
using snapshots, unlocking access to files from departed users.

USE WHEN: User has storage issues, quota problems, needs to share files, or recover data.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_ssh_main_doc",
        "description": """Read SSH connection documentation.
        
COVERS: What SSH is, how to SSH from Mac and Windows, SSH host addresses for all clusters
(Midway2, Midway3, Midway3-AMD, DaLI, Beagle3, SSD), Duo two-factor authentication.
Data transfer: SCP commands and examples, SFTP protocol, Rsync for file synchronization.

USE WHEN: User asks about SSH connection, login commands, SCP file transfer, rsync,
or connection troubleshooting.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_ssh_advanced_doc",
        "description": """Read advanced SSH options documentation.
        
COVERS: Advanced SSH command options, X11 forwarding, SSH config file setup,
key-based authentication, port forwarding.

USE WHEN: User asks about advanced SSH features, X11 forwarding, SSH keys, or SSH config.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_ssh_faq_doc",
        "description": """Read SSH frequently asked questions.
        
COVERS: Common SSH connection issues and troubleshooting.

USE WHEN: User has SSH connection problems or errors.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_thinlinc_doc",
        "description": """Read ThinLinc remote desktop documentation.
        
COVERS: What ThinLinc is (remote desktop/GUI access), connecting via web browser URLs
for each cluster, connecting via ThinLinc client app, ThinLinc interface navigation,
maintaining sessions, remote visualization on GPU nodes (sviz command).

USE WHEN: User asks about ThinLinc, remote desktop, GUI access, graphical applications,
or visualization on Midway.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_ondemand_doc",
        "description": """Read Open OnDemand web portal documentation.
        
COVERS: What Open OnDemand is (web-based HPC portal), features (file management, job
management, interactive apps, terminal access), dashboard navigation, file manager,
job composer, interactive apps (Jupyter, RStudio, VS Code, Desktop).

USE WHEN: User asks about Open OnDemand, web portal access, browser-based HPC access,
or launching Jupyter/RStudio through the web.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_globus_transfer_doc",
        "description": """Read Globus file transfer documentation.
        
COVERS: What Globus is (robust file transfer service), making your computer a Globus
endpoint, manually transferring files between endpoints, scheduling transfers,
Globus Flows for automated workflows.

USE WHEN: User asks about Globus, large file transfers, scheduled transfers, or
transferring data to/from RCC.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_globus_share_doc",
        "description": """Read Globus file sharing documentation.
        
COVERS: Sharing files with collaborators using Globus.

USE WHEN: User asks about sharing data with collaborators via Globus.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_samba_doc",
        "description": """Read SAMBA/SMB file access documentation.
        
COVERS: Using SAMBA to mount RCC directories on local computer, accessing files
without command line.

USE WHEN: User asks about SAMBA, SMB, mounting RCC directories locally, or
network drive access.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_software_index_doc",
        "description": """Read main software and modules documentation.
        
COVERS: Using 'module avail' to find software, module commands (avail, load, unload, list),
module dependencies, software for AMD CPUs, requesting new software installation,
list of commonly used software packages.

USE WHEN: User asks about finding software, loading modules, module system basics,
or what software is available.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_python_doc",
        "description": """Read Python and Anaconda documentation.
        
COVERS: Python distribution recommendations (Standard Python, Miniforge, Anaconda),
Anaconda licensing issues and inode usage problems, loading Python modules,
UV package manager, environment management best practices, creating environments
in /project not /home, pip vs conda installations.

USE WHEN: User asks about Python, Anaconda, conda, pip, virtual environments,
Jupyter setup, or Python package management.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_tensorflow_pytorch_doc",
        "description": """Read TensorFlow and PyTorch documentation.
        
COVERS: Using TensorFlow/PyTorch on GPU nodes, loading CUDA and cuDNN modules,
recommended module versions, checking GPU engagement with nvidia-smi,
verifying GPU detection in TensorFlow and PyTorch code.

USE WHEN: User asks about TensorFlow, PyTorch, deep learning, GPU computing,
CUDA setup, or machine learning on Midway.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_r_doc",
        "description": """Read R and RStudio documentation.
        
COVERS: Loading R modules, using RStudio on Midway, installing R packages.

USE WHEN: User asks about R, RStudio, R packages, or statistical computing.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_matlab_doc",
        "description": """Read MATLAB documentation.
        
COVERS: Loading MATLAB modules, running MATLAB jobs, MATLAB licensing.

USE WHEN: User asks about MATLAB on Midway.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_singularity_doc",
        "description": """Read Singularity/container documentation.
        
COVERS: Using Singularity containers on Midway, pulling images, running containers,
binding directories.

USE WHEN: User asks about containers, Singularity, Docker, or containerized applications.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_compilers_doc",
        "description": """Read compiler documentation.
        
COVERS: Available compilers (GCC, Intel, PGI, NVIDIA), loading compiler modules,
compiling code, optimization flags.

USE WHEN: User asks about compiling code, gcc, g++, gfortran, Intel compilers,
or compilation issues.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_software_faq_doc",
        "description": """Read software frequently asked questions.
        
COVERS: Common software issues, module conflicts, installation problems.

USE WHEN: User has software-related issues or questions not covered elsewhere.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_alphafold_doc",
        "description": """Read AlphaFold protein structure prediction documentation.
        
COVERS: Running AlphaFold on Midway, AlphaFold databases.

USE WHEN: User asks about AlphaFold or protein structure prediction.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_gromacs_doc",
        "description": """Read GROMACS molecular dynamics documentation.
        
COVERS: Running GROMACS on Midway, GROMACS job scripts.

USE WHEN: User asks about GROMACS or molecular dynamics simulations.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_lammps_doc",
        "description": """Read LAMMPS molecular dynamics documentation.
        
COVERS: Running LAMMPS on Midway, building LAMMPS, LAMMPS job scripts.

USE WHEN: User asks about LAMMPS or molecular dynamics.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_gaussian_doc",
        "description": """Read Gaussian computational chemistry documentation.
        
COVERS: Running Gaussian on Midway, Gaussian licensing, job scripts.

USE WHEN: User asks about Gaussian or quantum chemistry.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_midwayr3_overview_doc",
        "description": """Read MidwayR3 secure computing environment documentation.
        
COVERS: What MidwayR3 is (secure HPC for regulated data - PII, HIPAA, FISMA, FERPA, IRB),
system overview, hardware specs, network (no internet access), file systems, software.

USE WHEN: User asks about MidwayR3, secure computing, regulated data, HIPAA compliance,
or Secure Data Enclave.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_skyway_doc",
        "description": """Read Skyway cloud bursting documentation.
        
COVERS: What Skyway is (cloud bursting to AWS/GCP through Midway), how to use cloud
resources transparently.

USE WHEN: User asks about Skyway, cloud computing, AWS, GCP, or cloud bursting.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_gis_doc",
        "description": """Read GIS and geospatial computing documentation.
        
COVERS: GIS software on Midway, geocoding, geospatial analysis tools.

USE WHEN: User asks about GIS, mapping, geospatial analysis, or geographic data.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_databases_doc",
        "description": """Read database documentation.
        
COVERS: Available databases on Midway (AlphaFold database, BFI data, Booth data).

USE WHEN: User asks about databases or specific data collections available on Midway.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # --- Web Content Tools (scraped from RCC website) ---
    # About RCC section
    {
        "name": "read_web_about_rcc",
        "description": """Read general information about RCC from the website.
        
COVERS: RCC history, mission, how RCC was established (2010-2012), growth of user base,
services offered (HPC, visualization, workshops, consulting), Midway cluster overview,
RCC user lab in Regenstein Library.

USE WHEN: User asks general questions about RCC, its history, what services it provides,
or wants an overview of the organization.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_advisory_committees",
        "description": """Read about RCC advisory committees.
        
COVERS: Information about committees that advise RCC on strategy and operations.

USE WHEN: User asks about RCC governance, advisory committees, or organizational structure.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_ai_spotlight",
        "description": """Read about AI spotlight and Mind Bytes 2018.
        
COVERS: AI research highlights, Mind Bytes symposium information.

USE WHEN: User asks about AI research at RCC or Mind Bytes events.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_director_welcome",
        "description": """Read the RCC Director's welcome message.
        
COVERS: Director's perspective on RCC, leadership vision, strategic priorities.

USE WHEN: User asks about RCC leadership, director, or organizational vision.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_rcc_team",
        "description": """Read about RCC staff and team members.
        
COVERS: List of RCC staff, computational scientists, system administrators,
staff roles and expertise areas, contact information.

USE WHEN: User asks about RCC staff, who to contact for specific expertise,
or wants to know about the RCC team.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_user_policy",
        "description": """Read RCC user policy from the website.
        
COVERS: Acceptable use policies, user responsibilities, terms of service.

USE WHEN: User asks about usage policies, acceptable use, or user responsibilities.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_oversight_committee",
        "description": """Read about the Research Computing Oversight Committee.
        
COVERS: Committee members, role in RCC governance, oversight responsibilities.

USE WHEN: User asks about RCC oversight, governance structure, or committee members.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_vision_mission",
        "description": """Read RCC vision and mission statement.
        
COVERS: RCC mission to advance research, vision for transforming research at UChicago,
key mission statements for research, education, and discovery.

USE WHEN: User asks about RCC's mission, vision, or strategic goals.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # Access and accounts
    {
        "name": "read_web_access",
        "description": """Read about accessing RCC resources.
        
COVERS: How to get access to RCC, access requirements, eligibility.

USE WHEN: User asks about getting access to RCC or eligibility requirements.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_accounts_allocations",
        "description": """Read about RCC accounts and allocations from website.
        
COVERS: Account types, allocation process, how to request resources.

USE WHEN: User asks about accounts or allocations from website perspective.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # Grants and publications
    {
        "name": "read_web_grants_publications",
        "description": """Read overview of grants and publications support.
        
COVERS: Overview of how RCC supports grant proposals and publications.

USE WHEN: User asks about grant support or publication assistance overview.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_acknowledging_rcc",
        "description": """Read how to acknowledge RCC in publications.
        
COVERS: Proper citation text for acknowledging RCC in papers, grant proposals,
and other publications. Required acknowledgment language.

USE WHEN: User asks how to cite or acknowledge RCC in their publications or grants.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_facilities_resources",
        "description": """Read facilities and resources documentation for grants.
        
COVERS: Boilerplate text describing RCC facilities for grant applications,
technical specifications for proposals, resources documentation.

USE WHEN: User needs facilities description for a grant proposal or needs
to document RCC resources in a formal application.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_pi_proposals",
        "description": """Read information for PI proposals.
        
COVERS: Information specifically for PIs writing grant proposals,
how RCC can support proposals, what to include.

USE WHEN: User is a PI preparing a grant proposal and needs RCC support info.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_grant_support",
        "description": """Read about RCC grant support services.
        
COVERS: How RCC helps with grants - brainstorming ideas, solicitation search,
piloting computational projects, hardware quotes, grant writing assistance,
staff expertise (AI/ML, GIS, algorithm development, visualization),
data repositories for sharing and reproducibility.

USE WHEN: User asks about how RCC can help with grant proposals, what grant
services RCC provides, or needs help with a grant application.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_hardware_quotes",
        "description": """Read about hardware quotes for grants.
        
COVERS: How to get hardware quotes for grant proposals, pricing information,
hardware specifications for budgets.

USE WHEN: User needs hardware quotes or pricing for a grant budget.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_publications_list",
        "description": """Read list of publications that used RCC resources.
        
COVERS: Comprehensive list of research publications that acknowledged RCC,
papers across various disciplines that used Midway.

USE WHEN: User asks about research done on RCC, publications using Midway,
or wants examples of RCC-supported research.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_support_letters",
        "description": """Read about support letters from RCC.
        
COVERS: How to request support letters from RCC for grant applications,
what RCC can provide in terms of letters of support.

USE WHEN: User needs a letter of support from RCC for a grant application.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # Resources
    {
        "name": "read_web_resources",
        "description": """Read overview of RCC resources.
        
COVERS: Overview of all RCC resources - compute, storage, software, networking.

USE WHEN: User wants a general overview of what resources RCC provides.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_hpc_resources",
        "description": """Read about high-performance computing resources.
        
COVERS: Midway2 cluster details, CPU architectures (Broadwell, Skylake),
tightly-coupled vs loosely-coupled nodes, shared memory nodes,
Infiniband interconnect, GPU computing with K80 cards, Hadoop,
emerging technologies, total cores and storage capacity.

USE WHEN: User asks about HPC hardware, cluster specifications,
node types, or computing capabilities.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_hosted_data",
        "description": """Read about hosted data resources.
        
COVERS: Data collections hosted at RCC, available datasets,
research data resources.

USE WHEN: User asks about data hosted at RCC or available datasets.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_networking",
        "description": """Read about RCC networking infrastructure.
        
COVERS: Network connectivity, bandwidth, data transfer capabilities,
interconnect technologies.

USE WHEN: User asks about network speed, connectivity, or data transfer rates.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_software_resources",
        "description": """Read about software resources at RCC.
        
COVERS: Overview of software available at RCC, software support,
application availability.

USE WHEN: User asks about what software is available at RCC (overview).""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_storage_backup",
        "description": """Read about storage and backup resources.
        
COVERS: RCC storage systems, persistent storage, high-performance scratch,
home directories, project space, backup and data recovery,
filesystem snapshots, Globus Online endpoint access.

USE WHEN: User asks about storage options, backup systems, or data recovery
from the resources perspective.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # Support and services
    {
        "name": "read_web_support_services",
        "description": """Read overview of RCC support and services.
        
COVERS: Walk-in lab location (Suite 216, Regenstein Library), hours (9am-5pm Mon-Fri),
consulting services, technical support, available services overview.

USE WHEN: User wants to know what support services RCC offers, walk-in hours,
or how to get in-person help.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_cpp",
        "description": """Read about the Cluster Partnership Program (CPP).
        
COVERS: How to purchase dedicated compute and storage through CPP,
hardware options (CPU nodes, large memory nodes, GPU nodes),
storage options (GPFS, CDS), pricing model, what CPP includes
(hosting, maintenance, support), how to contact for CPP.

USE WHEN: User asks about buying dedicated hardware, CPP program,
purchasing compute nodes, or expanding beyond shared resources.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_consultant_partnership",
        "description": """Read about the Consultant Partnership Program.
        
COVERS: How to hire RCC computational scientists or application developers,
purchasing FTE time from RCC staff, extended consulting services.

USE WHEN: User asks about hiring RCC staff, dedicated consulting,
or long-term computational support partnerships.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_consulting_support",
        "description": """Read about consulting and technical support.
        
COVERS: RCC consulting services, technical support offerings, walk-in lab,
in-person consultation options, how to get help with research computing problems.

USE WHEN: User asks about consulting services, technical support options,
or walk-in sessions.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_data_management",
        "description": """Read about data management services.
        
COVERS: Data management and sharing plan assistance (NIH requirements),
data lifecycle management, data curation, metadata preparation,
de-identification services, data access portals, links to UChicago
data management resources (Library, URA).

USE WHEN: User asks about data management plans, NIH data sharing requirements,
or needs help with data management for grants.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_data_sharing",
        "description": """Read about data sharing services.
        
COVERS: How RCC helps with data sharing, data sharing platforms,
making data available to collaborators.

USE WHEN: User asks about sharing data with collaborators or data sharing services.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_midway2_services",
        "description": """Read about Midway2 services specifically.
        
COVERS: Midway2 cluster information, services specific to Midway2.

USE WHEN: User asks specifically about Midway2 services.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_new_faculty",
        "description": """Read about the New Faculty Program.
        
COVERS: Special programs and allocations for new UChicago faculty,
how new faculty can get started with RCC, onboarding support.

USE WHEN: User is a new faculty member or asks about new faculty programs.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_outreach",
        "description": """Read about RCC outreach activities.
        
COVERS: RCC outreach programs, community engagement, educational outreach.

USE WHEN: User asks about RCC outreach or community programs.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_workshops_training",
        "description": """Read about RCC workshops and training programs.
        
COVERS: Workshop schedule (2025-2026), workshop topics (intro to RCC,
distributed data processing, AI/deep learning, Open OnDemand),
in-person hands-on training, industry expert sessions,
vendor training courses.

USE WHEN: User asks about RCC workshops, training sessions, when workshops
are held, or how to learn to use RCC resources.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # Other pages
    {
        "name": "read_web_faqs",
        "description": """Read frequently asked questions from RCC website.
        
COVERS: Common questions and answers about RCC services.

USE WHEN: User has a general question that might be in the FAQ.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_system_details",
        "description": """Read system details and specifications.
        
COVERS: Technical details about RCC systems, hardware specifications.

USE WHEN: User asks about specific system specifications or technical details.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_workshops",
        "description": """Read workshops information page.
        
COVERS: General workshops information.

USE WHEN: User asks about workshops (alternative to workshops_training).""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_workshops_events",
        "description": """Read about workshops and events.
        
COVERS: Upcoming and past workshops, events calendar, event details.

USE WHEN: User asks about upcoming events or workshop schedule.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_data_viz_committee",
        "description": """Read about Data Visualization Initiative Advisory Committee.
        
COVERS: Data visualization advisory committee, visualization initiatives.

USE WHEN: User asks about data visualization initiatives or related committees.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # Research showcases
    {
        "name": "read_web_bayesian_forest",
        "description": """Read research showcase: Bayesian Forest Cities project.
        
COVERS: Case study of research using RCC resources, Bayesian analysis,
urban forestry research.

USE WHEN: User asks about research examples or this specific project.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_big_data_worms",
        "description": """Read research showcase: Big Data, Sleeping Worms, and Electronic Chef.
        
COVERS: Research case studies, interdisciplinary research examples,
how RCC supports diverse research projects.

USE WHEN: User asks about research examples or diverse RCC use cases.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_our_work",
        "description": """Read about RCC's work and research support.
        
COVERS: Examples of RCC work, research projects supported, impact stories.

USE WHEN: User asks about what kind of work RCC does or research impact.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_tools_resources",
        "description": """Read about tools and resources available.
        
COVERS: Overview of tools and resources for researchers.

USE WHEN: User asks about what tools are available at RCC.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # Additional pages
    {
        "name": "read_web_index",
        "description": """Read the RCC homepage/index page.
        
COVERS: Main RCC website landing page content, overview of RCC.

USE WHEN: User asks for general RCC overview or homepage content.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_midway2",
        "description": """Read about Midway2 cluster from website.
        
COVERS: Midway2 cluster overview and information from main website.

USE WHEN: User asks about Midway2 specifically.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_news_events",
        "description": """Read news and events page.
        
COVERS: RCC news, announcements, upcoming events.

USE WHEN: User asks about RCC news or events.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_software",
        "description": """Read software overview page from website.
        
COVERS: Overview of software available at RCC from main website.

USE WHEN: User asks about software availability (overview).""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_team",
        "description": """Read about the RCC team page.
        
COVERS: RCC team members, staff directory, expertise areas.

USE WHEN: User asks about RCC staff or team members.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_publications",
        "description": """Read publications page overview.
        
COVERS: Information about publications and research output.

USE WHEN: User asks about RCC publications overview.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_publications_page",
        "description": """Read the publications landing page.
        
COVERS: Publications information and links.

USE WHEN: User asks about research publications.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_user_guide_page",
        "description": """Read user guide overview from website.
        
COVERS: Overview and links to user guide documentation.

USE WHEN: User asks about user guide or documentation overview.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_takecourse",
        "description": """Read about taking courses/training.
        
COVERS: Course and training information.

USE WHEN: User asks about taking RCC courses.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # Medical/specialized research pages
    {
        "name": "read_web_incidence",
        "description": """Read incidence research page (medical research project).
        
COVERS: Specialized medical research project information.

USE WHEN: User asks about medical incidence research projects.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_mpmri",
        "description": """Read mpMRI research page (multiparametric MRI project).
        
COVERS: Multiparametric MRI research project information.

USE WHEN: User asks about mpMRI or MRI research projects.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_web_pirads",
        "description": """Read PI-RADS research page (prostate imaging).
        
COVERS: PI-RADS prostate imaging research project information.

USE WHEN: User asks about PI-RADS or prostate imaging research.""",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    }
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


# --- System Prompt ---
SYSTEM_PROMPT = """You are the RCC User Guide Assistant for the University of Chicago's Research Computing Center.

You have DOCUMENTATION TOOLS available that retrieve official RCC documentation:
- read_*_doc tools that retrieve markdown documentation files
- read_web_* tools that retrieve content from the RCC website
- Use these tools to answer user questions about RCC systems and procedures

IMPORTANT GUIDELINES:
- For "how to" questions, policy questions, or conceptual questions, use the appropriate documentation tool
- Base your answers on the retrieved documentation content
- Be helpful, accurate, and cite specific commands or procedures when possible
- If information isn't in the documentation, let the user know
- NEVER include raw markdown syntax like {:target="_blank"}, {: .class}, or other kramdown/Jekyll attributes in your responses. Just provide clean, readable text.

TOPICS COVERED:
- Account management and access
- Connecting to clusters (SSH, ThinLinc, Open OnDemand, etc.)
- Running jobs (Slurm, sbatch, sinteractive)
- Storage and quotas
- Software and modules
- Python, R, MATLAB, and other applications
- GPU computing (TensorFlow, PyTorch)
- Containers (Singularity)
- Scientific software (AlphaFold, GROMACS, LAMMPS, Gaussian)
- Policies and best practices
- And more!

When answering questions:
1. Use the appropriate documentation tool to retrieve relevant information
2. Synthesize the information into a clear, helpful response
3. Include specific commands, paths, or examples from the documentation when relevant"""


# --- Streamlit App Configuration ---
st.set_page_config(
    page_title="RCC User Guide",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stDeployButton {display: none;}
    
    .cool-title {
        font-family: 'Courier New', monospace;
        font-size: 2.5rem;
        font-weight: bold;
        background: linear-gradient(90deg, #00d4ff, #0099cc, #00d4ff);
        background-size: 200% auto;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: shine 3s linear infinite;
        margin: 0;
        padding: 1rem 0;
    }
    
    @keyframes shine {
        to {background-position: 200% center;}
    }
    
    /* User message container - right aligned */
    .user-container {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 1.5rem;
    }
    
    .user-bubble {
        background: linear-gradient(135deg, #1a4d6e, #0d3347);
        color: #e0f0f8;
        padding: 12px 16px;
        border-radius: 14px 14px 4px 14px;
        font-size: 0.95rem;
        line-height: 1.5;
        max-width: 50%;
        min-width: 100px;
    }
    
    /* Assistant message spacing */
    .assistant-wrapper {
        margin-bottom: 1.5rem;
    }
    
    .tool-used {
        font-size: 0.8rem;
        color: #666;
        margin-bottom: 6px;
    }
    
    /* Add gap before chat input */
    .stChatInput {
        margin-top: 2rem !important;
    }
</style>
""", unsafe_allow_html=True)

# JavaScript for auto-focus on keypress
components.html("""
<script>
const doc = window.parent.document;

doc.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
        return;
    }
    if (e.ctrlKey || e.altKey || e.metaKey) {
        return;
    }
    const ignoreKeys = ['Escape', 'Tab', 'CapsLock', 'Shift', 'Control', 'Alt', 'Meta', 
                        'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
                        'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12'];
    if (ignoreKeys.includes(e.key)) {
        return;
    }
    
    const chatInput = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
    if (chatInput) {
        chatInput.focus();
    }
});
</script>
""", height=0)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "processing" not in st.session_state:
    st.session_state.processing = False
if "client" not in st.session_state:
    try:
        st.session_state.client = get_client()
    except Exception as e:
        st.error(f"Failed to initialize client: {e}")
        st.stop()


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
                    current_tool = {
                        "id": event.content_block.id,
                        "name": event.content_block.name,
                        "input": {}
                    }
                    current_tool_input = ""
            elif event.type == "content_block_delta":
                if hasattr(event.delta, 'type'):
                    if event.delta.type == "text_delta":
                        full_text += event.delta.text
                    elif event.delta.type == "input_json_delta":
                        if current_tool:
                            current_tool_input += event.delta.partial_json
            elif event.type == "content_block_stop":
                if current_tool:
                    try:
                        current_tool["input"] = json.loads(current_tool_input) if current_tool_input else {}
                    except json.JSONDecodeError:
                        current_tool["input"] = {}
                    tool_use_blocks.append(current_tool)
                    current_tool = None
                    current_tool_input = ""
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
            if hasattr(block, 'type'):
                if block.type == "text" and block.text:
                    texts.append(block.text)
            elif isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    texts.append(block["text"])
        return "\n".join(texts)
    return ""


def format_tool_names(tool_names):
    """Format tool names with counts."""
    if not tool_names:
        return ""
    tool_counts = {}
    for name in tool_names:
        # Make tool names more readable
        display_name = name.replace('read_', '').replace('_doc', '').replace('_', ' ').title()
        tool_counts[display_name] = tool_counts.get(display_name, 0) + 1
    parts = []
    for name, count in tool_counts.items():
        if count > 1:
            parts.append(f"{name} (×{count})")
        else:
            parts.append(name)
    return ", ".join(parts)


def render_user_message(content):
    """Render user message on the right with fixed width."""
    escaped = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    st.markdown(f'''
    <div class="user-container">
        <div class="user-bubble">{escaped}</div>
    </div>
    ''', unsafe_allow_html=True)


def render_assistant_message(content, tool_names=None):
    """Render assistant message using native chat_message for proper markdown."""
    st.markdown('<div class="assistant-wrapper">', unsafe_allow_html=True)
    with st.chat_message("assistant"):
        if tool_names:
            tools_str = format_tool_names(tool_names)
            st.caption(f"📚 Referenced: {tools_str}")
        st.markdown(content)
    st.markdown('</div>', unsafe_allow_html=True)


# Sidebar
with st.sidebar:
    st.markdown("## 📚 RCC User Guide")
    st.markdown("---")
    st.markdown("### About")
    st.markdown("AI assistant for UChicago's Midway Computing Clusters.")
    st.markdown("---")
    st.markdown("### Topics")
    st.markdown("""
    - 🔑 Accounts & Access
    - 🖥️ Connecting (SSH, ThinLinc, etc.)
    - ⚙️ Running Jobs (Slurm)
    - 💾 Storage & Quotas
    - 📦 Software & Modules
    - 🐍 Python, R, MATLAB
    - 🎮 GPU Computing
    - 🧬 Scientific Software
    """)
    st.markdown("---")
    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.session_state.processing = False
        st.rerun()

# Title
st.markdown('<h1 class="cool-title">RCC USER GUIDE</h1>', unsafe_allow_html=True)
st.markdown("---")

# Chat history - only display user prompts and final assistant responses
for message in st.session_state.messages:
    if message["role"] == "user" and isinstance(message["content"], str):
        render_user_message(message["content"])
    elif message["role"] == "assistant" and message.get("is_final"):
        display_text = extract_display_text(message["content"])
        tool_names = message.get("tool_names", [])
        if display_text:
            render_assistant_message(display_text, tool_names if tool_names else None)

# Chat input
prompt = st.chat_input("Ask me anything about RCC...", disabled=st.session_state.processing)

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.processing = True
    st.rerun()

# Process request
if st.session_state.processing:
    with st.spinner("Searching documentation..."):
        # Build API messages from session state
        api_messages = []
        for m in st.session_state.messages:
            api_messages.append({"role": m["role"], "content": m["content"]})
        
        try:
            stream = st.session_state.client.messages.stream(
                model=MODEL,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=api_messages,
                tools=TOOLS
            )
            response_text, tool_use_blocks, response = collect_stream_response(stream)
            all_tool_names = [tb["name"] for tb in tool_use_blocks]

            # Handle tool calls - keep looping until no more tools
            while tool_use_blocks:
                # Add to API messages only (not display)
                api_messages.append({"role": "assistant", "content": response.content})

                # Execute tools
                tool_results = []
                for tool_block in tool_use_blocks:
                    result = execute_tool(tool_block["name"], tool_block["input"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block["id"],
                        "content": result
                    })

                # Add tool results to API messages only
                api_messages.append({"role": "user", "content": tool_results})

                # Get next response
                stream = st.session_state.client.messages.stream(
                    model=MODEL,
                    max_tokens=8192,
                    system=SYSTEM_PROMPT,
                    messages=api_messages,
                    tools=TOOLS
                )
                response_text, tool_use_blocks, response = collect_stream_response(stream)
                all_tool_names.extend([tb["name"] for tb in tool_use_blocks])

            # Only add the FINAL assistant response to session state for display
            if response and response.content:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response.content,
                    "tool_names": all_tool_names,
                    "is_final": True
                })

        except Exception as e:
            st.error(f"Error: {e}")
            if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
                st.session_state.messages.pop()
        finally:
            st.session_state.processing = False
            st.rerun()

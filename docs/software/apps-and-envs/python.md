# Python 
## Distributions

Different versions of Python on Midway are offered as modules. Choosing the right Python distribution is essential for reproducibility, ease of use, and compatibility with Midway resources. The table below summarizes the main options and when to use each.

| Distribution                | Module Name/Version                 | Best for                        | Notes                                         |
|-----------------------------|-------------------------------------|----------------------------------|-----------------------------------------------|
| Standard Python | `python/3.11.9`, `python/3.8.0`, `python/2.7` (Midway3)<br>`python/3.9.18` (Midway2) | Most research, production, reproducibility | Minimal, clean installs. Use for scripts, pipelines, and most research. |
| Miniforge (conda/mamba)     | `python/miniforge-25.3.0` | Scientific computing, data science | Flexible, includes mamba for fast env/package management. |
| Anaconda                    | `python/anaconda-2022.05` (Midway3)<br>`python/anaconda3-2021.05` (Midway2) | Legacy, teaching, compatibility needs | Not recommended for research due to license restrictions and inode/storage issues. |

!!! tip "Quick advice:"
    - **Use Standard Python** for most research, scripting, and production workflows. It ensures a clean, reproducible environment.
    - **Use Miniforge** if you need many scientific/data science packages or want to manage environments with conda/mamba.
    - **Use Anaconda only if required** for teaching, legacy workflows, or compatibility needs. For research, prefer Standard Python or Miniforge.

!!! warning "Important: Anaconda Licensing and Inode Usage Issues"
    **Anaconda has implemented commercial license restrictions** for organizations with over 200 employees, affecting many academic institutions. Additionally, a full Anaconda installation can exceed 3GB in size and create over 100,000 small files, which quickly exhausts inode quotas. On Midway clusters, home directories typically have strict inode quotas (around 30,000), and a single Anaconda installation can consume most or all of this quota, preventing you from creating additional files.

**To see available versions:**
```bash
module avail python
```

**To load a module:**
```bash
module load python/3.11.9       # Standard Python (recommended)
module load python/miniforge-25.3.0  # Miniforge (conda/mamba)
```

- For most users, start with Standard Python. If you need conda-style environments or many scientific packages, switch to Miniforge.
- Both Standard Python and Miniforge are fully supported and optimized for Midway clusters.


!!! note "Why Miniforge over Anaconda?"
    Miniforge is strongly preferred over Anaconda for research computing on Midway clusters for several reasons:
    - **No license restrictions for any use**, unlike Anaconda's commercial restrictions
    - **Significantly fewer files and inodes** - Anaconda installations can exceed 3GB and create over 100,000 small files
    - **Smaller disk footprint** - Requires less storage space in your quota
    - **Faster package installation** with Mamba support
    - **Uses conda-forge by default** for more up-to-date scientific packages
    - **Better performance on HPC environments** with lower overhead

!!! warning "Managing Inode Usage with Conda Environments"
    If you use any conda-based distribution (Miniforge, Anaconda, etc.):
    
    1. Install environments in `/scratch/midway3/$USER/conda_envs` rather than your home directory
    2. Run `conda clean --all` regularly to remove unused package caches
    3. Limit the number of environments you create and maintain
    4. Use `df -i` to check your current inode usage
    5. Consider Python virtual environments (venv) for smaller projects

## Cache

### Conda/Mamba

By default, conda/mamba caches downloaded packages under `~/.conda/pkgs`, which can rapidly exhaust your home directory's inode and space quotas on shared systems.

Options to control the cache:

1. **Temporary cache (recommended on Midway)**
   - Minimizes inode usage; cache lives in a temporary location and is cleaned up automatically.
   - Our Python modules honor `USE_CONDA_CACHE=0` when set before loading the module.
   - Example:
     ```bash
     # Set before loading the Python module
     export USE_CONDA_CACHE=0
     module load python/miniforge-25.3.0
     ```

2. **Persistent cache (optional, for repeated installs)**
   - Keeps packages between sessions to speed up repeated environment solves/installs.
   - Set a cache directory in project or scratch space; avoid `$HOME`.
   - You can either set `USE_CONDA_CACHE=1` (module convenience; must be supported by the modulefile) and/or explicitly point conda to a path using `CONDA_PKGS_DIRS` or `.condarc`:
     ```bash
     # Choose a persistent location (recommended)
     export CONDA_PKGS_DIRS=/project/PI_NAME/USER/conda/pkgs   # or /scratch/midway3/$USER/conda/pkgs
     # Persist via conda config (optional)
     conda config --add pkgs_dirs /project/PI_NAME/USER/conda/pkgs
     conda config --show pkgs_dirs
     ```
   - If your modulefile supports the toggle, you can also do:
     ```bash
     export USE_CONDA_CACHE=1
     module load python/miniforge-25.3.0
     ```
   - Recommendation: Use project or scratch; do not keep caches in your home directory.
   - To Clean Unused Packages:
    ```bash
    mamba clean --all  # Remove unused package cache
    # or
    conda clean --all  
    ```

### UV

[UV](https://docs.astral.sh/uv/) is a modern, fast alternative to pip for package management (available on both Midway2 and Midway3):

```bash
# Load modules
module load python/miniforge-25.3.0  # or other Python version
module load uv

# Create virtual environment (faster than venv)
uv venv myenv

# Activate
source myenv/bin/activate

# Install packages (much faster than pip)
uv pip install numpy pandas
```

!!! note "UV cache: temporary vs persistent"
    - Temporary cache reduces inode usage and is a good default on shared clusters.
    - Persistent cache speeds up repeated installs across nodes/sessions. If you want this, either:
      - Use our module toggle `USE_UV_CACHE=1` before `module load uv` (if supported by the modulefile), or
      - Set an explicit path with `UV_CACHE_DIR` to project/scratch (preferred):
        ```bash
        export UV_CACHE_DIR=/project/PI_NAME/USER/uv/cache   # or /scratch/midway3/$USER/uv/cache
        ```
    - To minimize cache entirely for throwaway installs, you can disable caching:
      ```bash
      export UV_NO_CACHE=1
      ```
    - Note: `UV_NO_CACHE` is an official uv environment variable and does not require a modulefile. See: https://docs.astral.sh/uv/reference/environment/#uv_no_cache

!!! warning "Compiled packages on Midway2"
    On Midway2, packages with native extensions (e.g., NumPy/SciPy) may require a newer GCC toolchain (e.g., errors like "NumPy requires GCC >= 9.3"). If you encounter this, either load an appropriate GCC module before installing, or prefer installing these packages via conda/mamba environments instead of `uv pip`.

---

##  Environments
### Private
Suppose that you would like to install numpy, matplotlib and pandas for your calculations. You should first create an environment in your own space and install these packages into this environment.

Since Python environments might contain many files and/or take a lot space, it is recommended that you create your environments somewhere outside your home folder such as `/project` or `/scratch`. Suppose that your PI has a space under `/project/[pi-folder]` and you have a folder under that location.

```
cd /project/[pi-folder]/[your-cnetid]
python -m venv my-venv
source ./my-venv/bin/activate
pip install matplotlib numpy pandas
```

Note that the base environment of the default `python` module already has many popular packages installed, including the above 3 packages. You can also create an environment and install packages with `conda` or `mamba`.

=== "Midway2"
    Store environments in project space, not home directory:
    ```bash
    # Create environment in project space
    conda create -p /project2/PI_NAME/USER/envs/myenv python=3.9
    ln -s /project2/PI_NAME/USER/envs/myenv ~/.conda/envs/myenv
    source activate myenv

    # Or with uv (recommended for faster creation)
    module load uv
    cd /project2/PI_NAME/USER/envs
    uv venv myenv
    source /project2/PI_NAME/USER/envs/myenv/bin/activate
    ```

=== "Midway3"
    Store environments in project space, not home directory:
    ```bash
    # Create environment in project space
    conda create -p /project/PI_NAME/USER/envs/myenv python=3.11
    ln -s /project/PI_NAME/USER/envs/myenv ~/.conda/envs/myenv
    source activate myenv

    # Or with uv (recommended for faster creation)
    module load uv
    cd /project/PI_NAME/USER/envs
    uv venv myenv
    source /project/PI_NAME/USER/envs/myenv/bin/activate
    ```
Alternatively, you can use `export CONDA_ENVS_PATH=/project/PI_NAME/USER/envs:$CONDA_ENVS_PATH` to let conda know where to search for your virtual environment. 

To backup an environment to a YAML file:
```bash
# Minimal spec (portable): only packages you explicitly installed
conda env export --from-history > environment.yml
# Full lockfile (exact builds; best reproducibility on the same platform)
conda env export > environment-full.yml
# For uv environments
uv pip freeze > requirements.txt
```

To recreate from a YAML file:
```bash
# Using minimal spec (resolver may choose newer builds)
conda env create --prefix=/path/to/new/environment -f environment.yml

# Using full lockfile (recreate exact builds when available)
conda env create --prefix=/path/to/new/environment -f environment-full.yml
```
Once your environment is set up how you want, especially if it is in your scratch space, you may want
to create a backup of the environment into a YAML file. You do that after activating the environment
with `conda env export > environment.yml`. That YAML file can then be used to recreate the environment
with `conda env create --prefix=/path/to/new/environment -f environment.yml`.

!!! note
    Anaconda may sometimes cause issues with ThinLinc. If you are experiencing frequent, spontaneous disconnections from ThinLinc, remove any sections involving "conda" or "anaconda" from the file `~/.bashrc` (in your home directory).

### Shared
Once you load a Python distribution, you can list all available public environments with:
```bash
conda env list  
```
To activate an environment, run:
```
source activate <ENV NAME>
```
where `<ENV NAME>` is the name of the environment for a public environment,
or the full path to the environment, if you are using a personal one. You can deactivate an environment
with:
 ```
 conda deactivate
 ```

!!! danger

!!! tip "Why use `source activate` instead of `conda activate` (or `mamba activate`)?"
    **`conda activate`/`mamba activate` require `conda init`**, which edits your shell startup files (e.g., `~/.bashrc`, `~/.bash_profile`). Those edits can interfere with the module environment, non-interactive shells (batch jobs), and remote desktop sessions, and generally degrade the user experience on Midway. Using `source activate` (with the full env path or a symlinked name) avoids modifying startup files and works reliably across login, batch, and ThinLinc sessions.

!!! danger "Do not run `conda init`"
    Never run `conda init` on Midway. It modifies your shell startup scripts and can break module behavior, non-interactive shells, and ThinLinc sessions. Use `source activate` instead of `conda activate`.

With each Anaconda distribution, we have a small selection of widely used environments. Many, such as
Tensorflow or DeepLabCut should be loaded through their modules (i.e., `module load tensorflow`), which automate the loading of other
relevant libraries that are available as modules.

The `python/miniforge-25.3.0` module comes with several pre-configured domain-specific environments. Each environment is optimized for a specific research domain. Here’s a quick comparison:

| Environment | Activation command      | Best for                        | Core packages / Tools                           |
|-------------|------------------------|----------------------------------|-------------------------------------------------|
| sci         | `source activate sci`  | Scientific computing, data analysis | numpy, scipy, pandas, matplotlib, seaborn, scikit-learn, JupyterLab, ipython, h5py, psutil |
| ml          | `source activate ml`   | Deep learning, ML research       | tensorflow, pytorch, scikit-learn, keras, xgboost, lightgbm, matplotlib, seaborn           |
| bio         | `source activate bio`  | Genomics, bioinformatics         | biopython, samtools, bcftools, bedtools, fastqc, cutadapt, multiqc, pandas, scikit-bio     |
| geo         | `source activate geo`  | GIS, earth science               | gdal, rasterio, geopandas, cartopy, xarray, netcdf4, matplotlib, pyproj                    |
| hpc         | `source activate hpc`  | Parallel/distributed computing   | mpi4py, dask, dask-jobqueue, joblib, ipyparallel, numpy, pandas                            |

All environments include:
- Python 3.x
- Mamba for fast package management
- Pip for additional package installation
- Common development tools

!!! tip "Choosing your environment"
    Select the environment that matches your research domain to get started quickly. You can always install extra packages or create a custom environment based on these templates.


    
## Notebooks
### Jupyter

Jupyter Notebook is a useful tool for python users because it provides
interactive web-based computing. JupyterLab is the next-generation IDE-like counterpart of Jupyter Notebook with more advanced features for data science, scientific computing, computational journalism, and machine learning. It has a modular structure that allows you to create and execute multiple documents in different tabs in the same window.

You can launch Jupyter Notebooks on Midway, open it in the browser on your local machine and have all the computation work done on Midway. If you want to perform heavy compute, you will need to start an [interactive session](../../slurm/sinteractive.md) before launching Jupyter notebook, otherwise you may use one of the login nodes:

**Step 1**: Load the desired Python module. This can be done on a login node, or on a compute node via an interactive job or a batch job.

**Step 2**: Determine the IP address of the host you are on. Whether you are on a login node or a compute node,
you can use this command to get your IP address:

```
HOST_IP=`/sbin/ip route get 8.8.8.8 | awk '{print $7;exit}'`
echo $HOST_IP
```
which can be either `128.135.x.y` (an external address), or `10.50.x.y` (on-campus address).

**Step 3**: Launch Jupyter with:

=== "Midway2"
    ```
    jupyter-notebook --no-browser --ip=$HOST_IP --port=15021
    ```
    or
    ```
    jupyter-lab --no-browser --ip=$HOST_IP --port=15021
    ```
=== "Midway3"
    ```
    jupyter-notebook --no-browser --ip=$HOST_IP --port=15021
    ```
    or
    ```
    jupyter-lab --no-browser --ip=$HOST_IP --port=15021
    ```

where 15021 is an arbitrary port number rather than 8888. If there is a problem with the port already in use, your browser will complain. In that case, please try the another port with the flag `--port=<port number>`, or use the command `shuf`  to get a random number for the port:
```
PORT_NUM=$(shuf -i15001-30000 -n1)
```
and launch the Notebook server as earlier
```
jupyter-notebook --no-browser --ip=$HOST_IP --port=$PORT_NUM
```

which will give you two URLs with a token, one with the external address `128.135.x.y`, and another with the on-campus address `10.50.x.y`, or  with your local host `127.0.0.*`.  The on-campus address `10.50.x.y` is only valid when you are connecting to Midway2 or Midway3 via VPN. The URLs would be something like

```default
http://128.135.167.77:15021/?token=9c9b7fb3885a5b6896c959c8a945773b8860c6e2e0bad629
```
or
```default
http://10.50.260.16:15021/?token=9c9b7fb3885a5b6896c959c8a945773b8860c6e2e0bad629
```
or
```default
http://127.0.0.1:15021/?token=9c9b7fb3885a5b6896c959c8a945773b8860c6e2e0bad629
```

If you launch Jupyter Notebook on a compute node, the URLs with `10.50.x.y` and `127.0.0.1` are likely to be returned.

If you do not specify `--no-browser --ip=`, the web browser will be launched on the node and the URL returned cannot be used on your local machine.

Steps 1 through 3 can be done with a batch job as well. An example job script for launching Jupyter Notebook is given as below.

```
#!/bin/bash
#SBATCH --job-name=jupyter-launch
#SBATCH --account=pi-[cnetid]
#SBATCH --output=output-%J.txt
#SBATCH --error=error-%J.txt
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=8GB

module load python/anaconda-2021.05

cd $SLURM_SUBMIT_DIR

HOST_IP=`/sbin/ip route get 8.8.8.8 | awk '{print $7;exit}'`
PORT_NUM=$(shuf -i15001-30000 -n1)
jupyter-notebook --no-browser --ip=$HOST_IP --port=$PORT_NUM
```

After submitting the job script and the job gets running with a job ID assigned, you can check the output log `output-[jobID].txt` to obtain the URLs.

**Step 4**: Open a web browser on your local machine with the returned URLs.

If you are using on-campus network or VPN, you can copy-paste (or `Ctrl` + click) the URL with the external address, or the URL with the on-campus address into the browser's address bar.

Without VPN, you need to use SSH tunneling to connect to the Jupyter server launched on the Midway2 (or Midway3) login or compute nodes in Step 3 from your local machine. To do that, open another terminal window on your local machine and run

```
ssh -N -f -L 15021:<HOST_IP>:15021 <your-CNetID>@midway3.rcc.uchicago.edu
```
where `HOST_IP` is the external IP address of the login node obtained from Step 2, and 15021 is the port number used in Step 3.

This command will create an SSH connection from your local machine to Midway login or compute nodes and forward the 15021 port to your local host at port 15021. The port number should be consistent across all the steps (15021 in this example). You can find out the meaning for the arguments used in this command at [explainshell.com](https://explainshell.com){:target='_blank'}.

After successfully logging with 2FA as usual, you will be able to open the URL `http://127.0.0.1:15021/?token=....`, or equivalently, `localhost:15021/?token=....` in the browser on your local machine.

**Step 5**: To kill Jupyter, go back to the first terminal window where you launch Jupyter Notebook
and press `Ctrl+c` and then confirm with `y` that you want to stop it.






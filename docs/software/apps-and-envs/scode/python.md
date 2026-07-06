# Configuring Python for **`scode`**

This companion guide explains how to get a rock‑solid Python workflow inside a VS Code Web session launched with **scode**. You’ll learn:

1. Which VS Code extensions to install (and how to install them in one shot).
2. How to load Python (and any supporting toolchains like CUDA or Java) before the server starts so they’re visible to both VS Code integrated terminals and Jupyter kernels.
3. How the VS Code Python extension discovers interpreters, and what that means for:
    * plain `.py` files, and
    * Jupyter notebooks.
4. Tips for refreshing kernels and troubleshooting interpreter‑detection quirks.

---

## 🚀 Quick Start

```bash
# On the login node
module load scode   # activate scode
scode ext install ms-python.python ms-toolsai.jupyter # Install essential extensions

# Launch a 2‑hour session with 16 GB RAM and pre‑loaded Anaconda
# Remove Anaconda module loading if you already have it loaded in your ~/.bashrc
scode serve-web \
  --setup-command "module load python/anaconda-2023.09 && source activate base" \
  -- --account <pi-account> --time 02:00:00 --mem 16G
```

---

## 1  Installing Python Extensions

Run this **on the login node** *after* `module load scode` but *before* launching the server.

```bash
scode ext install ms-python.python ms-toolsai.jupyter
```

These extensions provide essential support for Python development and interactive notebooks:

* [`ms-python.python`](https://marketplace.visualstudio.com/items?itemName=ms-python.python) adds language features like IntelliSense, linting, debugging, and environment management for Python.
* [`ms-toolsai.jupyter`](https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter) enables support for running Jupyter notebooks within the editor, including code execution and rich outputs.

More extensions be found on the [VS Code Extension Marketplace](https://marketplace.visualstudio.com/vscode).

Extensions are cached in `~/.scode/envs/stable/<env>/extensions/` by default, so subsequent sessions will start with the extensions you have previously installed.

Make sure to periodically run `scode ext update` to keep your extensions up to date.

---

## 2  Environment Setup & Tips

Jupyter kernels started within VS Code Web inherits the shell environment of the VS Code Server. So it is recommended to have the Python environment configured before starting the VS Code server with `scode`.

Two reliable patterns keep Python (and friends like CUDA or Java) on the PATH for both VS Code integrated terminals and Jupyter kernels:

### 2.1  Persistent Environment Setup via `~/.bashrc` (Recommended)

Add your module‑load and activation commands to `~/.bashrc` so they run for **every** interactive shell (including `scode` jobs):

```bash
# ~/.bashrc
module load python/anaconda-2023.09

# Optional extras your notebooks might need:
module load cuda/12.6
module load java/17.0.10 # Required by PyArrow

# Conda base env on PATH so VS Code sees *all* `conda env list` interpreters
source activate base
```

### 2.2  Per‑job Tweaks with `--setup-command`

If you need occasional, per‑session tweaks without touching your `~/.bashrc`, pass a setup command directly to `scode`:

```bash
scode serve-web \
  --setup-command "module load python/anaconda-2023.09 && source activate base" \
  -- --account <pi-account> --time 01:00:00 --mem 16G
```

This runs **just before** the VS Code Server starts, ensuring both the server and any kernels it spawns see the right environment.

!!! question "Why so early?"

    Jupyter kernels are spawned as subprocesses of the VS Code server. If you load modules **after** the server starts, kernels *won’t* inherit them. We have to restart the server (the whole job) to pick up changes.

---

## 3  Choosing An Interpreter (and How VS Code Finds Them)

According to Microsoft’s [search order](https://code.visualstudio.com/docs/python/environments#_where-the-extension-looks-for-environments), the Python extension probes these locations **on the server host**:

| Search location                                                                                     | Typical Midway scenarios                         | Make sure…                                                             |
| --------------------------------------------------------------------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------- |
| **Virtual envs in the workspace or `$HOME`** <br/> (created via `python -m venv venv`, `pipenv`, etc.) | Project‑specific venv under your repo <br/> Venvs created in `/scratch` and symlinked under `$HOME`           | The folder contains `bin/python` and lives inside the workspace or `$HOME` |
| **Conda envs from `conda env list`**                                                                | Anaconda module on Midway (`python/anaconda-*`) | You loaded the module **and** activated `base`, so `conda` is on PATH  |
| **Sub‑folders of `python.venvPath`**                                                                | Central directory of many virtual envs          | Set `"python.venvPath": "/path/to/venvs"` in **Settings (JSON)**     |

### 3.1  Plain `.py` Files

**VS Code Command Palette (`Ctrl+Shift+P`)** → **Python: Select Interpreter** → pick any interpreter the VS Code Python extension found (or browse to one).

You can also click and open the interpreter selector in the far-right corner of the bottom status bar when a `.py` file is opened.

See [Microsoft VS Code Python documentation](https://code.visualstudio.com/docs/python/environments#_working-with-python-interpreters) for detailed instructions on selecting Python interpreters for `.py` files.

### 3.2  Jupyter Notebooks

The kernel‑picker lists only interpreters VS Code already knows about. You **can’t** type an arbitrary path. Ensure the desired venv/Conda env is discoverable according to the [table above](#3choosing-an-interpreter-and-how-vscode-finds-them) *before* opening the notebook, then choose it in the top‑right **Select Kernel** dropdown.

---

## 4  Refreshing Environments & Kernels

### 4.1  Running `.py` in Integrated Terminals

Changes to your shell environment (e.g., your `~/.bashrc`) are picked up by **newly reopened** integrated terminals immediately. There's no need to restart the VS Code Server.

| **Change you made**                                   | **What to do...**                             |
| ----------------------------------------------------- | ------------------------------------------------------------- |
| Edited `~/.bashrc` or added `module load …` lines     | Run `source ~/.bashrc`, or reopen a terminal tab to get the updated environment         |
| Created a new venv/Conda env *inside the running job* | Activate it in the terminal (e.g. `source venv/bin/activate`) |
| Installed new Python packages into the active env     | Ready to use immediately                                      |

### 4.2  Jupyter Notebooks

Notebook kernels are spawned by the VS Code Server process and inherit its environment at startup. To pick up environment changes such as an updated `~/.bashrc`, you must either refresh VS Code’s environment list or restart the entire server job.

| **Change you made**                                   | **What to do...**                                      |
| ----------------------------------------------------- | ----------------------------------------------------------------- |
| Edited `~/.bashrc` or added `module load …` lines     | Terminate the VS Code Server job (`scancel …`) and relaunch       |
| Created a new venv/Conda env *inside the running job* | **Python: Refresh Environment List** or reload the VS Code window |
| Installed new Python packages into the active env     | Restart the notebook kernel                    |

---

## 5  Troubleshooting

1. **Why is my Python version not listed?**

    * Run `which python` in an integrated terminal: is it the one you expect?
    * Check that the venv contains a `bin/python` and isn’t empty.
    * Verify `conda env list` shows your env (if using Conda).

2. **Notebook kernel stuck on “Starting”?**

    * The env might miss `ipykernel`; run `python -m pip install ipykernel`.
    * Double‑check that the env’s `python` is executable on the compute node.

3. **Modules (e.g., CUDA) missing inside notebook but present in terminal?**

    * You probably loaded them *after* launching the server. Pre‑load in `~/.bashrc` and restart the job.

4. **Still lost?**

    * View VS Code’s **Python** and **Jupyter** output channels (`⌘/Ctrl+Shift +U`).
    * Refer to the [Microsoft VS Code Python documentation](https://code.visualstudio.com/docs/python/python-quick-start) for more details.

# Python and Anaconda

## Getting Started

Different versions of Python on Midway are offered as modules. To check the full list of Python modules
use the `module avail python` command.

The command `module load python` will load the default module: an Anaconda distribution
of Python. Note that there are multiple different Anaconda distributions available.  

Once you load an Anaconda distribution, you can list all available public environments with:
```
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

    Never run `conda init`! Use `source activate` instead of `conda activate`**.**
    `conda init` has been known to break ThinLinc.

## Managing Environments

With each Anaconda distribution, we have a small selection of widely used environments. Many, such as
Tensorflow or DeepLabCut should be loaded through their modules (i.e., `module load tensorflow`), which automate the loading of other
relevant libraries that are available as modules.

If you need packages not available in the global environment, you can make a personal environment for
them. If you want to copy an existing environment to modify it, you can do that with:
```
conda create --prefix=/path/to/new/environment --clone <EXISTING ENVIRONMENT>
``` 
If you want to make a clean environment, you can do that with
```
conda create --prefix=/path/to/new/environment python=<PYTHON VERSION NUMBER>
```

Once your environment is set up how you want, especially if it is in your scratch space, you may want
to create a backup of the environment into a YAML file. You do that after activating the environment
with `conda env export > environment.yml`. That YAML file can then be used to recreate the environment
with `conda env create --prefix=/path/to/new/environment -f environment.yml`.

!!! note
    Anaconda may sometimes cause issues with ThinLinc. If you are experiencing frequent, spontaneous disconnections from ThinLinc, remove any sections involving "conda" or "anaconda" from the file `~/.bashrc` (in your home directory).
    
## Managing Packages

In the Anaconda distributions of Python, you should generally be using a personal environment to manage
packages. Once you activate your environment
```
source activate [your-env]
```
you can install packages with `conda install` or `pip install` into this environment. As per the advice of the Anaconda software authors, any  `pip install` packages should be installed after `conda install` packages.


## Using Python

On Midway, `python` can be launched, after loading a desired module, at the terminal with the command:

```default
python
```

To leave the launched interactive shell, use:

```default
exit()
```
or
```default
quit()
```

If you already have a python script, use this command to run it:

```default
python your_script.py
```

### Python Interactive Plotting

For interactive plotting, it is necessary to set the matplotlib backend to a
graphical backend. Here is an example:

```python
#!/usr/bin/env python

import matplotlib
matplotlib.use('Qt4Agg')
import matplotlib.pyplot as plt

plt.plot([1,2,3,4])
plt.ylabel('some numbers')
plt.show()
```

If you are saving files and viewing them with the *display* command, you may
experience rapid flickering. There seems to be an issue with image
transparency, use a command like this to disable the transparency:

```default
display -alpha off <image>
```

## Running Jupyter Notebooks

Jupyter Notebook is a useful tool for python users because it provides
interactive web-based computing. You can launch Jupyter Notebooks on Midway, open it in the
browser on your local machine and have all the computation work done
on Midway. If you want to perform heavy compute, you will need to start an [interactive session](../../slurm/sinteractive.md) before launching Jupyter notebook, otherwise you may use one of the login nodes.

The steps to launch Jupyter are as follows:

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
    jupyter-notebook --no-browser --ip=$HOST_IP
    ```
    or
    ```
    jupyter-lab --no-browser --ip=$HOST_IP
    ```
===+ "Midway3"
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
!/bin/bash
#SBATCH --job-name=jupyter-launch
#SBATCH --account=pi-[cnetid]
#SBATCH --output=output-%J.txt
#SBATCH --error=error-%J.txt
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --memb=8GB

module load python/anaconda-2021.05

cd $SLURM_SUBMIT_DIR

HOST_IP=`/sbin/ip route get 8.8.8.8 | awk '{print $7;exit}'`
PORT_NUM=$(shuf -i15001-30000 -n1)
jupyter-notebook --no-browser --ip=$HOST_IP --port=$PORT_NUM
```

After submitting the job script and the job gets running with a job ID assigned, you can check the output log `output-[jobID].txt` to obtain the URLs.

**Step 4**: Open a web browser on your local machine with the returned URLs.

If you are using on-campus network or VPN, you can use copy and paste (or `Ctrl` + mouse click on) the URL with the external address, or the URL with the on-campus address into the address bar.

Without VPN, you need to use SSH tunneling to connect to the Jupyter server launched on the Midway2 (or Midway3) login or compute nodes in Step 3 from your local machine. To do that, open another terminal window on your local machine and run

```
ssh -N -f -L 15021:<HOST_IP>:15021 <your-CNetID>@midway3.rcc.uchicago.edu
```
where `HOST_IP` is the external IP address of the login node obtained from Step 2, and 15021 is the port number used in Step 3.

This command will create an SSH connection from your local machine to Midway login or compute nodes and forward the 15021 port to your local host at port 15021. The port number should be consistent across all the steps (15021 in this example). You can find out the meaning for the arguments used in this command at [explainshell.com](https://explainshell.com){:target='_blank'}.

After successfully logging with 2FA as usual, you will be able to open the URL `http://127.0.0.1:15021/?token=....`, or equivalently, `localhost:15021/?token=....` in the browser on your local machine.

**Step 5**: To kill Jupyter, go back to the first terminal window where you launch Jupyter Notebook
and press `Ctrl+c` and then confirm with `y` that you want to stop it.


## Running JupyterLab

JupyterLab is the next-generation IDE-like counterpart of Jupyter Notebook with more advanced features for data science, scientific computing, computational journalism, and machine learning. It has a modular structure that allows you to create and execute multiple documents in different tabs in the same window.


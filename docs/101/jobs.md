## Running jobs on the compute nodes

See [Running Jobs on Midway](../slurm/main.md) for detailed documentation on how to run your own programs on the cluster once you've connected. In this tutorial, we will try interactive session and submit a batch job.

Before running any job, you need to check if your account has any eligible allocations:

```
rcchelp balance
```

If you don't have any PI account, or if the balance column has negative numbers, then you cannot run any jobs on the shared partitions on Midway3. More on allocations can be found at [Allocations](../101/allocations.md).

### Interactive session

On the Midway3 login node, request an interactive node with 8 CPU cores:

```
sinteractive -A [pi-account] -p caslake -N 1 --ntasks-per-node=8
```

which will take a while to get you a compute node. This is because the `sinteractive` command essentially invokes the Slurm command `salloc` with the requested resource, and waits for the Slurm manager to return the resource. If successful, you will see an empty screen with the command prompt `[your-cnetid]@midway3-0xyz`, indicating that you are on the compute node node `midway3-0xyz`.

You can load python as you did on the login node:
```
module load python
```

and run `python`

```
[your-cnetid@midway3-0xyz ] python
Python 3.9.19 | packaged by conda-forge | (main, Mar 20 2024, 12:50:21) 
[GCC 12.3.0] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>>
```

After quitting `python`, you can activate the environment you created, and list the installed packages

```
source /project/[pi-folder]/[your-cnetid]/my-venv/bin/activate
pip list
```
You should see `numpy`, `matplotlib` and `pandas` installed in this environment.

Let us prepare a simple Python script, namely, `simple.py` with a text editor like `nano`, in the current folder, with the following content:

```
import numpy as np
from matplotlib import pyplot as plt 
x = np.arange(1,11) 
y = 2 * x + 5 
plt.title("Matplotlib demo") 
plt.xlabel("x axis caption") 
plt.ylabel("y axis caption") 
plt.plot(x,y)
plt.savefig("output.pdf", format="pdf")
```
And run it with 

```
python simple.py
```

which should produce a file `output.pdf`.

Change to the input data folder
```
cd /project/[pi-folder]/[your-cnetid]/lammps/examples
```

Load the same modules you used to build LAMMPS (except `cmake`)

```
module load mpich/3.4.3+gcc-10.2.0 mkl/2023.1
```

Relax the locked memory limit
```
ulimit -l unlimited
```

Run the LAMMPS binary you built above
```
mpirun -np 8 /project/[pi-folder]/[your-cnetid]/lammps/build/lmp -in melt/in.melt
```

The run will produce the LAMMPS screen output and a file named `log.lammps` in the current folder.

To terminate the interactive session, run

```
exit
```

You will get back to the login node.

### Batch jobs

Next, let us run the same calculations in the batch mode. First, create a text file with `nano` or `vi` on the login node, namely, `batch_job_python.txt`

```
#!/bin/bash
#SBATCH --job-name=job-info
#SBATCH --account=[pi-account]
#SBATCH --partition=caslake
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
cd /project/[pi-folder]/[your-cnetid]/
source my-venv/bin/activate
python simple.py
```

Next, submit the job to Slurm
```
sbatch batch_job_python.txt
```

Check your submitted job in the queue with

```
squeue -u $USER
```

Next, to test a run with LAMMPS in the batch mode, create another text file with `nano` or `vi` on the login node, namely, `batch_job_lammps.txt`

```
#!/bin/bash
#SBATCH --job-name=job-info
#SBATCH --account=[pi-account]
#SBATCH --partition=caslake
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
cd /project/[pi-folder]/[your-cnetid]/lammps/examples
module load mpich/3.4.3+gcc-10.2.0 mkl/2023.1
ulimit -l unlimited
n=$(( SLURM_NNODES * SLURM_NTASKS_PER_NODE ))
mpirun -np $n /project/[pi-folder]/[your-cnetid]/lammps/build/lmp -in melt/in.melt
```

After saving the file (Ctrl+X with `nano`, `:x` with `vi`), you will submit the script to Slurm:

```
sbatch batch_job_lammps.txt
```

As you can see, you can submit more than one jobs at a time. The more resource you request (number of nodes, number of tasks per node, memory per node, walltime and so on), the longer the jobs are pending.  Your usage history also affects how soon your jobs get running.  See [Running Jobs on Midway](../slurm/main.md) for detailed documentation on how to monitor the submitted jobs.

You can check the generated output `output.pdf` and `log.lammps` in the corresponding directories.


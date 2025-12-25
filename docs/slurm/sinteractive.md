# Interactive jobs
Interactive jobs are the most intuitive way to use RCC clusters, as they allow you to interact with the program running on compute node/s (e.g., execute cells in a Jupyter Notebook) in real-time. This is great for exploratory work or troubleshooting. An interactive job will persist until you disconnect from the compute node or until you reach the maximum requested time.  

To request an interactive job with default parameters, run the following command while connected to a login node:  

=== "Midway2"
    ```
    sinteractive
    ```
===+ "Midway3"
    ```
    sinteractive --account=pi-<PI CNETID>
    ```

!!! note
    On Midway3, you **always** need to specify the account to be charged for the job explicitly. Slurm will use the default [partition](../partitions.md) (Midway2: `broadwl`, Midway3: `caslake`) if you do not specify it.

!!! note
    On Midway3, to use the partitions with AMD CPUs, it is recommended that you log in to the `midway3-amd.rcc.uchicago.edu` login node and submit jobs from this login node. 

As soon as the requested resources become available, `sinteractive` will do the following: 
 
1. Log in to the compute node/s in the requested partition.  
2. Change into the directory you were working in.  
3. Set up X11 forwarding for displaying graphics.  
4. Transfer your shell environment, including any previously loaded modules.  

!!! note 
	By default, an interactive session times out after ***2 hours***. If you would like more than 2 hours, include a `--time=HH:MM:SS` flag to specify the necessary amount of time. 
	
For example, to request an interactive session for 6 hours, run the following command:

=== "Midway2"
    ```
    sinteractive --time=06:00:00
    ```
===+ "Midway3"
    ```
    sinteractive --account=pi-<PI's CNETID> --time=06:00:00
    ```

There are many additional options for the sinteractive command, including options to select the number of nodes, the number of cores per node, the amount of memory, and so on. For example, to request exclusive use of two compute nodes on the default CPU partition for 8 hours, enter the following:

=== "Midway2"
    ```
    sinteractive --exclusive --partition=broadwl --nodes=2 --time=08:00:00
    ```
===+ "Midway3"
    ```
    sinteractive --account=pi-<PI's CNETID> --exclusive --partition=caslake --nodes=2 --time=08:00:00
    ```
For more details about these and other useful parameters, check [Slurm `sbatch` page](./sbatch.md).

!!! tip
    All options in the `sbatch` command are also available for the `sinteractive` command. 

### Debug QoS 
There is a debug QOS (Quality of Service) setup to help users quickly access some resources to debug or test their code before submitting their jobs to the main partition. The debug QoS will allow you to run one job and get up to four cores for 15 minutes without consuming SUs. To use the debug QoS, specify `--time` as 15 minutes or less. For example, to get two cores for 15 minutes, you could run:

```
sinteractive --qos=debug --time=00:15:00 --ntasks=2 --account=pi-<PI CNETID>
```
You can find out the available `qos` for your account with the command `rcchelp`

```
rcchelp qos
```

Additionally, it is important to use the `--mem` or `--mem-per-cpu` options. For example, to request 8 CPU cores and 128 GB of memory on a bigmem2 node, add the following to your `.sbatch` script:

```bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
```

These same options can also be used to set up a sinteractive session. For example, on Midway3 to access a `bigmem` node with 1 CPU and 128 GB of memory, run: 

```bash
sinteractive --partition=bigmem --ntasks=1 --cpus-per-task=8 --mem=128G --account=pi-<PI CNETID>
```

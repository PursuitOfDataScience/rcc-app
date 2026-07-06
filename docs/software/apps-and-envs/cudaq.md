# CUDA-Q

[CUDA-Q](https://nvidia.github.io/cuda-quantum/latest/index.html) is a software development kit for quantum computing from NVIDIA. Additional training materials can also be found at [CUDA-Q Academic](https://github.com/NVIDIA/cuda-q-academic).

CUDA-Q is available in Midway3 as a Singularity file (which has both the C++ version and the Python version) and also as a separate Python environment via the software module `cudaq`. As with other software packages, when using CUDA-Q for computation, the compute nodes should be used, which could be accessed via interactive sessions or batch jobs.

The path to the Singularity file and the Python environment can be obtained from the module details via the following command.

```default
module show cudaq
```
The Python environment is available at `CUDAQ_ENV` and the Singularity file at `CUDAQ_SIF`. The Python environment could be activated using `source $CUDAQ_ENV` after loading the module `module load cudaq/`.

To use the Singularity file for CUDA-Q, you can load the Singularity module, using `module load singularity/`. And then to use CUDA-Q, you could either use the Singularity shell or execute the program directly. Instructions on using Singularity in Midway3, can be found at [this page](https://docs.rcc.uchicago.edu/software/apps-and-envs/singularity/).

For the first approach, you can launch the Singularity shell using`singularity shell $CUDAQ_SIF`, and then run the Python program e.g., using `python example_program.py` or the C++ program by compiling the code first, e.g., using `nvq++ example_program.cpp -o example.out`, followed by the execution e.g., using `./example.out`. 

For the second approach, you could execute Python or C++ program using the `exec` command, e.g., using `singularity exec $CUDAQ_SIF python example_program.py > example_output.txt`, for the case of Python.

When using the NVIDIA GPU resources, you can use the `--nv` option with the singularity file e.g., when launching the Singularity shell, use `singularity shell --nv $CUDAQ_SIF`. An example batch script for running CUDA-Q jobs on GPU nodes is given below.

```default
#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:1
#SBATCH --account=pi-cnetid
#SBATCH --time=01:00:00
#SBATCH --partition=gpu
#SBATCH --job-name=cudaq_job
#SBATCH --output=output-%J.txt
#SBATCH --error=error-%J.txt

module load singularity/
module load cudaq/

# Run the Python program using CUDA-Q in the Singularity file
singularity exec --nv $CUDAQ_SIF python my_quantum_program.py
```

# OpenMM

[OpenMM](https://openmm.org/) is a open-source high-performance toolkit for molecular simulation. You can use it as an application, a library, or a flexible programming environment.

Keywords: `biology`, `physics`, `chemistry`, `molecular dynamics`


## Available modules
There are several OpenMM modules on Midway3 that you can check via `module avail opemm`:

===+ "Midway3"
    ```
    ---------------------------- /software/modulefiles -----------------------------
    openmm/7.5.1(default)  openmm/8.1.0

    ```

???+ note
    OpenMM is under active development. You are encouraged to build the latest stable version from [source code](https://github.com/openmm/openmm) in your own space using the provided [compilers](../compilers.md).

???+ note
    You can also install OpenMM into your conda environment. See http://docs.openmm.org/7.0.0/userguide/application.html for more information
    ```
    module load python/anaconda-2022.05
    conda create -n your-env python=3.8
    source activate your-env
    conda install -c conda-forge openmm cudatoolkit=11.5
    ```

The OpenMM documentation contain useful information for improving performance of your specific calculations:

https://openmm.org/documentation


## Example job script

An example batch script to run OpenMM for Midway3 is given as below
```
!/bin/bash
#SBATCH --job-name=openmm-bench
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --constraint=v100
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1

module load openmm

cd $SLURM_SUBMIT_DIR

ntasks_per_node=$SLURM_NTASKS_PER_NODE
numnodes=$SLURM_JOB_NUM_NODES
n=$(( ntasks_per_node * numnodes ))

t=1000

python run_openmm.py
```
where `run_openmm.py` is a python script that sets up the system.

Example python scripts can be found at https://github.com/openmm/openmm/blob/master/examples/. Below is an example script that reads in a protein PDB structure, selects a force field, defines a system, specifies a time integrator, performs energy minimization, sets up the output log and snapshots and finally runs the MD simulation. You can use this script as `run_openmm.py` in the job script above.

```
from openmm.app import *
from openmm import *
from openmm.unit import *
from sys import stdout

pdb = PDBFile('input.pdb')
forcefield = ForceField('amber14-all.xml', 'amber14/tip3pfb.xml')
system = forcefield.createSystem(pdb.topology, nonbondedMethod=PME, nonbondedCutoff=1*nanometer, constraints=HBonds)
integrator = LangevinMiddleIntegrator(300*kelvin, 1/picosecond, 0.004*picoseconds)
simulation = Simulation(pdb.topology, system, integrator)
simulation.context.setPositions(pdb.positions)
simulation.minimizeEnergy()
simulation.reporters.append(PDBReporter('output.pdb', 1000))
simulation.reporters.append(StateDataReporter(stdout, 1000, step=True, potentialEnergy=True, temperature=True))
simulation.step(10000)
```

<!---
There are two different primary configurations:

* **gromacs-X.Y.Z** is single precision (float)

* **gromacs-plumed-X.Y.Z+<compiler module>** is double precision, compiled with the stated compiler and MPI code, with PLUMED and Reconnaissance Metadynamics

`gromacs.sbatch` demonstrates how to run a short Gromacs job (the d.dppc test
case) in parallel.  Submit to the queue by:

```bash
cd $HOME/rcchelp/software/gromacs.rcc-docs
sbatch gromacs.sbatch
# and / or
sbatch gromacs-plumed.sbatch
```

The submission scripts can be modified to suit your needs
--->


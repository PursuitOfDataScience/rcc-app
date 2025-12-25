# ORCA

[ORCA](https://www.faccts.de/orca/) is a general-purpose quantum chemistry package that supports a wide variety of methods such as density functional theory, many-body perturbation and coupled cluster. ORCA is free of charge, but not open source.

Check out the ORCA manual for more information: https://www.faccts.de/docs/orca/6.0/manual/

Keywords: `quantum chemistry`, `chemistry`

## Available modules
There are several ORCA modules on Midway3 that you can check via `module avail orca`:

===+ "Midway3"
    ```
    ---------------------------- /software/modulefiles -----------------------------
    orca/4.1  orca/4.2.1  orca/5.0.2(default)  orca/6.0.1  
    orca/4.2  orca/5.0.0  orca/5.0.4
    ```

You can use `module show` to see the dependencies and environment variables set by a specified `orca` module, for example, `module show orca/6.0.1`:

```
-------------------------------------------------------------------
/software/modulefiles/orca/6.0.1:

module-whatis   {setup orca 6.0.1 compiled with the system compiler}
conflict        orca
module          load openmpi/4.1.2+gcc-10.2.0
prepend-path    PATH /software/orca-6.0.1-el8-x86_64/bin
setenv          ORCA_DIR /software/orca-6.0.1-el8-x86_64/bin
-------------------------------------------------------------------
```


## Example job script

An example batch script to run ORCA for Midway3 is given as below
```
#!/bin/bash
#SBATCH --job-name=orca-bench
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --mem=64GB

module load orca/6.0.1

ulimit -l unlimited

cd $SLURM_SUBMIT_DIR

# the environment variable ORCA_DIR may be set by the orca module loaded
$ORCA_DIR/orca input.txt > output.log
```

Note that ORCA supports MPI parallelization with a compatible version of OpenMPI. For the given example, `orca/6.0.1` is compatible with OpenMPI 4.1.x. Here the binary `orca` will launch the 8 MPI processes as specified in the `%pal` section in the input script `input.txt`. Below is a simple input script that performs a geometry optimization calculation with the Hartree-Fock method with the DEF2-SVP basis set using 8 MPI procs.
```
%pal
    nprocs 8
end
!HF DEF2-SVP
%scf
   maxiter 500
end
* xyz 0 1
O   0.0000   0.0000   0.0626
H  -0.7920   0.0000  -0.4973
H   0.7920   0.0000  -0.4973
*
```

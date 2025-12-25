##  Getting your software ready

You should check what software packages are already installed on Midway3 via `module avail` and `module list`. Many commonly used software packages and libraries have been installed on Midway for your use.  For an overview of how to use Software Modules on Midway, consult the RCC [Software](../software/index.md) documentation page.

For this tutorial, let us load `python`

```
module load python
```

which will load the default version of the `python/anaconda` module. You can do `module list` to see which version is just loaded.

Suppose that you would like to install numpy, matplotlib and pandas for your calculations.  You should first create an environment in your own space and install these packages into this environment.  See [managing Python environments](../software/apps-and-envs/python.md) for more information.

Since Python environments might contain many files and/or take a lot space, it is recommended that you create your environments somewhere outside your home folder such as `/project` or `/scratch`. Suppose that your PI has a space under `/project/[pi-folder]` and you have a folder under that location.

```
cd /project/[pi-folder]/[your-cnetid]
python -m venv my-venv
source activate ./my-venv
pip install matplotlib numpy pandas
```

Note that the base environment of the default `python` module already has many popular packages installed, including the above 3 packages. You can also create an environment and install packages with `conda` or `mamba`.

If you need to compile your software packages from source, you can download the software source code from GitHub to your space, load the compiler modules and build the codes. In this tutorial, let us build [LAMMPS](https://github.com/lammps/lammps) from source code:

```
cd /project/[pi-folder]/[your-cnetid]
git clone https://github.com/lammps/lammps.git
cd lammps
mkdir build && cd build
```

Load the modules for the preferred compiler, MPI libraries and MKL, and cmake to configure the build:
```
module load mpich/3.4.3+gcc-10.2.0 mkl/2023.1 cmake/3.26
cmake ../cmake -C ../cmake/presets/basic.cmake -DFFT=MKL -DFFTW3_INCLUDE_DIR=$MKLROOT/include/fftw
```

and finally build the code

```
make -j4
```

If the build succeeds, you will see a LAMMPS binary, namely `lmp`, generated under the folder `/project/[pi-folder]/[your-cnetid]/build`.

You can use other compilers (Intel oneAPI, GNU GCC) and MPI libraries (OpenMPI, MPICH). For GPU codes, you can use NVIDIA HPC SDK and Intel oneAPI. More information on the available development tools is given in [Compilers](../software/compilers.md). 
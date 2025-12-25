# Stata

Stata is a powerful statistical software package that is widely used in scientific computing. RCC users are licensed to use Stata on all RCC resources. Stata can be used interactively or as a submitted script. Please note that if you would like to run it interactively, you must still run it on a compute node, in order to keep the login nodes free for other users. Stata can be run in parallel on up to 16 nodes.

**NOTE**: Stata examples in this document are adapted from a Princeton [tutorial](http://data.princeton.edu/stata/). You may find it useful if you are new to Stata or want a refresher.

## Getting Started

If you need to use the Stata GUI, connect to Midway with ThinLinc.

Obtain an interactive session on a compute node. This is necessary so that your computation doesn’t interrupt other users on the login node. Now, load Stata:

```bash
sinteractive
module load stata
xstata
```

This will open up a Stata window. The middle pane has a text box to enter commands at the bottom, and a box for command results on top. On the left there’s a box called “Review” that shows your command history. The right-hand box contains information about variables in the currently-loaded data set.

One way Stata can be used is as a fancy desktop calculator. Type the following code into the command box:

```default
display 2+2
```

Stata can do much more if data is loaded into it. The following code loads census data that ships with Stata, prints a description of the data, then creates a graph of life expectancy over GNP:

```default
sysuse lifeexp
describe
graph twoway scatter lexp gnppc
```

## Running Stata from the command line

This is very similar to running graphically; the command-line interface is equivalent to the “Results” pane in the graphical interface. Again, please use a compute node if you are running computationally-intensive calculations:

```bash
sinteractive
module load stata
stata
```

## Running Stata Jobs with SLURM

You can also submit Stata jobs to SLURM, the scheduler. A Stata script is called a “do-file,” which contains a list of Stata commands that the interpreter will execute. You can write a do-file in any text editor, or in the Stata GUI’s do-file editor: click “Do-File Editor”” in the “Window” menu. If your do-file is named “example.do,” you can run it with either of the following commands:

```bash
stata < example.do
stata -b do example.do
```

Here is a very simple do-file, which computes a regression on the sample data set from above:

```default
version 13 // current version of Stata, this is optional but recommended.

sysuse lifeexp
gen loggnppc = log(gnppc)
regress lexp loggnppc
```

Here is a submission script that submits the Stata program to the default queue on Midway:

```bash
#!/bin/bash

#SBATCH --job-name=stataEx
#SBATCH --output=stata_example.out
#SBATCH --error=stata_example.err
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1

module load stata

stata -b stata_example.do
```

`stata_example.do` is our example do-file, and `stata_example.sbatch` is the submission script.

To run this example, download both files to a directory on Midway.  Enter the following command to submit the program to the scheduler:

```bash
sbatch stata_example.sbatch
```

Output from this example can be found in the file named `stata_example.log`, which will be created automatically in your current directory.

### Running Parallel Stata Jobs

The parallel version of Stata, Stata/MP, can speed up computations and make effective use of RCC’s resources. When running Stata/MP, you are limited to 16 cores and 5000 variables. Run an interactive Stata/MP session:

```bash
sinteractive
module load stata
stata-mp
# or, for the graphical interface:
xstata-mp
```

Here is a sample do-file that would benefit from parallelization. It runs bootstrap estimation on another data set that ships with Stata.

```default
version 13

sysuse auto
expand 10000
bootstrap: logistic foreign price-gear_ratio
```

Here is a submission script that will run the above do-file with Stata/MP:

```bash
#!/bin/bash

#SBATCH --job-name=stataMP
#SBATCH --output=stata_parallel.out
#SBATCH --error=stata_parallel.err
#SBATCH --nodes=1
#SBATCH --tasks-per-node=16

module load stata
stata-mp -b stata_parallel.do
```

Download `stata_parallel.do` and `stata_parallel.sbatch` to Midway, then run the program with:

```bash
sbatch stata_parallel.sbatch
```

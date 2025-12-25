## Using R on the Midway Cluster

[R](https://cran.r-project.org) is a powerful tool for quantitative research and data analysis across various fields.

For detailed, step-by-step instructions on setting up and using R on Midway2, refer to [this tutorial](https://github.com/rcc-uchicago/R-large-scale). These instructions are also applicable to Midway3 due to similar configurations.

#### Checking Available R Modules

To see the list of currently available R modules, run:

```sh
module avail R
```

#### Using RStudio IDE

The RStudio Integrated Development Environment (IDE) is available as `rstudio` modules. To check available versions, run:

```sh
module avail rstudio
```

When using RStudio, it is recommended to connect to the RCC cluster via ThinLinc for a smoother experience.

#### Spatial Packages

The `sf` package in R provides tools for handling spatial data using simple features. For more information, visit the [sf Package on CRAN](https://cran.r-project.org/web/packages/sf/index.html).

#### Midway2 Environment
- **Dependencies**: GDAL 2.4.1, udunits 2.2
- **R Version**: 4.2.0

#### Midway3 Environment
- **Dependencies**: GDAL 3.3.3, udunits 2.2, GEOS 3.9.1, GCC 10.2.0, SQLite 3.36.0
- **R Versions**: 4.2.1 and 4.3.1

#### Module Loading
Before using or installing `sf` on Midway3, load the necessary modules:
=== "Midway2"
    ```bash
    module load gdal/2.4.1 udunits/2.2 R/4.2.0
    ```
=== "Midway3"
    ```bash
    module load gdal/3.3.3 udunits/2.2 geos/3.9.1 gcc/10.2.0 sqlite/3.36.0 R/4.3.1
    ```

#### Additional Packages
The `terra` and `raster` packages are also installed.

### Installing R Packages: A Comprehensive Guide

R packages can be distributed as source code or compiled binaries. Source packages must be compiled before installation, typically requiring the GNU Compiler Collection (GCC). Here’s how to get started with R package installation on our HPC clusters.

#### Check GCC Version

To ensure compatibility, verify the version of GCC (g++) on your system:

```sh
$ g++ --version
g++ (GCC) 8.5.0 20210514 (Red Hat 8.5.0-10)
Copyright (C) 2018 Free Software Foundation, Inc.
This is free software; see the source for copying conditions.  There is NO
warranty; not even for MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
```

#### Before You Install

1. **Check Disk Space**:
   Ensure you have enough disk space using the `quota` command:
   ```sh
   $ quota
   ```

2. **Load Necessary Modules**:
   For packages like `ncdf4` and `hdf5r`, load the required modules before starting R:
   ```sh
   $ module load hdf5 netcdf
   ```
   For more information on working with netCDF files in R, you can check out this resource: [NetCDF with R](https://pjbartlein.github.io/REarthSysSci/netCDF.html). 


#### Installing Packages

To install R packages, use the `install.packages` function within an R session:

```R
install.packages("packageName")
```

For multiple packages:

```R
install.packages(c("package1", "package2"))
```

## FAQ

1. **Delete All R Packages and Start Over**:
   If you need to reset your R environment, delete all R packages and related files:
   ```sh
   $ rm -rf ~/R ~/.R ~/.rstudio* ~/.Rhistory ~/.Rprofile ~/.RData
   ```

2. **Update ~/.bashrc**:
   Remove any added or modified environment variables if necessary.

3. **See Where R Packages Are Installed**:
   ```R
   .libPaths()
   Sys.getenv("R_LIBS_USER")
   ```

4. **List Installed Packages**:
   ```R
   installed.packages()
   ```

5. **List Default Packages**:
   ```R
   getOption("defaultPackages")
   ```

6. **Remove a Package**:
   ```R
   remove.packages("packageName")
   ```

## Using the `renv` R Package to Create a Personal R Project Environment on the Midway Cluster

The `renv` package in R helps manage project-specific libraries, ensuring consistent package versions across projects. Here’s a step-by-step guide to set up and use `renv` for your project located at `/project/pi-cnetid/rproject/` on the Midway cluster.

#### Step 1: Load Necessary Modules

Before starting, ensure you have the necessary modules loaded. You can load the R module appropriate for your project:

```sh
module load R/4.3.1
```

#### Step 2: Set Up the Project Directory

Navigate to your project directory:

```sh
cd /project/pi-cnetid/rproject/
```

#### Step 3: Initialize `renv` in Your Project

Start R and initialize `renv` in your project directory:

```sh
R
```

Inside the R session, run:

```R
# Install renv if not already installed
install.packages("renv")

# Initialize renv in the project directory
renv::init()
```

This command will set up a new project-specific library in the `renv` subdirectory of your project directory and create an `renv.lock` file to record the state of your library.

#### Step 4: Install Packages within the `renv` Environment

With `renv` initialized, install any necessary packages:

```R
# Install required packages
renv::install("dplyr")
renv::install("ggplot2")
# Add more packages as needed
```

#### Step 5: Snapshot the Current State of Your Library

After installing the necessary packages, snapshot the current state of your library to `renv.lock`:

```R
renv::snapshot()
```

This records the exact versions of the packages you have installed, allowing you to recreate the environment later.

#### Step 6: Restore Library from `renv.lock` (Optional)

If you need to recreate the environment on another system or after a system change, you can restore the library:

```R
renv::restore()
```

This command reads the `renv.lock` file and installs the specified package versions.

#### Step 7: Using the Project

Whenever you start working on your project, load the `renv` environment:

```R
# Activate the renv environment
renv::activate()
```

This ensures that all package installations and library paths are managed by `renv`.

#### Example Workflow

Here’s a complete example workflow from the terminal to R session:

1. **Load R Module**:
   ```sh
   module load R/4.3.1
   cd /project/pi-cnetid/rproject/
   ```

2. **Start R and Initialize `renv`**:
   ```sh
   R
   ```

3. **Within R Session**:
   ```R
   install.packages("renv")
   renv::init()
   renv::install("dplyr")
   renv::install("ggplot2")
   renv::snapshot()
   q()  # Quit R session
   ```

4. **Future Sessions**:
   ```R
   renv::activate()
   ```

By following these steps, you can set up and manage a project-specific R environment on the Midway cluster, ensuring consistency and reproducibility for your R projects.


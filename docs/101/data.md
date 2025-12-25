## Getting your data ready

Midway3 compute nodes have access to `/project` and `/project2`, in addition to the shared scratch space `/scratch/midway3`. It is recommended that you put your input and output data under one of those spaces for fast access from the compute nodes. See [Storage](../storage/main.md) for more details.

```
cd /project/[pi-folder]/[your-cnetid]
git clone https://github.com/[some-data-pool.git]
```
or
```
wget [some-url]
```

In this tutorial, let us say we have the input data in the `examples` folder in the `lammps` repo from above.

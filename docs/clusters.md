# Hardware Overview

<!-- From these links:
https://mdw3-docs.rcc.uchicago.edu/ -->
## Midway3 HPC Cluster

![Midway3 Nodes](img/hardware/midway3_nodes_cropped.jpeg)
### Operating System and Connectivity

Midway3 runs CentOs 8, and all nodes are connected via HDR Mellanox InfiniBand (100 Gbps) Interconnect.

### Standard Compute Nodes

* 210 Intel Cascade Lake CPU-only compute nodes, each equipped with:
    * 2x Intel Xeon Gold 6248R (48 cores per node)
    * 960 GB Local SSD Storage 
    * 192 GB Memory 

### Specialized Nodes

#### GPU Nodes
There are 11 GPU nodes that are part of the Midway3 communal resources. Each GPU node has the Standard Intel Compute Node specifications and the following GPU configurations:

* 5 GPU nodes w/ 4x NVIDIA V100 GPUs per node
* 5 GPU nodes w/ 4x NVIDIA Quadro RTX 6000 GPUs per node
* 1 GPU node w/ 4x NVIDIA A100 GPUs per node

#### Big Memory Nodes
There are 2 big memory nodes available to all users. Each big memory node has the Standard Intel Compute Node specifications, but with the following larger memory configurations:

* 1 node w/ 768 GB of memory
* 1 node w/ 1.54 TB of memory

#### AMD Nodes
There are 40 nodes with AMD CPUs and the following configuration:

* 2x AMD EPYC Rome processors (128 cores per node)
* 960 GB Local SSD Storage 
* 256 GB Memory




## Midway2 HPC Cluster
<!-- From these links:
https://rcc.uchicago.edu/resources/ 
https://rcc.uchicago.edu/support-and-services/midway2
-->

![Midway2 Nodes](img/hardware/midway2_nodes_2.jpeg)
### Operating System and Connectivity

Midway2 runs CentOs 8, and all standard nodes are connected via HDR InfiniBand (100 Gbps) interconnect.

### Standard Compute Nodes

* 115 Intel Broadwell CPU-only compute nodes, each equipped with:
    * 2x Intel E5-2680 v4 (28 cores per node)
    * 400 GB Local SSD Storage 
    * 64 GB Memory 

### Specialized Nodes

#### GPU Nodes
There are 6 GPU nodes that are part of the Midway2 communal resources. Each GPU node has the following configuration:

* GPU: 2x Nvidia K80
* CPU: 2 * Intel E5-2680 v4  2.40 GHz
* Memory: 128 GB 
* Interconnect: InfiniBand FDR 56 Gb/s


#### Big Memory Nodes
There is 1 big memory node available to all users. The big memory node has the Standard Intel Compute Node specifications, but with the following larger memory configurations:

* 1 node w/ 512 GB of memory

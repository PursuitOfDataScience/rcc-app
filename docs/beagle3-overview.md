# Beagle3
<!-- From these links:
https://biologicalsciences.uchicago.edu/news/features/beagle-3-gpu-cluster -->

## What is Beagle3?
Beagle3 is a high-performance computing cluster funded by the NIH grant led by Professor Benoit Roux, the Amgen Professor of Biochemistry and Molecular Biology. [The project](https://biologicalsciences.uchicago.edu/news/features/beagle-3-gpu-cluster) benefits biomedical research with cutting-edge HPC resources for modeling and large-scale simulations of the molecular building blocks for biological functions. The cluster also serves research projects that employ recent advances in imaging technology, like cryo-electronic microscopy, for producing images of molecules at unprecedented resolution. The enormous amount of data rapidly generated need commensurate amounts of computing horsepower to analyze. Beagle3 has been in service since February 2022.

Beagle3 consists of 44 computing nodes, each with an 32-core Intel Xeon Gold 6346 CPUs and 4 NVIDIA A100 graphics processing units (GPUs).

## Gaining Access

You should contact your PI for access to Beagle3. You can also [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target="_blank"} for assistance.

## Partitions

=== "Beagle3"
      | Partition | Nodes  | CPUs | CPU Type  | GPUs | GPU Type| Total Memory|
      | --------- | -------| -----| --------- | ---- | ------- | ----------- |
      | beagle3   |   22   |  32  | gold-6346 | 4    |  a40    |    256 GB   |
      | beagle3   |   22   |  32  | gold-6346 | 4    |  a100   |    256 GB   |
      | beagle3   |   4    |  32  | gold-6346 | None |  None   |    512 GB   |

## Quality-of-Service

There are two quality-of-service (QoS) options available on the beagle3 partition. You can specify either one by using the --qos flag in your sbatch scripts or sinteractive commands.


`--qos=beagle3`: This QoS allows you to request up to 256 CPU-cores and 32 GPUs, and a maximum wall time of 48 hours. It is the default QoS for the beagle3 partition.

`--qos=beagle3-long`: This QoS allows you to request up to 128 CPU-cores and 16 GPUs, and a maximum wall time of 96 hours.

## Connecting and Running Jobs

You connect to and run jobs on Beagle3 in a similar manner to [Midway](slurm/main.md). Your home space is the same on Midway3, and you can access other mount points on Beagle3 from Midway3 as well.

## Troubleshooting

For further assistance, please [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target="_blank"}.
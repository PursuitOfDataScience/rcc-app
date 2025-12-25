# Skyway
<!-- From these links:
https://cloud-skyway.rcc.uchicago.edu/ -->

## What is Skyway?
Skyway is an integrated platform developed at the RCC to allow users to burst computing workloads from the on-premise RCC cluster, Midway, to run on remote commercial cloud platforms such as Amazon AWS and Google GCP. Skyway enables users to run computing tasks in the cloud from Midway in a seamless manner without needing to learn how to provision cloud resources. Since the user does not need to setup or manage cloud resources themselves, the result is improved productivity with a minimum learning curve.

Please refer to the [Skyway](https://cloud-skyway.rcc.uchicago.edu/) home page for more information.


## Gaining Access

You first need an active RCC User account (see [accounts and allocations page](https://rcc.uchicago.edu/accounts-allocations)). Next, you should contact your PI or class instructors for access to Skyway. Alternatively, you can [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target="_blank"} for assistance.

## Connecting and Running Jobs

Once your RCC User account is active, you log in to the Midway cluster with your `CNetID`
```
  ssh [CNetID]@midway2.rcc.uchicago.edu
```
then log in to Skyway from Midway2:
```
  ssh [CNetID]@skyway.rcc.uchicago.edu
```
If successful, you will get access to the Skyway login node, where you can access to the following locations:

1. `/home/[CNetID]`
This is the temporary home directory (no backup) for users on Skyway. Note, this is NOT the home file system on Midway, so you won’t see any contents from your home directory on midway. Please do NOT store any sizable or important data here. (`TODO`: Add note here about changing $HOME environment variable to `/cloud/aws/[CNetID]`.)
2. `/project` and `/project2`
This is the RCC high-performance capacity storage file systems from Midway, mounted on Skyway, with the same quotas and usages as on Midway. Just as with running jobs on Midway, /project and /project2 should be treated as the location for users to store the data they intend to keep. This also acts as a way to make data accessible between Skyway and midway as the /project and /project2 filesystems are mounted on both systems.
Run `cd /project/<labshare>` or `/project2/<labshare>`, where `<labshare>` is the name of the lab account, to access the files by your lab or group. This will work even if the lab share directory does not appear in a file listing, e.g., `ls /project`.
3. `/cloud/[cloud]/[CNetID]`
Options of [cloud]: aws or gcp
This is the cloud scratch folder (no backup), which is intended for read/write of cloud compute jobs. For example, with Amazon cloud resources (AWS) The remote cloud S3 AWS bucket storage is mounted to Skyway at this path. Before submitting jobs to the cloud compute resources, users must first stage the data, scripts and executables their cloud job will use to the /cloud/aws/[CNetID] folder. After running their cloud compute job, users should then copy the data they wish to keep from the /cloud/aws/[CNetID] folder back to their project folder. Similarly, if users are using Google Cloud Platform (GCP), the scratch folder /cloud/gcp/[CNetID] should be used.

You can create your own folders, upload data, write and compile codes, prepare job scripts and submit jobs in a similar manner to what you do on [Midway](slurm/main.md).

Skyway provides compiled software packages (i.e. `modules`) that you can load to build your codes or run your jobs. The list of the modules is given in the [Skyway](https://cloud-skyway.rcc.uchicago.edu/){:target='_blank'} home page.

You submit jobs to SLURM in a similar manner to what do on [Midway](slurm/main.md). The difference is that you should specify different partitions and accounts corresponding to the cloud services you have access to (e.g. AWS or GCP). Additionally, the instance configuration should be specified via `--constraint`.


## Troubleshooting

For further assistance, please [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target="_blank"}.

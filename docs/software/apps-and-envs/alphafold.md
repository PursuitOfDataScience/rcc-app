# AlphaFold Documentation

[AlphaFold](https://www.deepmind.com/research/highlighted-research/alphafold) is an artificial intelligence program developed by Google DeepMind, a subsidiary of Alphabet, which predicts protein structures with high accuracy. This documentation provides instructions for running **AlphaFold2** and **AlphaFold3** on the Midway3 HPC system.

---

## **Available Modules**

### **AlphaFold 2**
AlphaFold 2 is available as modules on Midway3. You can check the available versions using the following command:
```bash
module avail alphafold
```
Output:
```
---------------------- /software/modulefiles----------------------------------
alphafold/2.0.0(default)  alphafold/2.2.0  alphafold/2.3.2
```

The AlphaFold source code and running scripts (e.g., `run_alphafold.py`) can be found on the [AlphaFold GitHub repository](https://github.com/deepmind/alphafold).

The training datasets for different versions of AlphaFold are accessible under:
- `/software/alphafold-data/`
- `/software/alphafold-data-2.2/`
- `/software/alphafold-data-2.3/`

---

### **AlphaFold 3**
AlphaFold 3 on Midway3 uses a container-based approach with **Singularity** (or Apptainer) and requires different input arguments compared to AlphaFold 2. It supports advanced features like **FlashAttention** and improved accuracy for protein-ligand and protein-DNA interactions. See the example job script below for usage details.

---

## **Key Differences Between AlphaFold 2 and AlphaFold 3**
| Feature                | AlphaFold 2                          | AlphaFold 3                          |
|------------------------|---------------------------------------|---------------------------------------|
| Input Format           | `.fasta` file                       | `.json` file                         |
| Execution Environment  | Python-based scripts                | Singularity container                |
| GPU Requirements       | Moderate GPU memory (e.g., V100)    | High GPU memory (e.g., 2 A100 GPUs)  |
| FlashAttention Support | Not available                       | Supported (`triton` or `xla`)        |

---

## **System Requirements**

### **AlphaFold 2**
- **GPU:** V100 or higher (NVIDIA GPU with compute capability ≥8.0 recommended)
- **CUDA:** Version 11.3 or higher
- **Memory:** 32GB RAM minimum (64GB recommended for large proteins or multiple jobs)

### **AlphaFold 3**
- **GPU:** A100 or higher recommended (80GB GPU RAM may be needed for very large inputs)
- **CUDA:** Version 12.3 or higher (CUDA 12.6 preferred for best accuracy; 12.2 may work, but not guaranteed)
- **Memory:** 32GB RAM minimum (more is better for large jobs and databases)

??? note "Why Container-Based Approach for AlphaFold 3?"
    AlphaFold 3 requires CUDA 12.3 or higher, but the system NVIDIA driver version is 12.2. By using a container, we bypassed the driver compatibility issue.

    *This guidebook will be updated with a module-based usage method for AlphaFold 3 in the future, as the system CUDA version is updated.*

---

## **Example Job Scripts**

### **AlphaFold 2 Job Script**
The following example demonstrates how to run AlphaFold 2 on a GPU node with 2 GPUs and up to 16 CPU cores for multithreading on Midway3.

```bash
#!/bin/bash
#SBATCH --job-name=alphafold2
#SBATCH --account=[your-accountname]
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:2
#SBATCH --constraint=v100
#SBATCH --mem=64G

module load alphafold/2.3.2 cuda/11.3

cd $SLURM_SUBMIT_DIR

DOWNLOAD_DATA_DIR=/software/alphafold-data-2.3

python run_alphafold.py \
  --data_dir=$DOWNLOAD_DATA_DIR  \
  --uniref90_database_path=$DOWNLOAD_DATA_DIR/uniref90/uniref90.fasta  \
  --mgnify_database_path=$DOWNLOAD_DATA_DIR/mgnify/mgy_clusters_2022_05.fa  \
  --bfd_database_path=$DOWNLOAD_DATA_DIR/bfd/bfd_metaclust_clu_complete_id30_c90_final_seq.sorted_opt  \
  --uniref30_database_path=$DOWNLOAD_DATA_DIR/uniref30/UniRef30_2021_03 \
  --pdb70_database_path=$DOWNLOAD_DATA_DIR/pdb70/pdb70  \
  --template_mmcif_dir=$DOWNLOAD_DATA_DIR/pdb_mmcif/mmcif_files  \
  --obsolete_pdbs_path=$DOWNLOAD_DATA_DIR/pdb_mmcif/obsolete.dat \
  --model_preset=monomer \
  --max_template_date=2022-1-1 \
  --db_preset=full_dbs \
  --use_gpu_relax=true \
  --output_dir=out_alphafold_2.1.1_multi-monomer \
  --fasta_paths=T1083.fasta,T1084.fasta
```

---

### **AlphaFold 3 Job Script**
The following example demonstrates how to run AlphaFold 3 using a `.json` input file (e.g., `nipah_zmr.json`) on a GPU node with 2 A100 GPUs.

```bash
#!/bin/bash
#SBATCH --job-name=alphafold3
#SBATCH --account=[your-accountname]
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:2
#SBATCH --constraint=a100
#SBATCH --mem=32G

module load apptainer

cd $SLURM_SUBMIT_DIR

# Set the path to the AlphaFold 3 database directory
DOWNLOAD_DATA_DIR=/software/alphafold3.0-el8-x86_64/databases  # Path to AlphaFold 3 database directory

# Define bind paths
export BIND_PATHS="$DOWNLOAD_DATA_DIR,/software/alphafold3.0-el8-x86_64/params,/software/alphafold3.0-el8-x86_64/singularity,/tmp/$USER,/home/$USER,/scratch/midway3/$USER"

# Run the Singularity container
singularity exec --nv \
    -B "$BIND_PATHS" \
    --env CUDA_VISIBLE_DEVICES=0,1,NVIDIA_VISIBLE_DEVICES=0,1 \
    /software/alphafold3.0-el8-x86_64/alphafold3.sif \
    python /app/alphafold/run_alphafold.py \
    --json_path=/home/$USER/nipah_zmr.json \
    --db_dir=$DOWNLOAD_DATA_DIR \
    --output_dir=/scratch/midway3/$USER/alphafold3_output \
    --model_dir=/software/alphafold3.0-el8-x86_64/params \
    --flash_attention_implementation=triton \
    --run_data_pipeline=True \
    --run_inference=True \
    --jackhmmer_n_cpu=8 \
    --nhmmer_n_cpu=8
```

---

## **Input File Preparation**

### **AlphaFold 2**
- Input format: `.fasta` file containing the protein sequence(s).
- Example:
  ```
  >T1083
  SEQUENCE1
  >T1084
  SEQUENCE2
  ```

### **AlphaFold 3**
- Input format: `.json` file containing the protein sequence(s) and metadata.
- Example:
  Download the example file `nipah_zmr.json` from [this link](https://www.rbvi.ucsf.edu/chimerax/data/af3-wynton-dec2024/nipah_zmr.json) and place it in your home directory (`/home/$USER`).

---

## **Troubleshooting**

### **Common Errors and Solutions**

1. **Error**: `Unknown backend: 'gpu' requested, but no platforms that are instances of gpu are present.`
     - **Solution**: Ensure the job is running on a GPU-enabled node and that the `CUDA_VISIBLE_DEVICES` environment variable is set correctly.

2. **Error**: `Failed to get mmCIF for <PDB_ID>.`
     - **Solution**: Verify that the database directory is accessible and contains the required files. Ensure proper permissions:
     ```bash
     chmod 755 --recursive /software/alphafold3.0-el8-x86_64/databases
     ```

3. **Error**: `implementation='triton' for FlashAttention is unsupported on this GPU generation.`
     - **Solution**: Switch to the `xla` implementation:
     ```bash
     --flash_attention_implementation=xla
     ```

4. **Error**: `CUDA version mismatch.`
     - **Solution**: Ensure the NVIDIA driver and CUDA versions are compatible with AlphaFold3. Update the driver if necessary. For instance, if `nvidia-smi` on the node shows
     ```
     NVIDIA-SMI 535.161.08             Driver Version: 535.161.08   CUDA Version: 12.2     
     ```
     it means that the GPU driver version is 535.161.08, which was installed along with the CUDA toolkit version 12.2. If a version of AlphaFold3 relies on the CUDA toolkit 12.X (where X > 2), make sure that the GPU driver 535.161.08 is also compatible with this CUDA 12.x version.

---

## **Additional Notes**

- **Resource Allocation**: Adjust the `--gres=gpu` and `--mem` parameters in the job script based on the size of the input data.
- **Output Directory**: Results will be saved in the directory specified by the `--output_dir` parameter.

For more information, visit the [AlphaFold GitHub repository](https://github.com/deepmind/alphafold) or contact the RCC support team.

---

# OpenPose

OpenPose is available on Midway3 as a container. You can find the singularity file, named `openpose-v2_v0.1.sif`, under the directory `/project/rcc/shared/container`. 

To get started with a minimal working example, you'll want to follow these steps:

First, you'll need to launch a GPU node on Midway3. Once you've done that, run the following commands:

Go to your Midway3 scratch or project directory: 

`cd /scratch/midway3/$USER/containers`

or

`cd /project/drpepper/containers`

Copy the OpenPose container to your  Midway3 scratch or project directory:

`cp /project/rcc/shared/container/openpose-v2_v0.1.sif ./`

Load the `apptainer` module:

`module load apptainer`

Then load the OpenPose container: 

`apptainer shell -B /projects -B /scratch --nv ./openpose-v2_v0.1.sif`
 

After entering the container, you need to create a directory for your results:

`mkdir -p /scratch/midway3/$USER/poses`
 
Next, navigate to the OpenPose folder and execute the example:

`cd /openpose`

```
./build/examples/openpose/openpose.bin --video examples/media/video.avi --write_video /scratch/midway3/$USER/result.avi --write_json /scratch/midway3/$USER/poses --display 0
```

Once the process is complete, check the `result.avi` file created in your scratch folder. 
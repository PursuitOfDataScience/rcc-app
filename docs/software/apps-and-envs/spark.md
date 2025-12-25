# Spark

Apache Spark is a fast and general engine for large-scale data processing.  It
has a Scala, Java, and Python API and can be run either on either a single node
or multi-node configuration. For both cases, it is recommended to have exclusive
access of the node in Slurm.

## Single Node Examples

Here is the SparkPi and pi.py examples from the Spark distribution running on
a single node:

sbatch script `spark-single-node.sbatch`

```bash
#!/bin/bash

#SBATCH --job-name=spark
# Exclusive mode is recommended for all spark jobs
#SBATCH --exclusive
#SBATCH --nodes=1
#SBATCH --time=10

module load spark

# This syntax tells spark to use all cpu cores on the node.
export MASTER="local[*]"

# This is a scala example
run-example SparkPi

# This is a python example. 
# For production jobs, you'll probably want to have a python module loaded.
# This will use the system python if you don't have a python module loaded.
spark-submit --master $MASTER $SPARK_HOME/examples/src/main/python/pi.py

```

## Multi-node Examples

For multi-node Spark jobs, a helper script was written to launch the master
and work tasks in the slurm allocation. Here are the same examples as above,
but with Spark running on multiple nodes:

sbatch script `spark-multi-node.sbatch`

```bash
#!/bin/bash

#SBATCH --job-name=spark-multi-node
# Exclusive mode is recommended for all spark jobs
#SBATCH --exclusive
#SBATCH --nodes=4
#SBATCH --time=10

module load spark

# This command starts the spark workers on the allocated nodes
start-spark-slurm.sh

# This syntax tells the spark workers where the master is
export MASTER=spark://$HOSTNAME:7077

# This is a scala example
run-example SparkPi

# This is a python example.
# For production jobs, you'll probably want to have a python module loaded.
# This will use the system python if you don't have a python module loaded.
spark-submit --master $MASTER $SPARK_HOME/examples/src/main/python/pi.py

```

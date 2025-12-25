# CryoSPARC

CryoSPARC (Cryo-EM Single Particle Ab-Initio Reconstruction and Classification) is a state of the art software to process cryo-electron microscopy (cryo-EM) data. It is designed as a dispatcher for cryo-EM workloads on a group of servers and workstations. RCC provides support for CryoSPARC on the [Beagle3](../../beagle3-overview.md) cluster.

## Installation and Setup

In order to use CryoSPARC on Beagle3, you need to request for a license from <a href='https://cryosparc.com/download' target='_blank'>CryoSPARC</a> and send it to RCC via [this form](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}. RCC will then setup your account and provide you with your account details. Each user will also recieve a dedicated base port for their account, usually ranging from 39100-39300, and a host machine name. 

## Getting Started

CryoSPARC's GUI can be accessed via [Thinlinc](../../thinlinc/main.md) or via your local machine's web browser. 

To start CryoSPARC, firstly, log into the host machine provided to you by RCC at the time of account creation and then run: 

```
cryosparcm start
```

You may check the status of CryoSPARC at any point to learn CryoSPARC's status by using:

```
cryosparcm status
```
Now, to access the GUI, open a browser within Thinlinc or on your local machine and type the host machine name (``beagle3-login3``) in the address bar along with the port number assigned to you. The hostmachine name is provided in the ``config.sh`` file in the ``master`` folder of your installation directory. 

!!! example
    You may type something like ``http://beagle3-login3.rcc.local:39190/`` in the address bar of the Thinlinc browser. 

!!! info
    {==You are required to use this host machine name provided at all times to avoid possible disruptions in service.==}

## Troubleshooting

### Sock Error

If the error message looks like, 
```unix:///tmp/cryosparc-supervisor–6410667835282660811.sock refused connection (already shut down?)```, 
follow the steps mentioned below.

1. Run ```cryosparcm stop``` 

2. Delete ```/tmp/*.sock``` file that belongs to your user account. The exact name of the the ``*.sock`` file will be in the error message.

3. Kill any interfering zombie processes that are still running. You can find the process IDs using:
```
ps -ax | grep "supervisord"
ps -ax | grep "cryosparc"
ps -ax | grep "mongod"
```
```
kill <PID>
```
4. Run ``cryosparcm start`` to start CryoSPARC again. 

### Database Failure:

1. Kill the mongo processes. You can find the process IDs using:

```ps -ax | grep “mongod”```
```kill <PID>```

2. Delete the ``.lock`` file at ``<cryosparc-install-dir>/db``

3. Start CryoSPARC again using:

```cryosparcm start```

### Database Spawn Error

If the error message looks like, 

```
Starting cryoSPARC System master process..
CryoSPARC is not already running.
database: ERROR (spawn error)
```

then follow the steps mentioned below

1. Make a complete copy of your ``db`` directory as a backup and keep it safe
```
cp -rav db db_backup
```

2. Stop CryoSPARC
```
cryosparcm stop
```

3. Remove the original folder 
```
rm -rf db
```

4. Kill zombie processes
```
ps -ax | grep "supervisord" (kill only the process that is running from your cryosparc install)
ps -ax | grep "cryosparc_command" (kill all the matching processes related to your cryosparc instance)
ps -ax | grep "mongod" (kill only the process running your cryosparc database)
```


5. Start cryosparc which  will recreate the database
```
cryosparcm start
```

6. Stop cryosparc 
```
cryosparcm stop
```

7. Run 
```
cp -rav db_backup db
```

8. ``cd`` into the ``db`` directory that has all your original database files and run the following bash commands
```
eval $(cryosparcm env)
```
```
mongod --dbpath ./ --repair
```

9. Start cryoSPARC again 
```
cryosparcm start
```




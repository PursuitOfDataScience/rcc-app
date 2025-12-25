# Accessing RCC clusters
 This tutorial shows the basic steps to use the Midway3 cluster at the RCC. For complete RCC technical documentation, see the main sections of this user guide. The information here describes how users can connect to Midway to access RCC resources. All users are responsible for knowing and abiding by the [RCC User Policy](policies.md).

## RCC account credentials
To connect to RCC resources, you must have an RCC user account ([request an account](https://rcc.uchicago.edu/accounts-allocations/request-account){:target='_blank'}).
Your RCC account uses your UChicago CNetID and its corresponding password: 

```
Username: CNetID
Password: CNetID password
```
!!! tip "Copy code"
    Wherever you see grey boxes like the one above, click the icon in the top right corner of the box to copy the contents to your clipboard. It's especially useful for longer code snippets! 

## Supported protocols
There are five main ways to access RCC resources. the following table provides a summary of these methods: 

|  <div style="width:150px">Connection Method | Description | Access to Compute Nodes | Data Transfer | Data Sharing |  
| ------------------------------------------- | ----------- | ------- | ------------- | ------------ | 
| [Secure Shell (SSH)](../ssh/main.md)  | Can be used to access data and software packages (compute nodes) | Yes | Yes (two-way) | RCC Internal |
| [ThinLinc](../thinlinc/main.md) | A remote desktop to resources and can be used to access data and software packages (compute nodes) | Yes | Yes (two-way) | RCC Internal |
|[SAMBA (SMB)](../samba.md)| Can be used to access data | No | Yes (two-way) | No |
|[Globus](../globus/access-files.md)| Can be used to access and share data and scheduled data transfers | No | Yes (two-way) | External and RCC collaborators |
|[HTTP](../http.md)| Can be used to share data for public access (legacy service) | No | Yes (one-way) | Public |

## SSH/SFTP

 Here you will use [Secure Shell (SSH)](../ssh/main.md) to connect to the login node from your local machine. 

 ```
ssh [your-cnetid]@midway3.rcc.uchicago.edu
```

After putting in your password, you will choose an option to accept a push on the Duo app. If successful, you will land on your home folder on the Midway3 login node as shown at the command prompt `[your-cnetid]@midway3-login3` or `[your-cnetid]@midway3-login4`.

You can check where the present working directory by running the command `pwd`:

```
pwd
```


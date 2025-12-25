# HTTP - Public folder

!!! warning "Midway2 only"
    Please note that HTTP-based data sharing is currently supported on Midway2 only.

RCC provides web access to data on their storage system via public_html directories in users’ home directories.

| Local path                                   | Corresponding URL                                         |
|----------------------------------------------|-----------------------------------------------------------|
| /home/[your_CNetID]/public_html/research.dat | http://users.rcc.uchicago.edu/~[your_CNetID]/research.dat |

Ensure your home directory and `public_html` have the execute [permissions](ssh/advance.md/#Data-sharing). If the folder `public_html` does not exist, create it. 
Optionally, ensure public_html has read permissions if you would like to allow indexing.

You may set these permissions using the following commands:
```
chmod o+x $HOME
mkdir -p $HOME/public_html
chmod o+x $HOME/public_html
// optional; if you would like to allow directory listing.
chmod o+r $HOME/public_html
```
Files in public_html must also be readable by the web user, "other", but should not be made executable.

You may set read permissions for web users/"other" using the following command:
```
chmod o+r $HOME/public_html/research.dat
```

!!! note
    Use of these directories must conform with the [RCC usage policy](https://rcc.uchicago.edu/about-rcc/rcc-user-policy). Please notify RCC if you expect a large number of people to access data hosted here.

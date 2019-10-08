# noita modding tools

these aren't for consumers yet. how did you get here?

only tested on python 3.7, install required modules:
```
C:\path\to\python.exe -m pip uninstall -y crypto pycryptodome 
C:\path\to\python.exe -m pip install ipython pycryptodome hexdump numpy
```

run it:
```
C:\path\to\python.exe wakman.py -xo ./datawak_extracted/ C:\noita\data\data.wak
```

```
usage: wakman.py [-h] [-x] -o OUTLOC [wak_file]

On windows, please run me like: C:\path\to\your\python.exe wakman.py [args here]

positional arguments:
  wak_file    Path to your data.wak. ex: "C:\Program Files (x86)\Noita\data\data.wak"

optional arguments:
  -h, --help  show this help message and exit
  -x          Extract the contents of a wak. Only lists contents if omitted.
  -o OUTLOC   Folder to extract wak to. ex: -o C:\wak_extracted
```
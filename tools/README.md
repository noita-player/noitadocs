# noita modding tools

only tested on python 3.7, install required modules:

```
python3 -m pip uninstall -y crypto pycryptodome 
python3 -m pip install pycryptodomex hexdump numpy
```

run it:

```
python3 wakman.py -xo ./datawak_extracted/ C:\noita\data\data.wak
# or, let it find your Noita directory automatically.
python3 wakman.py -xo ./datawak_extracted/ 
```

```
usage: wakman.py [-h] [-x] -o OUTLOC [-m NOITA_VERSION] [wak_file]

On windows, please run: C:\path\to\your\python.exe wakman.py [args here]

positional arguments:
  wak_file          Path to your data.wak. If omitted, wakman guesses.

optional arguments:
  -h, --help        show this help message and exit
  -x                Extract the contents of a wak. Only lists contents if
                    omitted.
  -o OUTLOC         Folder to extract wak to. ex: -o C:\wak_extracted
  -m NOITA_VERSION  Version of noita. 1 is stable, before oct10. 2 is beta and
                    after oct10.
```

build release:

```
python3 -m PyInstaller wakman.py --onefile
```

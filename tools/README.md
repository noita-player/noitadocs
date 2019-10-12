# noita modding tools

want a single exe build? check [releases](https://github.com/noita-player/noitadocs/releases)!!

only tested on python 3.7, replace "python3" with the path to your python.exe if you're having trouble on Windows:
```
python3 -m pip install -r requirements.txt
```

run it:

```
python3 wakman.py -xo ./datawak_extracted/ C:\noita\data\data.wak
# or, let it find your Noita directory automatically.
python3 wakman.py -xo ./datawak_extracted/ 
```

make noita load the extracted data off disk
```
ren C:\noita\data\data.wak data.disabled
# copy the extracted `data` folder into C:\noita\data
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

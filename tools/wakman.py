#!/usr/bin/python3
# 3.7.4 64-bit
# pip uninstall -y crypto pycryptodome
# pip install ipython pycryptodome hexdump numpy
from Cryptodome.Cipher import AES
from Cryptodome.Util import Counter
from Cryptodome.Util.number import bytes_to_long
import struct, os, sys, argparse
#import IPython
import hexdump
import numpy as np
from binascii import *
from badprng import *
from wakparsing import *

def parse_datawak(in_path, ver):
    print("[+] Parsing \"{}\"".format(in_path))
    datawak_contents = None
    with open(in_path, 'rb') as f:
        datawak_contents = f.read()

    parser = WAKParser(datawak_contents, ver)
    
    return parser

def extract_files(wak, out_dir, extract=True):
    if extract:
        out_dir = out_dir + "/"
        print("[+] Extracting to {}".format(out_dir))
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

    # multiprocessing this
    for f in wak.file_list:
        print("{:.50s}:[offs {:08X}][size {:08X}][pthl {:08X}]".format(f.path, f.offset, f.size, f.pathlen))
        if extract:
            fdata = wak.datawak_contents[f.offset:f.offset+f.size]
            f_iv = wak.prng.badprng_get16(0x165EC8F+f.tblidx)

            c = Counter.new(128, initial_value=bytes_to_long(f_iv))
            fdata_dec = AES.new(wak.prng.default_key, AES.MODE_CTR, counter=c).decrypt(fdata)

            out_filepath = os.path.abspath(out_dir+f.path)
            out_filedir = os.path.split(out_filepath)[0]
            if not os.path.exists(out_filedir):
                os.makedirs(out_filedir)
            with open(out_filepath, 'wb') as outfile:
                outfile.write(fdata_dec)
    print("[+] Complete, iterated {} files.".format(len(wak.file_list)))

# scrape registry if the user didn't tell us where their wak is
def find_datawak_registry():
    # if you've recently launched noita
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache', 0, winreg.KEY_READ)

        for i in range(0, winreg.QueryInfoKey(key)[1]):
            val = winreg.EnumValue(key, i)
            if "noita" in val[0].lower():
                noita_dir = os.path.split(val[0])[0]
                if os.path.exists(noita_dir+"\\data\\data.wak"):
                    return (noita_dir+"\\data\\data.wak")
    except (KeyboardInterrupt):
        raise
    except:
        pass
    
    # if you ever launched it from a random location, abuse the fact that the game is WOW64
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store', 0, winreg.KEY_READ)

        for i in range(0, winreg.QueryInfoKey(key)[1]):
            val = winreg.EnumValue(key, i)
            if "noita" in val[0].lower():
                noita_dir = os.path.split(val[0])[0]
                if os.path.exists(noita_dir+"\\data\\data.wak"):
                    return (noita_dir+"\\data\\data.wak")
    except (KeyboardInterrupt):
        raise
    except:
        pass

    # if you browsed to a folder with Noita in the name
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths', 0, winreg.KEY_READ)

        for i in range(0, winreg.QueryInfoKey(key)[1]):
            val = winreg.EnumValue(key, i)
            if "noita" in val[1].lower():
                noita_dir = os.path.split(val[1])[0]
                if os.path.exists(noita_dir+"\\data\\data.wak"):
                    return (noita_dir+"\\data\\data.wak")
                elif os.path.exists(noita_dir+"\\data.wak"):
                    return (noita_dir+"\\data.wak")
    except (KeyboardInterrupt):
        raise
    except:
        pass
    
    return None

def find_datawak():
    test_paths = [r'./data.wak', 
                  r'./data/data.wak',
                  r'C:\Program Files (x86)\Steam\steamapps\common\Noita\data\data.wak']
    for path in test_paths:
        if os.path.exists(path):
            return path

    if os.name == 'nt':
        path = find_datawak_registry()
        if path:
            return path
    
    print("[:(] exiting, couldn't find data.wak in default locations: {}".format(test_paths))
    exit(1)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description="On windows, please run: C:\\path\\to\your\python.exe wakman.py [args here]")
    ap.add_argument('-x', dest='extract', action='store_true', help='Extract the contents of a wak. Only lists contents if omitted.')
    ap.add_argument('-o', dest='outloc', required=True, type=str, help='Folder to extract wak to. ex: -o C:\\wak_extracted')
    ap.add_argument('-m', dest='noita_version', default=1, type=int, help='Version of noita. 1 is stable, before oct10. 2 is beta and after oct10.')
    ap.add_argument('wak_file', nargs='?', type=str, help='Path to your data.wak. If omitted, wakman guesses.')

    try:
        args = ap.parse_args()
        print(vars(args))
    except SystemExit as err:
        print("\n")
        if err.code == 2:
            ap.print_help()
        sys.exit(0)

    extract = False

    if args.outloc:
        args.outloc = os.path.abspath(args.outloc)
        print("[+] Output directory: {}".format(args.outloc))
    if args.extract:
        extract = True  

    # try to find your wak non-intrusively
    if args.wak_file is None or not os.path.exists(args.wak_file):
        if args.wak_file != None: 
            print("[?] Couldn't find your WAK at \"{}\"".format(args.wak_file))
        args.wak_file = os.path.abspath(find_datawak())
        input("[+] Found a WAK at \"{}\", parse this WAK? (press any key to continue, ctrl+c to cancel)\n".format(args.wak_file))

    args.wak_file = os.path.abspath(args.wak_file)

    try:
        wak = parse_datawak(args.wak_file, args.noita_version)
        extract_files(wak, args.outloc, extract)
    # UnicodeDecodeError should only occur if decryption failed, ValueError we throw in WAKParser
    except (UnicodeDecodeError, ValueError):
        print("[:(] extraction as version {} failed, trying another...", args.noita_version)
        args.noita_version = (args.noita_version % len(noita_versions)) + 1
        try:
            wak = parse_datawak(args.wak_file, args.noita_version)
            extract_files(wak, args.outloc, extract)
        except (UnicodeDecodeError, ValueError) as err:
            print(err)
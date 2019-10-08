#!/usr/bin/python3
# 3.7.4 64-bit
# pip uninstall -y crypto pycryptodome
# pip install ipython pycryptodome np hexdump
from Crypto.Cipher import AES
from Crypto.Util import Counter
from Crypto.Util.number import bytes_to_long
import struct, os, argparse
import IPython
import hexdump
import numpy as np
from binascii import *
from badprng import *
from wakparsing import *
from aestest import bytes_iv_one, bytes_iv_negone

def parse_datawak(in_path):
    print("[+] Parsing \"{}\"".format(in_path))
    datawak_contents = None
    with open(in_path, 'rb') as f:
        datawak_contents = f.read()

    parser = WAKParser(datawak_contents)
    
    return parser

def extract_files(wak, out_dir, extract=True):
    if extract:
        out_dir = out_dir + "/"
        print("[+] Extracting to {}".format(out_dir))
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

    # multiprocessing this
    for f in wak.file_list:
        print("{}:[offs {:08X}][size {:08X}][pthl {:08X}]".format(f.path, f.offset, f.size, f.pathlen))
        if extract:
            fdata = wak.datawak_contents[f.offset:f.offset+f.size]
            f_iv = badprng_get16(0x165EC8F+f.tblidx)

            c = Counter.new(128, initial_value=bytes_to_long(f_iv))
            fdata_dec = AES.new(default_key, AES.MODE_CTR, counter=c).decrypt(fdata)

            out_filepath = os.path.abspath(out_dir+f.path.decode())
            out_filedir = os.path.split(out_filepath)[0]
            if not os.path.exists(out_filedir):
                os.makedirs(out_filedir)
            with open(out_filepath, 'wb') as outfile:
                outfile.write(fdata_dec)

def find_datawak():
    test_paths = [r'./data/data.wak', r'C:\Program Files (x86)\Steam\steamapps\common\Noita\data\data.wak']
    for path in test_paths:
        if os.path.exists(path):
            args.wak_file = path
            return path
    
    print("[:(] exiting, couldn't find data.wak at: {}".format(args.wak_file))
    exit(1)

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('-x', dest='extract', action='store_true', help='Extract the contents of a wak. Only lists contents if omitted.')
    ap.add_argument('-o', dest='outloc', type=str, default='./wakman/', help='Folder to extract wak to.')
    ap.add_argument('wak_file', type=str, default=argparse.SUPPRESS, help='Path to your data.wak.', nargs='?')
    args = ap.parse_args()
    
    extract = False

    if args.outloc:
        args.outloc = os.path.abspath(args.outloc)
    if args.extract:
        extract = True

    # try to find your wak non-intrusively
    if not "wak_file" in args:
        args.wak_file = find_datawak()
    else:
        args.wak_file = os.path.abspath(args.wak_file)

    wak = parse_datawak(args.wak_file)
    extract_files(wak, args.outloc, extract)

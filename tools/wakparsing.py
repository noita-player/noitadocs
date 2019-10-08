#!/usr/bin/python3
# 3.7.4 64-bit
# pip uninstall -y crypto pycryptodome
# pip install ipython pycryptodome np hexdump
import struct
from Crypto.Cipher import AES
from Crypto.Util import Counter
from Crypto.Util.number import bytes_to_long

from badprng import *
from aestest import bytes_iv_one, bytes_iv_negone, default_key

# wakfiles = WAKFileList(buffer)
# for file in wakfiles:
#   print(file.path, file.offset, file.size, file.pathlen)
# todo: make it a generator
class WAKFileList():
    class WAKFile():
        def __init__(self, path, offset, size, pathlen, tblidx):
            self.path = path
            self.offset = offset
            self.size = size
            self.pathlen = pathlen
            self.tblidx = tblidx
    
    def __init__(self, buffer):
        self.files = []
        self.num = 0 # for iterator

        curpos = 0
        curidx = 0
        while curpos < len(buffer):
            offset  = struct.unpack("I", buffer[curpos:curpos+4])[0]
            size    = struct.unpack("I", buffer[curpos+4:curpos+8])[0]
            pathlen = struct.unpack("I", buffer[curpos+8:curpos+12])[0]
            path = buffer[curpos+12:curpos+12+pathlen]
            #IPython.embed()
            self.files.append(self.WAKFile(path, offset, size, pathlen, curidx))

            curpos += 12+pathlen
            curidx += 1

    def __iter__(self):
        return self
    
    def __next__(self):
        self.num += 1
        if self.num > len(self.files):
            self.num = 0
            raise StopIteration
        return self.files[self.num-1]

class WAKParser():
    def __init__(self, buffer):
        self.datawak_contents = buffer
        self.datawak_head = AES.new(default_key, AES.MODE_OFB, bytes_iv_one).decrypt(self.datawak_contents[0:16])
        self.datawak_head_length = struct.unpack("I", self.datawak_head[8:8+4])[0]

        c = Counter.new(128, initial_value=bytes_to_long(bytes_iv_negone))
        bodyaes = AES.new(default_key, AES.MODE_CTR, counter=c).decrypt(self.datawak_contents[16:self.datawak_head_length])
        first_buffer = bodyaes
        self.file_list = WAKFileList(first_buffer)

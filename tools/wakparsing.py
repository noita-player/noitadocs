#!/usr/bin/python3
# 3.7.4 64-bit
import struct

from Cryptodome.Cipher import AES
from Cryptodome.Util import Counter
from Cryptodome.Util.number import bytes_to_long

from badprng import *


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
            path = buffer[curpos+12:curpos+12+pathlen].decode()
            #IPython.embed()
            self.files.append(self.WAKFile(path, offset, size, pathlen, curidx))

            curpos += 12+pathlen
            curidx += 1

    def __len__(self):
        return len(self.files)

    def __iter__(self):
        return self
    
    def __next__(self):
        self.num += 1
        if self.num > len(self.files):
            self.num = 0
            raise StopIteration
        return self.files[self.num-1]

class WAKParser():
    def __init__(self, buffer, ver):
        self.prng = BadPRNG(ver)
        self.datawak_contents = buffer
        self.datawak_head = AES.new(self.prng.default_key, AES.MODE_OFB, self.prng.bytes_iv_one).decrypt(self.datawak_contents[0:16])
        self.datawak_head_length = struct.unpack("I", self.datawak_head[8:8+4])[0]

        if self.datawak_head[0:4] != b"\x00\x00\x00\x00":
            raise ValueError("ERROR: data.wak header seems incorrect, try a different value for -m")

        c = Counter.new(128, initial_value=bytes_to_long(self.prng.bytes_iv_negone))
        first_buffer = AES.new(self.prng.default_key, AES.MODE_CTR, counter=c).decrypt(self.datawak_contents[16:self.datawak_head_length])
        self.file_list = WAKFileList(first_buffer)

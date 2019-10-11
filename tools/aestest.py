#!/usr/bin/python3
# 3.7.4 64-bit
# pip uninstall -y crypto pycryptodome
# pip install ipython pycryptodome np hexdump
from binascii import *
from Cryptodome.Cipher import AES
from Cryptodome.Util import Counter
from Cryptodome.Util.number import bytes_to_long
#import IPython
import struct, os
import hexdump
import numpy as np
from badprng import *
# self-documenting
def hex_to_bytes(str_hex):
    str_hex = str_hex.replace("-", " ").replace(" ", "") # '-' is an windbg copypaste artifact
    return unhexlify(str_hex)
def h2b(s): return hex_to_bytes(s)

# don't know or care what AES mode they're using? try em all
def get_each_aes(bytes_data, bytes_key, bytes_iv):
    results = []
    # ECB
    res = AES.new(bytes_key, AES.MODE_ECB).encrypt(bytes_data)
    results.append(("ECB", res))

    # no iv CTR
    res = AES.new(bytes_key, AES.MODE_CTR).encrypt(bytes_data)
    results.append(("CTR", res))

    c = Counter.new(128, initial_value=bytes_to_long(bytes_iv))
    res = AES.new(bytes_key, AES.MODE_CTR, counter=c).encrypt(bytes_data)
    results.append(("CTR-iv", res))

    res = AES.new(bytes_key, AES.MODE_CBC, bytes_iv).encrypt(bytes_data)
    results.append(("CBC", res))
    
    res = AES.new(bytes_key, AES.MODE_CFB, bytes_iv).encrypt(bytes_data)
    results.append(("CFB", res))

    res = AES.new(bytes_key, AES.MODE_OFB, bytes_iv).encrypt(bytes_data)
    results.append(("OFB", res))

    res = AES.new(bytes_key, AES.MODE_GCM, bytes_iv).encrypt(bytes_data)
    results.append(("GCM", res))

# SIV keylen is restricted. prob not SIV.
#    res = AES.new(bytes_key, AES.MODE_SIV, bytes_iv).encrypt(bytes_data)
#    results.append(("SIV", res))

# OCB takes a 15 byte nonce. don't think so.
#    res = AES.new(bytes_key, AES.MODE_OCB, bytes_iv).encrypt(bytes_data)
#    results.append(("OCB", res))

    return results

# if you've got the result buffer, find the correct AES fn(s)
# empty array on failure
def find_matching_aes(bytes_data, bytes_key, bytes_iv, bytes_result):
    result = []
    for pair in get_each_aes(bytes_data, bytes_key, bytes_iv):
        if pair[1] == bytes_result:
            result.append(pair)
    return result

bytes_data   = h2b("7b 00 00 00 00 00 00 00-00 00 00 00 00 00 00 00")
bytes_key    = h2b("c3 d2 ba e7 c3 f3 62 9a-17 53 71 d6 b1 f5 05 aa")
bytes_iv     = h2b("d2 97 e4 d6 e9 46 ab b9-ed 46 bc 9b 2e 3e d4 e5")
bytes_result = h2b("a5 58 e1 18 56 10 cf 4d-d2 49 01 bf a9 3e f2 74")

foundaes = find_matching_aes(bytes_data, bytes_key, bytes_iv, bytes_result)

if __name__ == "__main__":
    IPython.embed()
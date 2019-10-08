from binascii import *
from Crypto.Cipher import AES
import IPython
import struct
import numpy as np

np.seterr(all='ignore')

# sanity checks of (input-after-cvttsd2si, v4-before-floatation, v4-after-mulsd-with-constant)
rngtests = [
    (0x298eace9, 0x55fa0a4f, 0x3fe57e8293e61d8f),
    (0x8165ec8d, 0x7fffbe58, 0x3fefffef9638beb3) # negative test
]

# .rdata:014EF9B0 00 00 00 00 00 00 E0 C1 for_fmul_rand_dblfloat dq -2.147483648e9
badprng_constget16 = np.float64(-2.147483648e9)
# 
badprng_constrand  = np.float64(4.656612875e-10)

def badprng_intmath(v):
    # v = 00 00 80 74 56 c7 c4 41, cvttsd2si this
    # ecx/v2 = 0x298eace9
    v2 = np.uint32(v)
    v2 = v2.astype(np.float64).astype(np.int32)
    # v3 = (signed int)(v2 + ((unsigned __int64)(0xFFFFFFFF834E0B5Fi64 * v2) >> 32)) >> 16;
    v3 = np.uint32(v2) + np.int64((np.int64(-2092037281) * np.int64(v2)) >> np.int64(32))
    v3 = np.int32(np.int32(v3) >> np.uint32(16)) # shr upcasts to int64...
    # v4 = 16807 * v2 - 0x7FFFFFFF * (v3 + (v3 >> 31));
    v4 = np.int32( np.int32(16807) * np.int32(v2) - np.int32(0x7FFFFFFF) * (v3 + np.int32(np.uint32(v3) >> np.uint32(31))))

    if v4 <= 0:
        v4 += 0x7FFFFFFF
    return v4

def badprng_floatmath(v4):
    return np.float64(v4)*badprng_constrand

def testrng():
    for test in rngtests:
        v4 = badprng_intmath(test[0])
        if v4.view("u4") != test[1]:
            print("RNG test failed intmath result, input 0x{:08x} expected 0x{:08x} - got 0x{:08x}".format(
                test[0], test[1], v4.view("u4")
            ))
            IPython.embed()
        
        floatres = badprng_floatmath(v4)
        if floatres.view("u8") != test[2]:
            print("RNG test failed floatmath result, input 0x{:08x} expected 0x{:08x} - got 0x{:08x}".format(
                v4.view("u4"), test[2], floatres.view("u8")
            ))
            IPython.embed()

        print("RNG test passed: {}".format(test))

# get 1 value and update PRNG state
def badprng_nextfloat(prng):
    num_seed = prng["seed"].astype(np.int32) # -0x80...
    #IPython.embed()
    v4 = badprng_intmath(num_seed)
    prng["seed"] = np.float64(v4)
    floatres = badprng_floatmath(v4)
    return floatres

def badprng_init(seed):
    # hex(np.float64(0x165EC8F).view("u8"))
    # '0x41765ec8f0000000'
    # matches xmm0 as well.
    # fix it if it's signed.
    seed = np.float64(seed)
    return {"seed":seed}

def badprng_get16(int_seed):
    prng = badprng_init(int_seed)
    thrownaway = badprng_nextfloat(prng)

    bytes_result = b""
    for i in range(4):
        f = badprng_nextfloat(prng)*badprng_constget16
        bytes_result += struct.pack("I", f.astype(np.uint32))
    return bytes_result

if __name__ == "__main__":
    testrng()
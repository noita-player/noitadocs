# simple tool to apply a few different binary noita patches.
import logging, re, struct
import gevent
from pathlib import Path
from collections import defaultdict, deque, namedtuple
LOG = logging.getLogger()

def find_pattern_in_buffer(pattern: str, buffer: bytes):
    """
    pattern: "EB FE E8 ? ? ? ? 90 90 90 90"
    buffer: with open('file', 'rb') as f: buffer = f.read()

    returns a list of offsets the pattern occurs at
    """
    # todo, don't @ me
    try:
        bytere = b""
        for b in pattern.split(' '):
            if '?' in b:
                bytere += b"."
            else:
                bytere += struct.pack("B", int(b, base=16))

    except Exception as err:
        raise ValueError("Bad pattern format '{}' failed to parse with {}".format(pattern, err))
    #re.search(bytere,buffer)

    return [m.start(0) for m in re.finditer(bytere, buffer)]

def insert_shellcode(buffer: bytes, offset: int, payload: bytes):
    return buffer[0:offset] + payload + buffer[offset+len(payload):]

def patch_noita(game_path, component_docs=False):
    """ If patch failed, raises ValueError / NotImplementedError """
    buffer = None
    with open(game_path, 'rb') as infile:
        buffer = infile.read()

    # necessary for builds prior to 4308369
    if component_docs:
        # this is the argument handler for -write_documentation_n_exit
        locations_dump_components = find_pattern_in_buffer("74 12 68 ? ? ? ? E8 ? ? ? ? 83 C4 04 E9 ? ? ? ? 68 ? ? ? ? 8D", buffer)
        # this is the return after loading completes. should be able to patch this directly.
        locations_loading_ended   = find_pattern_in_buffer("80 3D ? ? ? ? ? 75 18", buffer)
        
        if len(locations_dump_components) > 1:
            LOG.warning("-write_documentation_n_exit found multiple pattern matches.")
        if len(locations_loading_ended) > 1:
            LOG.warning("on_load_complete found multiple pattern matches.")
        if len(locations_dump_components) == 0:
            err = "-write_documentation_n_exit pattern was not found."
            LOG.error(err)
            raise ValueError(err)
        if len(locations_loading_ended) == 0:
            err = "load completion pattern was not found."
            LOG.error(err)
            raise ValueError(err)
        
        # +2 because the pattern includes the jz before the push+call to dump components
        offset_dump_components = locations_dump_components[0]+2
        offset_loading_ended = locations_loading_ended[0]
        jmp_target = 0

        if offset_dump_components > offset_loading_ended:
            jmp_target = (offset_dump_components) - (offset_loading_ended+5)
        else:
            raise NotImplementedError("fix the jmp math, make all this its own function")

        # relative jmp from loading_finished to dump_components
        jmp_dump = b"\xE9" + struct.pack("I", jmp_target)
        buffer = insert_shellcode(buffer, offset_loading_ended, jmp_dump)

        # get rid of the fucking unskippable release notes popup ($menureleasenotes_eawarning)
        # note, this doesn't disable popup creation entirely... looks annoying to do that
        try:
            location_ret_me = find_pattern_in_buffer("56 E8 ? ? ? ? 6A 01 50", buffer)[0]
            buffer = insert_shellcode(buffer, location_ret_me, b"\xC3") # retn
        except KeyboardInterrupt:
            raise
        except:
            pass

    new_file = str(game_path.resolve()) + ".patched.exe"
    with open(new_file, 'wb') as ofile:
        ofile.write(buffer)
    return Path(new_file)

#patch_noita(r"./noitadocs/tools/updatewatcher/archive/881100_4281899_noitabeta_mods/noita.exe", component_docs=True)

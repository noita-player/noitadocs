#!/usr/bin/env python2
# ^^^ very important, don't forget
from collections import defaultdict
import logging
import idaapi, idautils, idc

logging.basicConfig(format="%(asctime)s:%(levelname)s:ida_noita| %(message)s", level=logging.DEBUG)
LOG = logging.getLogger()

headless = True
rename_lua_natives = False
sig_lua_register_global = "55 8B EC 56 8B F1 6A 00 FF 75 0C"
all_strings = None

class LuaGlobalInfo():
    def __init__(self, registered_fn, registered_at, name, native_addr, docstr):
        self.registered_fn = registered_fn
        self.registered_at = registered_at
        self.name = name
        self.docstr = docstr
        self.native_addr = native_addr
    def to_dict(self):
        return {'registered_fn': self.registered_fn,
                'registered_at': self.registered_at,
                'name': self.name,
                'docstr': self.docstr,
                'native_addr': self.native_addr}
    def __str__(self):
        return str(self.to_dict())

def find_all_pattern(pat):
    first = idc.FirstSeg()
    last = idc.BADADDR
    result = []

    ea = idaapi.find_binary(first, last, pat, 16, idaapi.SEARCH_DOWN)
    while ea != idaapi.BADADDR and ea < last:
        result.append(ea)
        ea = idaapi.find_binary(ea, last, pat, 16, idaapi.SEARCH_DOWN|idaapi.SEARCH_NEXT)

    return result

def get_func_start(ea):
    return idc.GetFunctionAttr(ea, idc.FUNCATTR_START)

def get_first_string(ea):
    """ walk up and grab a string like this
    push    offset aGamegetpotionc ; "GameGetPotionColorUint"
    lea     ecx, [ebp+var_244] ; int
    call    makestr
    push    offset sub_435ADA
    lea     eax, [ebp+var_244]
    mov     ecx, esi
    push    eax
    call    register_global ; <---- ea
    """
    maybe_start = idc.get_func_attr(ea, idc.FUNCATTR_START)
    limit = 0
    if maybe_start == idc.BADADDR:
        limit = 10

    cur_ea = ea
    limit_count = 0
    while cur_ea != idc.BADADDR:
        # are we over limit or up to the func start?
        limit_count += 1
        limit_exceeded = (limit > 0 and limit_count > limit)
        too_far = (maybe_start != idc.BADADDR and cur_ea < maybe_start)
        if limit_exceeded or too_far:
            LOG.error("Failed to find string walking backwards from {:08X}".format(ea))
            return None

        prev_ins = idautils.DecodePreviousInstruction(cur_ea)
        prev_ea = prev_ins.ea

        # did we find it?
        if idc.GetMnem(prev_ea) == 'push':
            if idc.get_operand_type(prev_ea,0) in [idc.o_mem, idc.o_imm]:
                # push offset found!
                pushed_addr = idc.GetOperandValue(prev_ea, 0)
                if idc.isASCII(idc.GetFlags(pushed_addr)):
                    s = idc.GetString(pushed_addr, -1, idc.ASCSTR_C)
                    #LOG.debug("Read string {} from {:08X} from instruction at {:08X}".format(repr(s), pushed_addr, prev_ea))
                    return s

        cur_ea = prev_ea

def get_first_function(ea):
    """ see above, but returns the first pushed value """
    maybe_start = idc.get_func_attr(ea, idc.FUNCATTR_START)
    limit = 0
    if maybe_start == idc.BADADDR:
        limit = 10

    cur_ea = ea
    limit_count = 0
    while cur_ea != idc.BADADDR:
        # are we over limit or up to the func start?
        limit_count += 1
        limit_exceeded = (limit > 0 and limit_count > limit)
        too_far = (maybe_start != idc.BADADDR and cur_ea < maybe_start)
        if limit_exceeded or too_far:
            LOG.error("Failed to find string walking backwards from {:08X}".format(ea))
            return None

        prev_ins = idautils.DecodePreviousInstruction(cur_ea)
        prev_ea = prev_ins.ea

        # did we find it?
        if idc.GetMnem(prev_ea) == 'push':
            if idc.get_operand_type(prev_ea,0) in [idc.o_mem, idc.o_imm]:
                # push offset found!
                pushed_addr = idc.GetOperandValue(prev_ea, 0)
                # it's not data, then probably good
                if idc.isCode(idc.GetFlags(pushed_addr)):
                    return pushed_addr

        cur_ea = prev_ea

def get_all_second_level_xrefs(ea):
    """ handle situations like this, where we want to know when real_fn is used
    main_game_fn:
    0: call 1 <thunk_real_fn>
    thunk_real_fn:
    1: jmp 2 <real_fn>
    real_fn:
    2: push ebp ....
    """

    refs = []
    for first_level in idautils.XrefsTo(long(ea)):
        #print(type(first_level), repr(first_level), dir(first_level))
        for second_level in idautils.XrefsTo(first_level.frm):
            refs.append(second_level)
    return refs

def find_funcs_calling(s):
    result = []
    first_pass = []
    try:
        for functionAddr in idautils.Functions():    
            if s in idc.GetFunctionName(functionAddr):
                for x in idautils.XrefsTo(functionAddr):
                    #first_pass.extend(list(idautils.XrefsTo(functionAddr)))
                    first_pass.append(x.frm)

        # we need to get the function start to search for xrefs to this caller-func
        for r in first_pass:
            ea = idc.get_func_attr(r, idc.FUNCATTR_START)
            if ea != idc.BADADDR:
                result.append(ea)
            else:
                LOG.warning("find_funcs_calling failed to resolve xref of {} to fn at {:08X}".format(
                    s,
                    r
                ))
    except:
        LOG.error("error in find_funcs_calling")
        return result
    return result

def get_all_registered_lua_natives():
    """ Returns {func_ea: [LuaGlobalInfo(), LuaGlobalInfo(), ...], ...} """
    result = {}
    
    # there's one fn that is called to register every global.
    #res = find_all_pattern(sig_lua_register_global)
    res = find_funcs_calling("lua_pushcclosure")
    print(res)
    if len(res) > 1:
        LOG.warning("Found multiple lua_register_global definitions, only using first.")
    elif len(res) == 0:
        errstr = "Failed to find pattern for lua_register_global {}".format(sig_lua_register_global)
        LOG.error(errstr)
        raise ValueError(errstr)

    docstr_needed = defaultdict(lambda: None)
    
    for lua_register_global in res:
        LOG.info("lua_register_global at {}".format(lua_register_global))
        register_global_xrefs = get_all_second_level_xrefs(lua_register_global)

        # get simple metadata in first pass, no docstr
        for xref in register_global_xrefs:
            #LOG.debug("lua_global_register call: {:08X}".format(int(xref.frm)))
            called_in_fn = idc.get_func_attr(xref.frm, idc.FUNCATTR_START)

            try:
                fn_name = get_first_string(xref.frm)
            except:
                LOG.error("failed to find string for lua_global_register call: {:08X}".format(int(xref.frm)))
                continue

            try:
                fn_addr = get_first_function(xref.frm)
            except:
                LOG.error("failed to find func for lua_global_register call: {:08X}".format(int(xref.frm)))
                continue
            
            #LOG.debug("registers ({},{:08X})".format(fn_name, fn_addr))
            docstr_needed[fn_name] = None

            lua_obj = LuaGlobalInfo(called_in_fn, xref.frm, fn_name, fn_addr, None)

            # add a new func that registers lua globals, or append if we already did.
            if called_in_fn in result.keys():
                result[called_in_fn].append(lua_obj)
            else:
                result[called_in_fn] = [lua_obj]

        # loop all strings once to save some time
        search_for = docstr_needed.keys()
        for s in all_strings:
            s = str(s)
            for entry in search_for:
                # probably the docstring? whatever
                if( entry in s and 
                    "(" in s and ")" in s and
                    s.index(")") - s.index("(") > 2 and # () isn't a docstr
                    "..." not in s                      # (...) is used in error msgs
                    ):
                    docstr_needed[entry] = s
                    break # out of docstr iteration
    
    # update any results
    for called_in, lua_list in result.iteritems():
        for obj in lua_list:
            obj.docstr = docstr_needed[obj.name]

    # remove the defaultness to allow ez serialization
    return dict(result)

LOG.info("Noita IDAPython init")
idaapi.auto_wait()
LOG.info("analysis finished")
idb_path = idautils.GetIdbDir()+"noita_auto.idb"
LOG.info("saving IDB to {}".format(idb_path))
#idaapi.save_database(idb_path)

all_strings = idautils.Strings()

# do something useful?
lua_natives = get_all_registered_lua_natives()

# person who started IDA defined where the log file is, so they can parse this out of it.
# import ast; natives_fromlogs = ast.literal_eval(x.split("|lol|")[1])
# ...py3, need to re.sub(r"(\d+)L,", "\\1,", x)
natives_fordisk = []
for caller,natives in lua_natives.iteritems():
    natives_fordisk.extend([o.to_dict() for o in natives])

LOG.info("|lol|{}|lol|".format(str(natives_fordisk)))

idaapi.save_database(idb_path)
if headless:
    idaapi.quit(0)

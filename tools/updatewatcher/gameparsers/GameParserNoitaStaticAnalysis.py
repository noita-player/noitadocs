import gevent
import gevent.subprocess

import logging, re, traceback, time, os, shutil, ast
from pathlib import Path
from collections import defaultdict, deque, namedtuple

try:
    from gameparsers.gameparser import GameParser
    from gameparsers.noitapatcher import patch_noita
except:
    from gameparser import GameParser
    pass

LOG = logging.getLogger()

class GameParserNoitaStaticAnalysis(GameParser):
    def __init__(self, game_path, storage_path):
        LOG.info("[GameParserNoitaStaticAnalysis] started v2")
        self.finished = False
        self.game_path = game_path
        self.storage_path = storage_path
        self.ida_path = r"C:\tools\idapro7\ida.exe"
        self.start_time = time.time()
        self.threads = []
        self.errors = []

        if not Path(self.storage_path).exists():
            LOG.info("Created storage path: {}".format(self.storage_path))
            Path(self.storage_path).mkdir(parents=True, exist_ok=True)

        if not Path(self.ida_path).exists():
            raise Exception("IDA installation not found at {}".format(self.ida_path))

        # gevent will pass self automagically.
        self.threads.append(gevent.spawn(self.worker))
    def get_changes(self):
        if not self.finished:
            LOG.error("getting changes before parsing finished")
            return None
        return self.result
    def get_result(self):
        if not self.finished:
            LOG.error("getting changes before parsing finished")
            return None
        return self.result
    def write_lua_global_result(self, lua_globals):
        path_dump_literal = Path(self.storage_path) / Path("lua_dump_raw.txt")
        path_dump_human = Path(self.storage_path) / Path("lua_dump.txt")

        # like json but more direct
        # |lol|....data....|lol|
        lua_globals = lua_globals.split("|lol|")[1]
        # idapython is py2, need to remove "L" from numbers to parse as a literal
        lua_globals = re.sub(r" (\d+)L", "\\1", lua_globals)

        with open(path_dump_literal, 'w') as f:
            f.write(lua_globals)
        self.result.append(str(path_dump_literal.absolute()))

        lua_globals = ast.literal_eval(lua_globals)
        # okay now we have [{'native_addr': 1, 'registered_fn': 1, 'registered_at': 1, 'docstr': None, 'name': 'LUI_whatever'}, ...]
        
        humanized = []
        for fn in lua_globals:
            if fn['docstr']:
                humanized.append(fn['docstr'])
            else:
                humanized.append(fn['name'])
        humanized.sort()
        with open(path_dump_human, 'w') as f:
            for v in humanized:
                f.write("{}\n".format(v))
        self.result.append(str(path_dump_human.absolute()))

    def launch_ida_and_wait(self, game_bin):
        ida_cfg_replaced = self.ida_cfg_install()

        try:
            time_start = time.time()
            time_last  = time_start

            ida_logs = Path(game_bin.with_suffix(".idalog")).absolute()
            ida_script = Path("./gameparsers/ida_noita.py").absolute()
            # -A is autonomous mode, -S is a script to exec, -L is where to write log
            ida_args = ["-A",
                        "-S{}".format(ida_script), # todo: how does this work with spaces
                        "-L{}".format(ida_logs),
                        "{}".format(game_bin)]

            ida_args.insert(0, self.ida_path)

            LOG.info("[GameParserNoitaStaticAnalysis] Starting IDA with args: {}".format(ida_args))
            ida_proc = gevent.subprocess.Popen(ida_args, cwd=str(game_bin.parent.resolve()))

            # wait for IDA
            while ida_proc.poll() is None:
                # we probably don't need to timeout, ida is flawless.
                curtime = time.time()
                if curtime - time_last > 30:
                    LOG.info("ida anlysis still running on {} at {}".format(self.game_path, curtime))
                    time_last = curtime
                gevent.sleep(1)
        except:
            # Don't fuck up  IDA's cfgs no matter what happens
            if ida_cfg_replaced:
                ida_cfg_replaced = False
                self.ida_cfg_reset()
            raise
    
        if ida_cfg_replaced:
            self.ida_cfg_reset()

        return
    def worker(self):
        game_bin = Path(self.game_path) / Path("noita.exe")
        cached_idb = Path(self.game_path) / Path("noita_auto.idb")
        self.result = []

        if not game_bin.exists():
            LOG.error("staticanalysis failed to find game at {}".format(game_bin))
            self.finished = True
            return

        # re-use the idb if it exists, duh
        if cached_idb.exists():
            LOG.info("new Re-using IDB at {}".format(cached_idb))
            game_bin = cached_idb

        self.launch_ida_and_wait(game_bin.absolute())
        # ida ran, handle results
        idalog = game_bin.with_suffix(".idalog")
        if idalog.exists():
            with open(str(idalog), 'r') as f:
                idalog = f.read()

            self.write_lua_global_result(idalog)
        else:
            LOG.warning("Failed to find IDA log after analysis run.")            

        self.finished = True
        return

    def ida_cfg_install(self):
        # don't do anything if files are fucked up
        new_cfg_path = Path("ida_fast.cfg")
        if not new_cfg_path.exists():
            LOG.warning("Couldn't find fast ida cfg, going ahead with regular cfg")
            return False

        # back up existing cfg
        cfg_path = Path(self.ida_path).parent / Path("cfg/ida.cfg")
        cfg_path_bak = cfg_path.with_suffix(".parser_bak")
        if cfg_path.exists():
            LOG.info("backing up IDA config: {}".format(cfg_path))
            # uhh, this shouldn't exist. let's preserve it just in case it's a backup of a user's custom config
            if cfg_path_bak.exists():
                cfg_path_bak.rename(cfg_path_bak.with_suffix(".{}".format(self.start_time)))
            cfg_path.rename(cfg_path_bak)
        
        # overwrite the cfg
        shutil.copy2(str(new_cfg_path), str(cfg_path.absolute()))
        LOG.info("Replaced ida cfg with ida_fast")
        return True
    def ida_cfg_reset(self):
        cfg_path = Path(self.ida_path).parent / Path("cfg/ida.cfg")
        cfg_path_bak = cfg_path.with_suffix(".parser_bak")

        if not cfg_path_bak.exists():
            LOG.warning("Couldn't find idacfg backup? Not resetting. {}".format(cfg_path_bak.resolve()))
            return

        shutil.copy2(str(cfg_path_bak.resolve()), str(cfg_path.resolve()))
        LOG.info("Restored original ida cfg.")
        os.remove(str(cfg_path_bak.resolve()))
        return

# test code
if __name__ == '__main__':
    logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s| %(message)s", level=logging.DEBUG)
    LOG = logging.getLogger()

    waiters = []
    vers = ["4293634","4301535","4307942","4308369","4308554","4308683"]
    for v in vers:
        indir = "./archive/881100_{}_noitabeta".format(v)
        outdir = (indir + "_GameParserNoitaStaticAnalysis")
        LOG.info("running {}".format(v))
        x = GameParserNoitaStaticAnalysis(indir, outdir )#r"./archive/881100_4301535_noitabeta", r"./archive/tmp")
        waiters.append(x)
    while len(waiters) > 0:
        for idx,x in enumerate(waiters):
            if x.finished:
                LOG.info("ida finished,\nresult: {}\nerrors: {}".format(x.result, x.errors))
                del waiters[idx]
        gevent.sleep(1)

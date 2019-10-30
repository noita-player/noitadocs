import gevent
import gevent.subprocess

import logging, re, traceback, time, os, shutil
from pathlib import Path
from collections import defaultdict, deque, namedtuple

from gameparsers.gameparser import GameParser
LOG = logging.getLogger()

class GameParserNoitaStrings(GameParser):
    ASCII_BYTE = " !\"#\$%&\'\(\)\*\+,-\./0123456789:;<=>\?@ABCDEFGHIJKLMNOPQRSTUVWXYZ\[\]\^_`abcdefghijklmnopqrstuvwxyz\{\|\}\\\~\t\n"
    String = namedtuple("String", ["s", "offset"])

    def __init__(self, game_path, storage_path):
        LOG.info("grabbing strings")
        self.finished = False
        self.game_path = game_path
        self.storage_path = storage_path
        self.threads = []
        self.errors = []
        self.result = []
        # gevent will pass self automagically.
        self.threads.append(gevent.spawn(self.strings_worker))
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
    def strings_worker(self):
        game_bin = Path(self.game_path) / Path("noita.exe")
        self.result = []

        if not game_bin.exists():
            LOG.error("string parser failed to find game at {}".format(game_bin))
            self.finished = True
            return
        
        with open(game_bin, 'rb') as game_file:
            game_buffer = game_file.read()
            for s in self.strings(game_buffer):
                self.result.append(s.s)

        self.result.sort()
        out_path = self.storage_path / "strings.txt"
        if not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w") as out_file:
            out_file.write("\n".join(self.result))

        self.result = [str(out_path.resolve())]
        self.finished = True
        return

    # https://stackoverflow.com/questions/17195924/python-equivalent-of-unix-strings-utility
    # todo, this code fucking sucks
    def strings(self, buf, min=4):
        reg = bytes("([%s]{%d,})" % (self.ASCII_BYTE, min), "ascii")
        ascii_re = re.compile(reg)
        for match in ascii_re.finditer(buf):
            yield self.String(match.group().decode("ascii"), match.start())

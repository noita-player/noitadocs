import gevent
import gevent.subprocess

import logging, re, traceback, time, os, shutil, hashlib
from pathlib import Path
from collections import defaultdict, deque, namedtuple

from gameparsers.gameparser import GameParser
from gameparsers.noitapatcher import patch_noita
LOG = logging.getLogger()

class GameParserNoitaRuntimeAnalysis(GameParser):
    def __init__(self, game_path, storage_path):
        LOG.info("runtime analysis started")
        self.finished = False
        self.game_path = Path(game_path)
        self.storage_path = Path(storage_path)
        self.threads = []
        self.errors = []
        # gevent will pass self automagically.
        self.threads.append(gevent.spawn(self.runtime_worker))

        if not Path(self.storage_path).exists():
            LOG.info("Created storage path: {}".format(self.storage_path))
            Path(self.storage_path).mkdir(parents=True, exist_ok=True)

    # utility functions
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
    def launch_game_and_wait(self, game_args, timeout=25): # timeout in seconds
        time_start = time.time()
        game_proc = gevent.subprocess.Popen(game_args, cwd=str(Path(self.game_path).resolve()))

        while game_proc.poll() is None:
            if time.time() - time_start > timeout:
                game_proc.kill()
                errmsg = "RuntimeAnalysis: timeout waiting for noita to close, killing"
                self.errors.append(errmsg)
                LOG.error(errmsg)
                break
            gevent.sleep(2)
        return

    def copytree(self, source, dest):
        """ copytree+overwrite """
        for root, dirs, files in os.walk(source):
            if not os.path.isdir(root):
                os.makedirs(root)
            for file in files:
                rel_path = root.replace(source, '').lstrip(os.sep)
                dest_path = os.path.join(dest, rel_path)
                if not os.path.isdir(dest_path):
                    os.makedirs(dest_path)
                shutil.copyfile(os.path.join(root, file), os.path.join(dest_path, file))
    def copytree_to_storage(self, s):
        if type(s) is str:
            s = Path(s)
        if not s.is_dir():
            raise ValueError("can't copytree if not a dir: {}".format(s))
        new_path = Path(self.storage_path) / s.name
        self.copytree(str(s), str(new_path))
        return new_path
    def copy_to_storage(self, s):
        if type(s) is str:
            s = Path(s)
        new_path = Path(self.storage_path) / s.name
        shutil.copy2(str(s), str(new_path))
        return new_path
    def sha1sum(self, filename):
        h  = hashlib.sha1()
        b  = bytearray(128*1024)
        mv = memoryview(b)
        with open(filename, 'rb', buffering=0) as f:
            for n in iter(lambda : f.readinto(mv), 0):
                h.update(mv[:n])
        return h.hexdigest()
    def get_tree(self, root):
        result = []
        # recursive generator for all files
        all_items = Path(root).rglob("*")
        # we want to yank their path relative to root
        oldcwd = os.getcwd()
        os.chdir(root)
        for entry in all_items:
            rel_name = entry.relative_to(root)
            if entry.is_dir():
                result.append("{} dir".format(rel_name))
            else:
                file_hash = self.sha1sum(entry)
                result.append("{} {}".format(rel_name, file_hash))
        os.chdir(oldcwd)
        result.sort()
        return result

    # utility functions above, actions we need to run the game during below.
    def try_component_docs(self, game_bin):
        """ Patch the game for versions prior to oct21, or trust their shipped doc. """
        new_file = ""
        try:
            new_file = patch_noita(game_bin, component_docs=True)
            self.launch_game_and_wait(str(new_file.resolve()))

            docs_path = Path(self.game_path) / "docs/component_documentation.txt" 
            if not docs_path.exists():
                err = "runtimeanalysis failed to get component documentation for {}".format(new_file)
                LOG.error(err)
                return

            self.result.append(str(docs_path.absolute()))
        except (ValueError, NotImplementedError) as err:
            errmsg = "(not a problem after oct21) failed to patch noita for component_docs: {}".format(''.join(
                traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__)
                ))
            LOG.debug(errmsg)

        # oct 21 2019 beta patch introduces this
        new_file = Path(self.game_path) / "tools_modding/component_documentation.txt"
        if new_file.exists():
            s = self.copy_to_storage(new_file)
            self.result.append(str(s.absolute()))
        return

    def try_datawak(self, game_bin):
        """ appdata _must_ be cleaned, we use their extractor for now """
        self.launch_game_and_wait([str(game_bin.resolve()), "-wizard_unpak"])

        # Did it unpak successfully?
        unpak_path = Path(os.getenv(r"userprofile")+"/AppData/LocalLow"+"/Nolla_Games_Noita/data")
        if not unpak_path.exists():
            err = "wizard_unpak had no result at {}".format(unpak_path)
            LOG.error(err)
            return

        # Generate a tree list with hashes for ez "what changed" on git
        tree_path = self.storage_path / "datawak_tree.txt"
        with open(tree_path, 'w') as f:
            tree = self.get_tree(unpak_path)
            f.write('\n'.join(tree))
        self.result.append(str(tree_path.absolute()))

        # Store this shit away until we figure out something to do with it
        self.copytree_to_storage(unpak_path)
        return

    def try_releasenotes(self, game_bin):
        """ make sure the game was run before this one in case they update these dynamically
        todo: please god reverse how this relates to https://noitagame.com/release_notes/
        """
        notes_path = Path(self.game_path) / "_release_notes.txt" 
        if not notes_path.exists():
            err = "error, failed to find release notes: {}".format(notes_path)
            LOG.error(err)
            return

        self.copy_to_storage(notes_path)
        self.result.append(str(notes_path.absolute()))
        return

    def runtime_worker(self):
        game_bin = Path(self.game_path) / Path("noita.exe")
        self.result = []

        if not game_bin.exists():
            LOG.error("runtimeanalysis failed to find game at {}".format(game_bin))
            self.finished = True
            return

        def rm_tree(pth):
            pth = Path(pth)
            for child in pth.glob('*'):
                if child.is_file():
                    child.unlink()
                else:
                    rm_tree(child)
            pth.rmdir()

        # If a certain file exists, a bunch of blocking popups can happen on game start that I don't want to patch out.
        appdata = Path(os.getenv(r"userprofile")+"/AppData/LocalLow"+"/Nolla_Games_Noita")
        appdata_disabled = appdata.with_suffix(".disabled")
        swapped_appdata = False
        if appdata.exists():
            LOG.info("Found [appdata: {}][appdata_disabled: {}]".format(appdata, appdata_disabled))
            if appdata_disabled.exists():
                LOG.info("Deleting appdata_disabled: ")
                rm_tree(appdata_disabled)
            
            LOG.info("Renamed [appdata: {}] to appdata_disabled".format(appdata))
            #shutil.copytree(str(appdata.resolve(strict=False)), 
            #                str(appdata_disabled.resolve(strict=False)))
            appdata.rename(appdata_disabled)
            swapped_appdata = True
            # remove one file to prevent save detected popup and skip intro
            #  save00\world\.stream_info 
            try:
                os.remove(str(Path(os.getenv(r"userprofile")+"/AppData/LocalLow"+"/Nolla_Games_Noitasave00/world/.stream_info")))
            except KeyboardInterrupt:
                raise
            except Exception as err:
                LOG.info("Did not delete .stream_info, error: {}".format(err))

        # At this point, the game is prep'd to run (appdata fixed, whatever else)
        try:
            self.try_component_docs(game_bin)
            self.try_datawak(game_bin)
            self.try_releasenotes(game_bin)
        except KeyboardInterrupt:
            raise
        except Exception as err:
            LOG.error("Error during runtime analysis: {}".format(''.join(traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__))))

        # Cleanup!
        if appdata.exists():
            LOG.info("Deleting temp appdata: {}".format(appdata))
            rm_tree(appdata)
        if swapped_appdata:
            LOG.info("Renaming orig {} to {}".format(appdata_disabled, appdata))
            appdata_disabled.rename(appdata)
        self.finished = True
        return

# test code
if __name__ == '__main__':
    logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s| %(message)s", level=logging.DEBUG)
    LOG = logging.getLogger()

    waiters = [] # "4293634",
    vers = ["4301535","4307942","4308369","4308554","4308683","4315272","4315340","4315794","4316127","4323807","4335384", "4336782"]
    for v in vers:
        indir = "./archive/881100_{}_noitabeta".format(v)
        outdir = (indir + "_GameParserNoitaRuntimeAnalysis")
        LOG.info("running {}".format(v))
        x = GameParserNoitaRuntimeAnalysis(indir, outdir)
        waiters.append(x)
        gevent.joinall(x.threads)
        LOG.info("completed!")
        #import sys
        #sys.exit(1)
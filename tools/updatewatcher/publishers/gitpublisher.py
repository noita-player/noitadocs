import gevent
import gevent.subprocess

import logging, re, traceback, time, os, shutil, ast
from pathlib import Path
from collections import defaultdict, deque, namedtuple

LOG = logging.getLogger()

class GitPublisher:
    """ shove a bunch of shit into a folder, commit, push? zzz """
    def __init__(self, appid, steam_branch, version, results=[]):
        self.app_id = str(appid)
        self.app_branch = str(steam_branch)
        self.app_version = str(version)
        # an array of paths to things we're publishing
        self.paths = results
        # the repo we're publishing to, set this up ahead of time.
        self.repo = "./data/gitpublisher/{}".format(appid)
        # you published something(s) somewhere, tell people about it by putting it here.
        self.result = []
        if not Path(self.repo).exists():
            raise ValueError("Git repo path invalid: {}".format(self.repo))
        for p in self.paths:
            if not Path(p).exists():
                LOG.warning("Git publisher was given a non-extant path: {}".format(p))

    def add_result(self, result):
        if not Path(result).exists():
            LOG.warning("Git publisher was given a non-extant path: {}".format(result))
        self.paths.append(result)

    def store_state(self):
        """ cwd, env, what else? """
        self.old_cwd = os.getcwd()
    def restore_state(self):
        os.chdir(self.old_cwd)

    def publish(self):
        """ done adding things to it, publish! """
        branch_dir = Path(self.repo) / self.app_branch
        if not branch_dir.exists():
            branch_dir.mkdir(parents=True, exist_ok=True)
        
        # remove any existing files so that we commit deletions
        def rm_tree(pth, root=True):
            pth = Path(pth)
            for child in pth.glob('*'):
                if child.is_file():
                    child.unlink()
                else:
                    rm_tree(child, False)
            if not root: pth.rmdir()
        #rm_tree(branch_dir)

        # copy the data in
        for p in self.paths:
            if not Path(p).exists():
                LOG.warning("path does not exist for publishing: {}".format(p))
                continue

            # copy and overwrite into the repo
            shutil.copy2(str(p), str(branch_dir))
        
        # commit it
        commit_message = "updated {} {}".format(self.app_branch, self.app_version)
        self.store_state()
        os.chdir(str(branch_dir))
        os.system("git add -A")
        os.system('git commit --allow-empty -m "{}"'.format(commit_message))
        os.system("git push origin master")
        self.restore_state()
        return

# test code
if True and __name__ == '__main__':
    logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s| %(message)s", level=logging.DEBUG)
    LOG = logging.getLogger()

    # simulate some updates
    commitme = []
    parsers = [
        "GameParserNoitaRuntimeAnalysis/_release_notes.txt",
        "GameParserNoitaRuntimeAnalysis/datawak_tree.txt",
        "GameParserNoitaRuntimeAnalysis/component_documentation.txt",
        "GameParserNoitaStaticAnalysis/lua_dump.txt"]
    vers = ["4293634","4301535","4307942","4308369","4308554","4308683","4315272","4315340","4315794","4316127","4323807","4335384","4336782"]
    for ver in vers:
        res = []
        for p in parsers:
            res.append("./archive/881100_{}_noitabeta_{}".format(ver,p))
        commitme.append((
            "881100",
            "noitabeta",
            ver,
            res
        ))
 
    for commit in commitme:
        LOG.info("committing {}".format(commit))
        x = GitPublisher(commit[0],commit[1],commit[2],results=commit[3])
        x.publish()
    LOG.info("finished")
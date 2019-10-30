import gevent
from gevent import monkey

#from gevent.threadpool import ThreadPoolExecutor
from gevent.pool import Pool as GPool

from gevent.fileobject import FileObject
#monkey.patch_ssl()

from steam.exceptions import SteamError
import logging, re, string, time, timeago, traceback, pickle
import IPython
from pathlib import Path
from collections import defaultdict, deque, namedtuple
from multiprocessing import Process, Queue # just for quarantining discord

from secrets import user, passwd

LOG = logging.getLogger()

# class these out so we can treat them like enums and take diff actions on certain changes
class CDNEvent():
    def __init__(self):
        return
class CDNEvent_ProductInfoChange(CDNEvent):
    def __init__(self, old_info, new_info):
        self.old_info = old_info
        self.new_info = new_info
    def __str__(self):
        return "app info change: {} to {}".format(self.old_info, self.new_info)
class CDNEvent_ManifestChange(CDNEvent):
    def __init__(self, old_manifest, new_manifest):
        self.old_manifest = old_manifest
        self.new_manifest = new_manifest
    def __str__(self):
        return "manifest change: {} to {}".format(self.old_manifest, self.new_manifest)
class CDNEvent_BranchChange(CDNEvent):
    """ (branch_name, old_branchinfo, new_branchinfo) """
    def __init__(self, branch_name, old_branchinfo, new_branchinfo):
        self.branch_name    = branch_name
        self.old_branchinfo = old_branchinfo
        self.new_branchinfo = new_branchinfo
    def __str__(self):
        return "change on branch {}: {} to {}".format(self.branch_name, self.old_branchinfo, self.new_branchinfo)
    def buildid_changed(self):
        if self.old_branchinfo['buildid'] != self.new_branchinfo['buildid']:
            return True
        return False

def thread_init():
    from gevent import monkey
    monkey.patch_all()

def async_download_file(out_dir, f):
    size_skip = 100000000 # > 100mb for noita is sound and shit
    names_skip = ["neverskip"]#[".png", "translations", "fonts", "audio"]
    #LOG.info("Handling {}".format(f))
    #for f in all_files:
    f_path = out_dir / Path(f.filename)
    if f.is_directory:
        f_path.mkdir(parents=True, exist_ok=True)
    else:
        # handle data/test/file.txt where test doesn't exist yet
        if not f_path.parent.exists():
            f_path.parent.mkdir(parents=True, exist_ok=True)
        #print(f_path)
        # flush it down unless we're skipping this type
        if not any([(n in f.filename) for n in names_skip]):
            with open(f_path, 'wb') as fout:
                fout = FileObject(fout)
                if size_skip > f.size:
                    fout.write(f.read())
                else:
                    fout.write(b"")
    gevent.sleep()
    return True

def do_nothing(): return None

# one per appid
class CDNScraper():
    def handle_error(self, msg):
        LOG.error(msg)

    # this is actually a noita-specific method. whatever. refactor later.
    # called when a branch update is seen.
    def default_update_handler(self, manifest, branch_info, branch_name):
        # we return async results all the way up.
        promises = []

        # can't download a branch with no manifest
        if manifest is None or len(manifest) == 0:
            LOG.info("No manifest for branch {}:{}, skipping file download.".format(branch_name, branch_info))
            return []
        
        build_folder_name = "{}_{}_{}".format(self.appid,branch_info['buildid'],branch_name)
        out_dir = self.download_directory / Path(build_folder_name)
        if not out_dir.is_dir():
            out_dir.mkdir(parents=True, exist_ok=True)

        # noita only has <CDNDepotManifest('Noita Content', app_id=881100, depot_id=881101, gid=8897187370775608456, creation_time='2019-10-11 15:27:55')>
        manifest_pulled = self.cdnapi.get_manifest(manifest['app_id'], manifest['depot_id'], manifest['gid'])
        all_files = list(manifest_pulled.iter_files())
        LOG.info("[+] Downloading {} - {} files to {}".format(branch_name, len(all_files), out_dir))

        # per-file threading breaks gevent.ThreadPool
        if True:
            for f in all_files:
                if True: # dl_async
                    #promises.append(self.download_pool.apply_async(async_download_file, (out_dir, f)))
                    promises.append(self.download_pool.spawn(async_download_file, *(out_dir, f)))
                else:
                    promises.append(gevent.spawn(do_nothing))
                    async_download_file(out_dir, f)
        #promises.append(self.download_pool.submit(async_download_file, *(out_dir, all_files)))
        #IPython.embed()
        
        return promises

    def get_manifests(self, appid, branch=None, retries=5):
        """ Handle CDN errors :( """
        while retries > 0:
            try:
                retries -= 1
                api_result = self.cdnapi.get_manifests(appid, branch=branch)
                return api_result
            except KeyboardInterrupt:
                raise
            except Exception as err:
                LOG.error("[get_manifests][{}][{}][{} tries left] got error:\n{}".format(
                        appid,
                        branch,
                        retries,
                        ''.join(traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__))
                        ))

    def check_for_updates(self):
        """
        1. Pull game's depotinfo
        2. Iterate the branches, update the logged branch-manifest pair.
        3. Return a list of branches with changes.
        """
        branches_updated = {}

        # bug, this API returns the cached value.
        # depotinfo = self.cdnapi.get_app_depot_info(self.appid)
        depotinfo = None
        public_buildid = None
        try:
            depotinfo = self.cdnapi.steam.get_product_info([self.appid])['apps'][self.appid]['depots']
            public_buildid = depotinfo["branches"]["public"]["buildid"]
        except KeyboardInterrupt:
            raise
        except Exception as err:
            self.handle_error(''.join(traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__)))
            return []


        for branch in depotinfo["branches"]:
            # passworded branches only have branchinfo, not manifests
            has_pw_field = "pwdrequired" in depotinfo["branches"][branch].keys()
            if ( not has_pw_field or (has_pw_field and depotinfo["branches"][branch]["pwdrequired"] == '0') ):
                # note for the future, apparently if your branch buildid matches master it has no manifest of its own.
                try:
                    api_result = self.get_manifests(self.appid, branch=branch)
                except KeyboardInterrupt:
                    raise
                except SteamError as err:
                    LOG.error("Branch manifest download failed, skipping: {}".format(err))
                    continue
                LOG.debug("[{}] get_manifests got: {}".format(branch, api_result))
                api_result = [x for x in api_result if x.app_id == self.appid]
                if len(api_result) != 0:
                    # todo: what do we do if we want to track all manifests...
                    if len(api_result) > 1:
                        LOG.warning("[CDNScraper][check_for_updates][{}] found multiple manifests, only using the first: {}".format(branch, api_result))
                    api_result = api_result[0]
                    # we can't store the entire CDNDepotManifest, it's a complex object with steam client state. let's just track these fields.
                    self.current_branchmanifests[branch] = {
                        'name': api_result.name,
                        'app_id': api_result.app_id,
                        'depot_id': api_result.depot_id,
                        'gid': api_result.gid,
                        'creation_time': api_result.creation_time
                        }
                else:
                    if depotinfo["branches"][branch]["buildid"] != public_buildid:
                        LOG.error("[{}] failed to grab manifests and branch isn't equal to public:\n{}".format(branch, depotinfo))
                        LOG.error("[{}] get_manifests got: {}".format(branch, api_result))
                        # todo: if there's no manifest for this branch but buildid matches another branch, steam just... intuits that the other branch's manifest is OK.

                LOG.debug("[{}] found manifests: {}".format(branch, self.current_branchmanifests[branch] ))

            # {'buildid': '4258732', 'description': 'the press build', 'pwdrequired': '1', 'timeupdated': '1570222226'}
            branch_info = depotinfo["branches"][branch]
            # let's pretend any change at all is an update for now
            if branch_info != self.last_branchinfo[branch]:
                LOG.info("Branch {} update found:\nold: {}\nnew: {}".format(branch, self.last_branchinfo[branch], branch_info))
                branches_updated[branch] = branch_info


        # update "last" values for next run.
        self.last_depotinfo = depotinfo
        self.last_branchmanifests = self.current_branchmanifests

        return branches_updated

    # call this in your main gevent loop
    def tick(self):
        curtime = time.time()
        promises = []

        if (curtime - self.last_check) > self.check_interval:
            LOG.info("CDNScraper checking for {} updates...".format(self.appid))
            # None-out "current" values for this run.
            self.current_branchmanifests.clear()

            try:
                branches_with_update = self.check_for_updates()
            except KeyboardInterrupt:
                raise
            except Exception as err:
                LOG.error("Failed to fetch depotinfo for {}, got:\n{}".format(
                    self.appid,
                    ''.join(traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__))
                    ))
                return promises
            except:
                return promises
            
            for branch in branches_with_update:
                self.change_events.append(
                    CDNEvent_BranchChange(
                        branch,
                        self.last_branchinfo[branch],
                        branches_with_update[branch]
                    )
                )
                if branch in self.branch_actions.keys():
                    LOG.info("Calling branch_actions entry ({},{},{})".format(self.current_branchmanifests[branch], self.last_depotinfo, branch))
                    action_result = self.branch_actions[branch](
                        self,
                        self.current_branchmanifests[branch],
                        branches_with_update[branch],
                        branch)
                    # if your branch_action returned any promises in a list, we'll return these up.
                    if len(action_result) > 0:
                        LOG.info("[tick][{}] branch_actions returned {} results".format(branch, len(action_result)))
                        promises.extend(action_result)

                self.last_branchinfo[branch] = branches_with_update[branch]

            self.last_check = curtime
        
        return promises

    # pickling support, remove unserializable fields
    def __getstate__(self):
        state = self.__dict__.copy()
        del state["download_pool"] # gevent.threadpool.ThreadPool unserializable, no shit
        del state["cdnapi"]        # don't trust third party libraries to handle pickling
        #LOG.info("serializing scraper:\n{}".format(state))

        return state
    def __setstate__(self, state):
        self.__dict__.update(state)

    def save_state(self):
        out_path = self.download_directory / "cdnscraper-state.pickle"
        if not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.rename(out_path.with_suffix("."+str(time.time())))
        with open(out_path, 'wb') as out_file:
            pickle.dump(self, out_file)

    # small init for restoring from a pickled state
    def reinit(self, cdnapi, options):
        self.cdnapi = cdnapi
        self.options = options
        self.appid = options["appid"]
        self.download_directory = Path(options["download_directory"]).absolute()

        self.download_pool = GPool(16)#ThreadPoolExecutor(16, initializer=thread_init)

    default_options = {
                "appid": 881100,
                "branch_actions": {
                    "public": default_update_handler,
                    "noitabeta": default_update_handler,
                    "noitabeta_mods": default_update_handler
                },
                "download_directory": r"./archive/"
            }

    # need these two for pickling support
    def default_branchinfo(self):
        return {'buildid':'0','timeupdated':'0'}
    def default_none(self):
        return None
    def __init__(self, cdnapi, options=None):
        if options is None:
            options = self.default_options
        
        self.options = options
        self.cdnapi = cdnapi
        self.appid = options["appid"]
        self.download_directory = Path(options["download_directory"]).absolute()

        # everything below here is just default empty state
        self.branch_actions= {}
        self.download_pool = GPool(16)#ThreadPoolExecutor(16, initializer=thread_init)

        self.last_check = 0
        self.check_interval = 5 # seconds
        self.change_events = deque()

        self.last_manifests = []
        self.last_depotinfo = {} # the entire depot info for this appid, containing all branches.
        self.last_branchinfo = defaultdict(self.default_branchinfo)
        self.last_branchmanifests = defaultdict(self.default_none) # {'noitabeta': [CDNDepotManifest instances], 'never_seen_this_branch': None}

        self.current_branchmanifests = defaultdict(self.default_none) # passing around args between members sucks

        # initialize the state for branch tracking
        for branch, func in options["branch_actions"].items():
            self.branch_actions[branch] = func
            #self.last_branchinfo[branch] = {'buildid': '0', 'timeupdated': '0'}

        # test code to trigger an update on first check
        if False:
            self.last_branchinfo['noitabeta'] = {'buildid': '4246174', 'description': 'Beta branch with experimental modding support', 'timeupdated': '1570816042'}

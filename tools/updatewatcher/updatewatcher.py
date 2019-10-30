#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gevent
from gevent import monkey
monkey.patch_all()

from gevent.pool import Pool as GPool

from gevent.fileobject import FileObject
#monkey.patch_ssl()

import logging, re, string, time, traceback, pickle, importlib, inspect
import IPython, timeago
from pathlib import Path
from collections import defaultdict, deque, namedtuple
from multiprocessing import Process, Queue # separate the process that does downloads+decrypts at 1gbps and the discord loop.

from steam.client.cdn import CDNClient, CDNDepotManifest
from steam.client import SteamClient
from steam.enums.emsg import EMsg
from steam.enums import EResult

from secrets import user, passwd
import disco_bot
from disco_bot import BotCommand

# load the default parsers
from gameparsers.GameParserNoitaRuntimeAnalysis import GameParserNoitaRuntimeAnalysis
from gameparsers.GameParserNoitaStaticAnalysis import GameParserNoitaStaticAnalysis
from gameparsers.GameParserNoitaStrings import GameParserNoitaStrings

# get-content .\running.log -Wait -Tail 10
logging.basicConfig(filename="running.log", format="%(asctime)s:%(levelname)s:%(name)s| %(message)s", level=logging.INFO)
LOG = logging.getLogger()

dl_async = True # False = 10x slower
dl_native_threads = False # False = steamcdn @ ~15-20MB/s, True = symmetric gigabit is saturated
run_discord = True
discord_process = None
discord_commands_recv = None
discord_commands_send = None

LOGON_DETAILS = {'username': user, 'password': passwd}

if dl_native_threads:
    from gevent.threadpool import ThreadPoolExecutor

from cdnscraper import CDNScraper, CDNEvent_BranchChange # CDNEvent_*

class Hämis:
    """ Main runtime class for game tracker customized for Noita """

    def __init__(self, appid, run_discord=True):
        """ 
        1. Init steam, discord clients.
        2. CDNScraper init, or restore state if previously ran.
        3. Run main processing loop that does
        """
        self.appid = appid
        self.init_steam() # self.steacli, self.cdnapi
        if run_discord:
            self.run_discord()  # self.discord_process, self.discord_commands_recv, self.discord_commands_send
        
        # restore what we've scraped already if we're restarting
        old_state = Path("./archive/cdnscraper-state.pickle")
        self.scraper = None
        if old_state.exists():
            try:
                self.scraper = pickle.load(open(old_state, 'rb'))
                self.scraper.reinit(self.cdnapi, CDNScraper.default_options)
                LOG.info("Reinitialized scraper:\n{}".format(self.scraper.__dict__))
            except:
                LOG.error("Failed to reinit scraper, pickle bad")

        if not self.scraper:
            self.scraper = CDNScraper(self.cdnapi)
            LOG.info("Started new scraper:\n{}".format(self.scraper.__dict__))

        self.game_parsers = [GameParserNoitaRuntimeAnalysis, GameParserNoitaStrings, GameParserNoitaStaticAnalysis] # GameParserNoitaWAK, GameParserNoitaComponents,

        # run PER-BRANCH after parsers complete.
        from publishers.gitpublisher import GitPublisher
        self.publishers = [GitPublisher]

        self.main_loop()

    def main_loop(self):
        quitting = False
        # last time we sent a status to discord
        last_status = 0
        last_scrape = 0
        scrape_period = 15
        steam_reinit_period = 60*60*6 # 6 hours works okay
        steam_reinit_last = time.time()
        # main gevent loop
        while True:
            curtime = time.time()
            pending_downloads_for_changes = [] # what downloads need to finish for the parsers to run?
            branches_to_parse = [] # what branches need parsers run?
            scraper_change = False # has the scraper found a change this iteration?

            # seems like our token goes bad every ~12 hours, so renew every 6
            if steam_reinit_last - curtime > steam_reinit_period:
                LOG.info("Trying to reinitialize steam...")
                self.reinit_steam()
                LOG.info("Steam reinit complete?")
                steam_reinit_last = curtime

            if run_discord:
                # do we have any commands from discord
                if not self.discord_commands_recv.empty():
                    item = self.discord_commands_recv.get()
                    LOG.info("command from discord: {}".format(item))
                    try:
                        self.discord_cmd_dispatch(item)
                    except KeyboardInterrupt:
                        quitting = True
                    except Exception as err:
                        LOG.error("Error during discord dispatch {}".format(''.join(traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__))))

                # do we need to tell discord we're alive
                if curtime-last_status > (60*5):
                    self.discord_commands_send.put({'t':'WATCHER_LOG_MESSAGE','d':{
                        'logtype': BotCommand.LOGINFO,
                        'logmsg': 'watcher running: {}'.format(curtime)
                    }})
                    last_status = curtime

            if curtime - last_scrape > scrape_period:
                last_scrape = curtime
                LOG.debug("[main_loop] checking manifest+depots for differences...")
                pending_downloads_for_changes = self.scraper.tick()
                if len(pending_downloads_for_changes) == 0:
                    LOG.debug("[main_loop] scraper reports no changes :)")
                

            # pump change events off the stack, could be:
            #   CDNEvent_BranchChange
            #   CDNEvent_ManifestChange
            while len(self.scraper.change_events) > 0:
                scraper_change = True
                cur_event = self.scraper.change_events.popleft()
                LOG.info("change notification: {}".format(cur_event))
                # if the branch info changed, and the buildid changed, time to parse.
                if (isinstance(cur_event, CDNEvent_BranchChange)):
                    self.discord_commands_send.put({'t':'WATCHER_CHANGE_BRANCH','d':{
                        'app_id': '881100',
                        'branch_name': cur_event.branch_name,
                        'old_branchinfo': cur_event.old_branchinfo,
                        'new_branchinfo': cur_event.new_branchinfo
                    }})
                    if cur_event.buildid_changed():
                        LOG.info("above change is triggering a parse")
                        branches_to_parse.append(cur_event)

            # wait for downloads to complete and parse them
            if len(pending_downloads_for_changes) > 0:
                gevent.spawn(self.wait_then_process_noita, pending_downloads_for_changes, branches_to_parse)

            if scraper_change:
                # persist scraper state to disk to support restarts
                # loop it so I don't break the fucking state with a ctrl+c
                unsaved = True
                while unsaved:
                    try:
                        self.scraper.save_state()
                        unsaved = False
                    except KeyboardInterrupt:
                        quitting = True
                        pass
                        
            if quitting:
                LOG.info("Exiting gracefully")
                break
            gevent.sleep(1)

    # todo refactor
    # this function should run in its own thread asynchronously.
    def wait_then_process_noita(self, events, branches, parsers=None, publish=True):
        LOG.info("[!!!!] parser for branches {} started, waiting on {} events".format(branches,len(events)))
        if len(events) > 0:
            gevent.joinall(events)

        dirs = '\n'.join([str(e) for e in Path("archive").iterdir() if e.is_dir()])
        LOG.info("[!!!!] downloads for all branches finished:\n{}\n".format(dirs))
        
        for branch_change in branches:
            archive_name = "archive/{}_{}_{}".format(
                881100,
                branch_change.new_branchinfo['buildid'],
                branch_change.branch_name)
            
            if not Path(archive_name).exists():
                continue

            running_parsers = []
            finished_parsers = []
            parsers_to_run = self.game_parsers
            if parsers:
                # running specific set of parsers
                parsers_to_run = parsers

            for parser_class in parsers_to_run:
                storage_location = archive_name + "_" + parser_class.__name__

                LOG.info("starting parser: {}({},{})".format( parser_class.__name__, archive_name, storage_location))
                self.discord_commands_send.put({'t':'WATCHER_CHANGE_PARSER_START','d':{
                    'app_id': '881100',
                    'branch_name': branch_change.branch_name,
                    'parser': parser_class.__name__
                }})

                # encourage the discord greenlet to dispatch that.
                gevent.sleep(0.1)

                running_parsers.append(parser_class(Path(archive_name), Path(storage_location)))
                
            # wait for them to complete, send results to discord, etc.
            while len(running_parsers) > 0:
                for idx,parser in enumerate(running_parsers):
                    try:
                        if parser.finished:
                            result = parser.get_result()
                            LOG.info("[{}] finished, results:\n{:.500s}".format(type(parser).__name__, repr(result)))
                            self.discord_commands_send.put({'t':'WATCHER_CHANGE_PARSER_RESULT','d':{
                                'app_id': '881100',
                                'branch_name': branch_change.branch_name,
                                'branch_version': branch_change.new_branchinfo['buildid'],
                                'parser': type(parser).__name__,
                                'result': result
                            }})
                            if len(parser.errors) > 0:
                                LOG.info("[{}] had errors: {}".format(type(parser).__name__, parser.errors))

                            finished_parsers.append(parser)
                            del running_parsers[idx]
                    except KeyboardInterrupt:
                        raise
                    except Exception as err:
                        LOG.error("Error getting results for parser {}, {}".format(type(parser).__name__,''.join(traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__))))
                        if parser.finished: 
                            finished_parsers.append(parser)
                            del running_parsers[idx]
                gevent.sleep(0.5)
            LOG.info("[!!!!][{}] parsers finished :)".format(branch_change.branch_name))

            if publish:
                # you have:
                #   * parsers that return vastly different data by design
                #   * publishers that want to format arbitrary data in a way humans might want to read
                # the publishers are going to HAVE to special-case handling different data in different ways.
                # so you _need_ to have a result-type for every parsed result and the publisher needs a handler for every format.
                # for n result types and m publishers, that's n*m formatters to write.
                # so just git for now... 
                try:
                    for Publisher in self.publishers:
                        cur_publisher = Publisher(self.appid, 
                                                branch_change.branch_name, 
                                                branch_change.new_branchinfo['buildid'])
                        for parser in finished_parsers:
                            for result in parser.get_result():
                                cur_publisher.add_result(result)
                        cur_publisher.publish()
                except Exception as err:
                    LOG.error("Error during publisher run {}".format(''.join(traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__))))

    def reload_all(self, classes):
        result = []
        for c in classes:
            result.append(self.reload_class(c))
        return result

    def reload_class(self, target):
        mod_ref = inspect.getmodule(target)
        if not mod_ref:
            LOG.error("Failed to get module for class reload, {} got {}".format(target, mod_ref))
            return None
        mod_ref = importlib.reload(mod_ref)
        return getattr(mod_ref, target.__name__)

    def run_discord(self):
        """ Create IPC queues and Discord client process """
        self.discord_commands_recv = Queue()
        self.discord_commands_send = Queue()

        self.discord_process = Process(target=disco_bot.start, args=(self.discord_commands_recv, self.discord_commands_send))
        self.discord_process.start()

    def discord_respond(self, discord_msg, msg):
        self.discord_commands_send.put({'t':'WATCHER_RESPONSE','d':{
            'discord_msg': discord_msg,
            'msg': msg
        }})

    def discord_cmd_dispatch(self, cmd):
        LOG.info("Discord command dispatch: {}".format(cmd))
        if cmd['t'] == "RESET_BRANCH":
            branch = cmd['d']['branch_name']
            if branch in self.scraper.last_branchinfo.keys():
                self.scraper.last_branchinfo[branch] = cmd['d']['branch_info']
            else:
                self.discord_respond(cmd['m'], "Could not reset branch {}, branch not currently tracked.".format(branch))
        elif cmd['t'] == "PARSER_ENABLE":
            for idx,parser in enumerate(self.game_parsers):
                if str(parser.__name__) == cmd['d']['parser']:
                    self.discord_respond(cmd['m'], "Parser already enabled.")
                    return
                
            # loads the module here.
            parser_class = getattr(importlib.import_module('gameparsers.{}'.format(cmd['d']['parser'])), cmd['d']['parser'])
            self.game_parsers.append(parser_class)
        elif cmd['t'] == "PARSER_DISABLE":
            LOG.info("disable")
            for idx,parser in enumerate(self.game_parsers):
                LOG.info("disable {} == {}".format( str(parser.__name__), cmd['d']['parser']))                
                if str(parser.__name__) == cmd['d']['parser']:
                    self.discord_respond(cmd['m'], "Parser {} disabled.".format(cmd['d']['parser']))
                    del self.game_parsers[idx]
                    return
            
            self.discord_respond(cmd['m'], "Parser {} was never enabled.".format(cmd['d']['parser']))
        elif cmd['t'] == "PARSER_RUN":
            if not self.archived_build(cmd['d']['buildid'], cmd['d']['branch_name'], cmd['m']):
                return

            parser = None
            if cmd['d']['parser'] == "all":
                parser = self.game_parsers
            else:
                parser_class = getattr(importlib.import_module('gameparsers.{}'.format(cmd['d']['parser'])), cmd['d']['parser'])
                parser = [parser_class]
            # shitty hack
            gevent.spawn(self.wait_then_process_noita, [], [
                    CDNEvent_BranchChange(
                        cmd['d']['branch_name'],
                        {'buildid': cmd['d']['buildid']},
                        {'buildid': cmd['d']['buildid']}
                    )],
                    parsers=parser,
                    publish=False)
            pass
        elif cmd['t'] == "PARSER_RELOAD":
            try:
                if cmd['d']['parser'] in globals().keys():
                    updated_class = self.reload_class(globals()[cmd['d']['parser']])

                    # reload anything referencing it, really
                    for idx, c in enumerate(self.game_parsers):
                        if c.__name__ == updated_class.__name__:
                            self.game_parsers[idx] = updated_class
                    for idx, c in enumerate(self.publishers):
                        if c.__name__ == updated_class.__name__:
                            self.publishers[idx] = updated_class
                else:
                    self.discord_respond(cmd['m'], "Class not loaded? {}".format(cmd['d']['parser']))
                    return
            except (ImportError, KeyError, TypeError):
                self.discord_respond(cmd['m'], "Failed to reload {}, check log".format(cmd['d']['parser']))
            self.discord_respond(cmd['m'], "Reloaded {}".format(cmd['d']['parser']))
        elif cmd['t'] == "NOITA_PYWIKIBOT":
            if not self.archived_build(cmd['d']['buildid'], cmd['d']['branch_name'], cmd['m']):
                return
            
            gevent.spawn(self.run_pywikibot, cmd['d']['branch_name'], cmd['d']['buildid'], )

    def archived_build(self, buildid, branch, m=None):
        """ Check if a build is archived, and reply to m if necessary. """
        archive_path = "archive/{}_{}_{}".format("881100", buildid, branch)
        if not Path(archive_path).exists():
            if m: self.discord_respond(m, "Failing out, couldn't find archived build at {}".format(archive_path))
            return False
        return True

    def run_pywikibot(self, branch, buildid):
        return

    def reinit_steam(self):
        """ cdnapi's token is invalid after a certain period, and the CDN will happily serve us partial content for unauthed users """
        # note that we don't wait for gpools to finish or anything, that might fuck shit up.
        try:
            self.steamcli.teardown = True
            self.steamcli.disconnect()
            del self.steamcli
            del self.cdnapi
        except KeyboardInterrupt:
            raise
        except Exception as err:
            LOG.error("Error during steam teardown: {}".format(''.join(traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__))))
        try:
            self.steamcli = None
            self.cdnapi = None
            self.init_steam()
        except KeyboardInterrupt:
            raise
        except Exception as err:
            LOG.error("Error during steam bringup: {}".format(''.join(traceback.format_exception(etype=type(err), value=err, tb=err.__traceback__))))

    def init_steam(self):
        """ Starts Steam & SteamCDNAPI clients courtesy https://github.com/ValvePython/steam """
        self.steamcli = steamcli = SteamClient()
        self.steamcli.teardown = False

        steamcli.set_credential_location("./secrets")

        @steamcli.on('error')
        def steam_error(result):
            LOG.error("SteamClient error: ", repr(result))

        @steamcli.on('auth_code_required')
        def auth_code_prompt(is_2fa, mismatch):
            if is_2fa:
                code = input("Enter 2FA Code: ")
                steamcli.login(two_factor_code=code, **LOGON_DETAILS)
            else:
                code = input("Enter Email Code: ")
                steamcli.login(auth_code=code, **LOGON_DETAILS)

        @steamcli.on("disconnected")
        def handle_disconnect():
            LOG.info("Disconnected.")

            if not steamcli.teardown and steamcli.relogin_available:
                LOG.info("Reconnecting...")
                steamcli.reconnect(maxdelay=30)

        @steamcli.on("error")
        def handle_error(result):
            LOG.info("Logon result: %s", repr(result))

        @steamcli.on("channel_secured")
        def send_login():
            if steamcli.relogin_available:
                steamcli.relogin()

        @steamcli.on("logged_on")
        def handle_after_logon():
            LOG.info("Steam logon success, last logon: %s", steamcli.user.last_logon)
            LOG.info("Steam last logoff: %s", steamcli.user.last_logoff)

        steamcli.login(**LOGON_DETAILS)
        self.cdnapi = CDNClient(steamcli) 


if __name__ == '__main__':
    noita_appid = 881100
    Hämis(noita_appid)

    IPython.embed()
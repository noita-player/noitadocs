
import gevent
from gevent import Greenlet
from gevent import monkey
monkey.patch_all()

import logging
from enum import Enum
from multiprocessing import Process, Queue # just for quarantining discord

from disco.bot import Bot, BotConfig
from disco.client import Client, ClientConfig
from disco.util.logging import setup_logging
from disco.gateway.events import GatewayEvent
from disco.types.base import Model, ModelMeta, Field, ListField, AutoDictField, snowflake, datetime

#logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s| %(message)s", level=logging.DEBUG)

# everything that can come from main process
class BotCommand(Enum):
    LOGERROR = 1
    LOGWARNING = 2
    LOGINFO = 3
    LOGDEBUG = 4
    CHANGE_BRANCH = 5
    CHANGE_MANIFEST = 6
    CHANGE_DOWNLOADCOMPLETE = 7
    CHANGE_PARSERSTART = 8
    CHANGE_PARSERRESULT = 9

# from disco.gateway.events import EVENTS_MAP; print(EVENTS_MAP)
# 'WATCHER_LOG_MESSAGE': disco_bot.WatcherLogMessage
class WatcherLogMessage(GatewayEvent):
    """
        Sent for LOGERROR, LOGWARNING, LOGINFO, LOGDEBUG
    """
    logtype = Field(BotCommand)
    logmsg = Field(str)
    def __str__(self):
        return "{} - {}".format(self.logtype,self.logmsg)

# WATCHER_CHANGE_BRANCH
class WatcherChangeBranch(GatewayEvent):
    app_id = Field(str)
    branch_name = Field(str)
    old_branchinfo = Field(dict)
    new_branchinfo = Field(dict)
    def __str__(self):
        return "{} - {}".format(self.old_branchinfo,self.new_branchinfo)

# WATCHER_CHANGE_PARSER_START
class WatcherChangeParserStart(GatewayEvent):
    app_id = Field(str)
    branch_name = Field(str)
    branch_version = Field(str)
    parser = Field(str)
    def __str__(self):
        return "{} - {}".format(self.app_id,self.parser)

# WATCHER_CHANGE_PARSER_RESULT
class WatcherChangeParserResult(GatewayEvent):
    app_id = Field(str)
    branch_name = Field(str)
    branch_version = Field(str)
    parser = Field(str) # name of parser
    result = ListField(str) # absolute path to some files
    def __str__(self):
        return "[{}][{}][{}]".format(self.app_id,self.parser,self.result)

# WATCHER_RESPONSE
class WatcherResponse(GatewayEvent):
    """
        Sent when updatewatcher is asynchronously responding to discord_msg
    """
    discord_msg = Field(dict)
    msg = Field(str)


"""
disco/gateway/client.py emits events to plugins like so

    def handle_dispatch(self, packet):
        obj = GatewayEvent.from_dispatch(self.client, packet)
        self.log.debug('GatewayClient.handle_dispatch %s', obj.__class__.__name__)
        self.client.events.emit(obj.__class__.__name__, obj)
        if self.replaying:
            self.replayed_events += 1
"""

class DiscoBotManager():
    """ small class to start disco and manage IPC with main proc """
    def __init__(self, main_process_recv, main_process_send):
        self.main_process_recv = main_process_recv
        self.main_process_send = main_process_send

        self.main_loop()

    # start disco and return its greenlet
    def start_disco(self):
        setup_logging(level=logging.DEBUG)
        self.config = ClientConfig.from_file("./secrets/discord.json")
        self.client = Client(self.config)
        self.bot_config = BotConfig(self.config.bot)
        self.bot = Bot(self.client, self.bot_config)
        self.bot.main_process_recv = self.main_process_recv
        return self.bot.client.run()

    def run_command(self, event):
        self.bot.client.events.emit(event.__class__.__name__, event)

    def main_loop(self):
        discolet = self.start_disco()
        while True:
            #self.run_command(1, 'message injected?')
            while not self.main_process_send.empty():
                evt = self.main_process_send.get()

                # {'ipc': ...} indicates a command for DiscordBotManager and not disco :)
                if not ('ipc' in evt.keys()):
                    self.run_command(GatewayEvent.from_dispatch(self.bot.client, evt))
            gevent.sleep(10)
        discolet.kill()

def start(main_process_recv, main_process_send):
    DiscoBotManager(main_process_recv, main_process_send)

if __name__ == '__main__':
    sendq = Queue()
    recvq = Queue()

    _ = """
    sendq.put({'t':'WATCHER_CHANGE_BRANCH','d':{
        'app_id': '881100',
        'branch_name': 'noitabeta',
        'old_branchinfo': {'buildid': '4279396', 'description': 'Beta branch', 'timeupdated': '1570807815'},
        'new_branchinfo': {'buildid': '4279397', 'description': 'Beta branch', 'timeupdated': '1570807816'}
    }})
"""
    DiscoBotManager(recvq, sendq)
#gevent.joinall([Greenlet.spawn(go_disco)])
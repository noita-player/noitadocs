from disco.bot.command import CommandEvent
from disco.types.channel import ChannelType
from disco.types.message import Message, MessageEmbed, MessageEmbedThumbnail, MessageEmbedAuthor
from disco.types.permissions import Permissions
from disco.types.guild import GuildMember
from disco.types.user import User
from disco.bot import Plugin, Config

import IPython, timeago
from tabulate import tabulate
from pathlib import Path

from collections import defaultdict
import traceback, ast

class GameTrackerPlug(Plugin):
    """send tracker events to discord"""
    def load(self, ctx):
        self.log_msg_list = defaultdict(lambda: None)
        self.admin_role = self.config['ADMIN_ROLE']
        self.dev_mode = False # don't spam discord when I'm testing

        self.ping_roles = {}
        for r in self.client.api.guilds_roles_list(self.config['GUILD_ID']):
            if "_ping" in r.name:
                self.ping_roles[r.name] = r

    def log_msg(self, src, level, msg):
        log_channel = self.config['BOT_LOGGING_CHANNEL']
        if level == 1:
            log_channel = self.config['BOT_LOGGING_CHANNEL_ERRORS']

        if self.log_msg_list[src] is None:
            self.log_msg_list[src] = self.client.api.channels_messages_create(log_channel, msg)
        else:
            message = self.log_msg_list[src].content
            message += "\n{}".format(msg)
            try:
                self.log_msg_list[src] = self.client.api.channels_messages_modify(log_channel, self.log_msg_list[src].id, content=message)
            except Exception as err:
                print(err)
                self.log_msg_list[src] = None
                self.log_msg(src, level, msg)

    @staticmethod
    def create_embed(event_name: str,
                     event_link: str,
                     title: str,
                     *args, **kwargs):

        embed = MessageEmbed()
        embed.title = title
        embed.url = event_link
        embed.author = MessageEmbedAuthor(name=event_name,
                                          url="https://github.com/noita-player/noitadocs",
                                          icon_url="https://cdn.discordapp.com/avatars/380885338916388876/68c463572e12c8f9209789fd8ca29ff0.webp?size=128")
        args_desc = "\n\n".join(args)
        kwargs_desc = "\n\n".join("**{0}:\n{1}**".format(name, value) for name, value in kwargs.items())
        embed.description = "\n\n".join((args_desc, kwargs_desc))
        embed.color = 0x00FFFF
        return embed

    def pingrole_from_string(self, s):
        fuzzy = None
        for r in self.ping_roles.keys():
            if s == r: 
                return self.ping_roles[r]
            elif s in r:
                fuzzy = self.ping_roles[r]
        return fuzzy

    @Plugin.command('ping')
    def command_ping(self, event):
        if self.admin_role not in event.member.roles:
            return
        event.msg.reply('Pong!')

    @Plugin.command('dev')
    def command_dev(self, event):
        if self.admin_role not in event.member.roles:
            return
        self.dev_mode = not self.dev_mode
        if self.dev_mode:
            event.msg.reply('dev on - not pinging, not posting')
        else:
            event.msg.reply('dev off - pings / updates going')

    @Plugin.command('pingme', "[game:str...]")
    def command_pingme(self, event, game=None):
        # just assume noita for now
        if game == None or game == "":
            game = "noita_ping"
        ping_role = self.pingrole_from_string(game)
        if ping_role.id in event.member.roles:
            event.member.remove_role(ping_role)
            event.msg.reply('No longer pinging you.')
        else:
            event.member.add_role(ping_role)
            event.msg.reply('You will get a ping on new changes to important branches!')

    @Plugin.command('noita_pywikibot', '<command:str> <buildid:str> <branch:str>')
    def command_noita_pywikibot(self, event, command, buildid, branch):
        if self.admin_role not in event.member.roles:
            return
        event.msg.reply('command: {} buildid: {} branch: {}'.format(command, buildid, branch))
        self.bot.main_process_recv.put({
                't': 'NOITA_PYWIKIBOT',
                'd': {"command": command, "buildid": buildid, "branch": branch},
                'm': event.msg.to_dict()
            })

    @Plugin.command('parser_enable', '<appid:str> <parser:str>')
    def command_parser_enable(self, event, appid, parser):
        if self.admin_role not in event.member.roles:
            return
        event.msg.reply('appid: {} parser: {}'.format(appid, parser))
        self.bot.main_process_recv.put({
                't': 'PARSER_ENABLE',
                'd': {"parser": parser, "appid": appid},
                'm': event.msg.to_dict()
            })

    @Plugin.command('parser_disable', '<appid:str> <parser:str>')
    def command_parser_disable(self, event, appid, parser):
        if self.admin_role not in event.member.roles:
            return
#        event.msg.reply('appid: {} parser: {}'.format(appid, parser))
        self.bot.main_process_recv.put({
                't': 'PARSER_DISABLE',
                'd': {"parser": parser, "appid": appid},
                'm': event.msg.to_dict()
            })

    @Plugin.command('parser_reload', '<parser:str>')
    def command_parser_reload(self, event, parser):
        if self.admin_role not in event.member.roles:
            return
#        event.msg.reply('appid: {} parser: {}'.format(appid, parser))
        self.bot.main_process_recv.put({
                't': 'PARSER_RELOAD',
                'd': {"parser": parser},
                'm': event.msg.to_dict()
            })

    @Plugin.command('parser_run', '<parser:str> <branch_name:str> <buildid:str>')
    def command_parser_run(self, event, parser, branch_name, buildid):
        """ Re-load and run a parser """
        if self.admin_role not in event.member.roles:
            return
        
        event.msg.reply('parser: {} branch: {} buildid: {}'.format(parser, branch_name, buildid))
        self.bot.main_process_recv.put({
                't': 'PARSER_RUN',
                'd': {"parser": parser, "branch_name": branch_name, "buildid": buildid},
                'm': event.msg.to_dict()
            })

    @Plugin.command('reset_branch', '<content:str...>')
    def command_reset_branch(self, event, content):
        if self.admin_role not in event.member.roles:
            return

        try:
            data = ast.literal_eval(content)
        except:
            data = None
        if data != None and 'branch_name' in data.keys() and 'branch_info' in data.keys():
            event.msg.reply('trying to reset')
            self.bot.main_process_recv.put({
                't': 'RESET_BRANCH',
                'd': data,
                'm': event.msg.to_dict()
            })
        else:
            event.msg.reply("Bad format, try: {'branch_name': 'whatever', 'branch_info': {'buildid': '12345', 'timeupdated': '12345'}}")

    @Plugin.listen('WatcherResponse')
    def listen_watcherresponsemessage(self, msg):
        self.client.api.channels_messages_create(msg.discord_msg['channel_id'], msg.msg)

    @Plugin.listen('WatcherLogMessage')
    def listen_watcherlogmessage(self, msg):
        self.log_msg('watcherlog', msg.logtype, msg.logmsg)

    @Plugin.listen('WatcherChangeBranch')
    def listen_watcherchangebranch(self, msg):
        print('got change branch: {}'.format(msg))
        if self.dev_mode:
            log_channel = self.config['BOT_LOGGING_CHANNEL_ERRORS']
        else:
            log_channel = self.config['BOT_CHANGES_CHANNEL']

        embed_title = "occurred {}".format(timeago.format(int(msg.new_branchinfo['timeupdated'])))
        embed_obj = GameTrackerPlug.create_embed("branch changed: {}".format(msg.branch_name), 
                                                "https://github.com/noita-player/noitadocs",
                                                embed_title
                                                )

        def value_or_nonexistant(value, dic):
            if value in dic.keys():
                return dic[value]
            else:
                return "NO VALUE"

        changes_table = []
        for branch in msg.new_branchinfo.keys(): 
            try:
                changes_table.append([branch, msg.old_branchinfo[branch], msg.new_branchinfo[branch]])
            except KeyError:
                changes_table.append(
                    ["{} added-or-removed".format(branch), 
                    value_or_nonexistant(branch, msg.old_branchinfo), 
                    value_or_nonexistant(branch, msg.new_branchinfo) ])
        changes_table = tabulate(changes_table,
                                ["","old","new","timeupdated"], tablefmt="grid"
                                )
        embed_obj.description = ""
        
        # todo
        ping_message = ""
        if msg.branch_name == "public" or msg.branch_name == "noitadev":
            for role_name in self.ping_roles.keys():
                role = self.ping_roles[role_name]
                if "noita" in role.name:
                    ping_message += "<@&{}> ".format(role.id)
            ping_message += " change on branch {}\n".format(msg.branch_name)

        pretty_table = """
{}
```
{}
```
""".format(ping_message, changes_table)

        self.client.api.channels_messages_create(log_channel, pretty_table,
            embed=embed_obj)

    @Plugin.listen('WatcherChangeParserStart')
    def listen_watcherchangeparserstart(self, msg):
        if self.dev_mode:
            log_channel = self.config['BOT_LOGGING_CHANNEL_ERRORS']
        else:
            log_channel = self.config['BOT_CHANGES_CHANNEL']

        self.client.api.channels_messages_create(log_channel, "Started parser `{}`".format(msg.to_dict()))


    @Plugin.listen('WatcherChangeParserResult')     
    def listen_watcherchangeparserresult(self, msg):
        if self.dev_mode:
            log_channel = self.config['BOT_LOGGING_CHANNEL_ERRORS']
        else:
            log_channel = self.config['BOT_CHANGES_CHANNEL']


        self.log_msg('changeparser', 3, str(msg.to_dict()))

        attach_list = []
        try:
            for result_path in msg.result:
                result_path = Path(result_path)
                if not result_path.exists():
                    self.log_msg('plugin-error', 1, "Result file not found: {}".format(result_path))
                else:
                    attach_list.append((result_path.name, open(result_path, 'rb'), 'application/octet-stream'))
        except Exception as ex:
            self.log_msg('plugin-error', 1, ''.join(traceback.format_exception(type(ex), ex, ex.__traceback__)))

        try:
            self.client.api.channels_messages_create(log_channel, "[branch: {} build: {}][{}] finished, result below".format(msg.branch_name, msg.branch_version, msg.parser),
                attachments=attach_list)
        except Exception as ex:
            self.log_msg('plugin-error', 1, ''.join(traceback.format_exception(type(ex), ex, ex.__traceback__)))

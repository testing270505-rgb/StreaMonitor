import math
from logging import INFO, WARN, ERROR
from threading import Thread
from termcolor import colored
import terminaltables.terminal_io
from terminaltables import AsciiTable
import streamonitor.config as config
import streamonitor.log as log
from streamonitor.bot import Bot, LOADED_SITES
from streamonitor.managers.outofspace_detector import OOSDetector

from streamonitor.enums import Status


class Manager(Thread):
    def __init__(self, streamers):
        super().__init__()
        self.daemon = True
        self.streamers = streamers
        self.logger = log.Logger("manager")

    def execCmd(self, line):
        parts = str(line).split(' ')
        if 'do_' + parts[0] not in dir(self):
            return 'Unknown command'

        command = getattr(self, 'do_' + parts[0])
        if command:
            return command(parts)

    def getStreamer(self, username, site):
        found = None
        site = Bot.str2site(site)
        if site:
            site = site.site
        for streamer in self.streamers:
            if streamer.username == username:
                if site and site != "":
                    if streamer.site == site:
                        return streamer
                else:
                    if not found:
                        found = streamer
                    else:
                        self.logger.error('Multiple users exist with this username, specify site too')
                        return None
        return found

    def saveConfig(self):
        config.save_config([s.export() for s in self.streamers])

    def do_add(self, parts):
        """
        Add streamer with multiplatform support.
        Usage:
            add <username> <site>                    - Add parent stream
            add <username> <site> parent <parent_username> <parent_site> - Add child stream
        """
        if len(parts) < 3:
            return "Missing value(s)"
        
        username = parts[1]
        site = parts[2]
        
        # Check if streamer already exists
        streamer = self.getStreamer(username, site)
        if streamer:
            return 'Streamer already exists'
        
        try:
            streamer = Bot.createInstance(username, site)
            
            # Handle parent assignment for multiplatform models
            if len(parts) >= 6 and parts[3].lower() == 'parent':
                parent_username = parts[4]
                parent_site = parts[5]
                
                parent = self.getStreamer(parent_username, parent_site)
                if not parent:
                    return f"Parent streamer not found: {parent_username} [{parent_site}]"
                
                # Set up child relationship
                streamer.parent = parent
                streamer.is_child = True
                parent.children.append(streamer)
                self.logger.info(f"Created child stream {streamer.username} [{streamer.site}] for parent {parent.username} [{parent.site}]")
            
            self.streamers.append(streamer)
            streamer.start()
            streamer.restart()
            self.saveConfig()
            
            if streamer.is_child:
                return f"Added [" + streamer.siteslug + "] " + streamer.username + f" as child of {streamer.parent.username}"
            else:
                return "Added [" + streamer.siteslug + "] " + streamer.username
        except Exception as e:
            return f"Failed to add: {e}"

    def do_remove(self, parts):
        if len(parts) < 2:
            return "Missing username"
        
        username = parts[1]
        site = parts[2] if len(parts) > 2 else ""
        
        streamer = self.getStreamer(username, site)
        if not streamer:
            return "Streamer not found"
        
        try:
            # Remove from parent's children list if it's a child
            if streamer.parent:
                streamer.parent.children.remove(streamer)
                self.logger.info(f"Removed child {streamer.username} from parent {streamer.parent.username}")
            
            # If parent, reassign children
            if streamer.children:
                self.logger.warning(f"Removing parent {streamer.username} with {len(streamer.children)} child streams. Children will be orphaned.")
            
            streamer.stop(None, None)
            streamer.logger.handlers = []
            self.streamers.remove(streamer)
            self.saveConfig()
            return "OK"
        except Exception as e:
            self.logger.error(e)
            return "Failed to remove streamer"

    def do_start(self, parts):
        if len(parts) < 2:
            return "Missing username"
        
        username = parts[1]
        site = parts[2] if len(parts) > 2 else ""
        
        streamer = self.getStreamer(username, site)
        if not streamer:
            if username == '*':
                for streamer in self.streamers:
                    if not streamer.is_alive():
                        streamer.start()
                    streamer.restart()
                self.saveConfig()
                return "Started all"
            else:
                return "Streamer not found"
        else:
            try:
                if not streamer.is_alive():
                    streamer.start()
                streamer.restart()
                self.saveConfig()
                return "OK"
            except Exception as e:
                self.logger.error(e)
                return "Failed to start"

    def do_stop(self, parts):
        if len(parts) < 2:
            return "Missing username"
        
        username = parts[1]
        site = parts[2] if len(parts) > 2 else ""
        
        streamer = self.getStreamer(username, site)
        if not streamer:
            if username == '*':
                for streamer in self.streamers:
                    streamer.stop(None, None)
                self.saveConfig()
                return "Stopped all"
            else:
                return "Streamer not found"
        else:
            try:
                streamer.stop(None, None)
                self.saveConfig()
                return "OK"
            except Exception as e:
                self.logger.error(e)
                return "Failed to stop"

    def do_restart(self, parts):
        if len(parts) < 2:
            return "Missing username"
        
        username = parts[1]
        site = parts[2] if len(parts) > 2 else ""
        
        streamer = self.getStreamer(username, site)
        if not streamer:
            return "Streamer not found"
        self.do_stop(parts)
        return self.do_start(parts)
        
    def do_status(self, parts):
        output = [["Username", "Site", "Started", "Status", "Type"]]

        def line(streamer):
            stream_type = "Child" if streamer.is_child else ("Parent" if streamer.children else "Single")
            if streamer.is_child:
                stream_type += f" (→{streamer.parent.username})"
            
            output.append([streamer.username,
                           streamer.site,
                           streamer.running,
                           streamer.status(),
                           stream_type])

        if len(parts) > 1:
            username = parts[1]
            site = parts[2] if len(parts) > 2 else ""
            streamer = self.getStreamer(username, site)
            if streamer:
                line(streamer)
        else:
            for streamer in self.streamers:
                line(streamer)
        
        return "Status:\n" + f'Free space: {str(round(OOSDetector.free_space(), 3))}%\n\n' + AsciiTable(output).table

    def do_status2(self, parts):
        maxlen = max([len(s.username) for s in self.streamers] or [0])
        termwidth = terminaltables.terminal_io.terminal_size()[0]
        table_nx = max(1, int(termwidth/(maxlen+3)))
        output = ''
        output += 'Status:\n'

        for site in LOADED_SITES:
            output += site.site + '\n'
            output += ('+' + '-'*(maxlen+2))*table_nx + '+\n'
            site_name = site.site
            i = 0
            for streamer in self.streamers:
                if streamer.site == site_name:
                    output += '!'
                    status_color = None
                    status = streamer.sc
                    if status == Status.PUBLIC: status_color = 'green'
                    if status == Status.PRIVATE: status_color = 'magenta'
                    if status == Status.ERROR: status_color = 'red'
                    if not streamer.running: status_color = 'grey'
                    
                    # Add indicator for child streams
                    indicator = ""
                    if streamer.is_child:
                        indicator = "↳"
                    
                    username_display = f"{indicator}{streamer.username}"[:maxlen]
                    output += colored(' ' + username_display + ' '*(maxlen-len(username_display)) + ' ', status_color)
                    i += 1
                    if i == table_nx:
                        output += '!\n'
                        i = 0
            for r in range(i, table_nx):
                output += '! ' + ' ' * maxlen + ' '
            output += '!\n'
            output += ('+' + '-'*(maxlen+2))*table_nx + '+\n'
            output += '\n'
        return output

    def do_help(self, parts):
        return """
Available commands:
  add <username> <site>                    - Add parent stream
  add <username> <site> parent <parent_username> <parent_site> - Add child stream
  remove <username> [<site>]               - Remove streamer
  start <username> [<site>]                - Start monitoring streamer
  start *                                  - Start all
  stop <username> [<site>]                 - Stop monitoring streamer
  stop *                                   - Stop all
  status [<username> [<site>]]             - Show status
  status2                                  - Show status in table format
  quit                                     - Exit application
  help                                     - Show this help message

Multiplatform Models:
  - Parent streams have higher priority and are recorded first
  - Child streams only record if parent is offline
  - Only one stream is recorded at a time per model family
"""

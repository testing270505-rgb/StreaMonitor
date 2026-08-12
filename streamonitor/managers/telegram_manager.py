from datetime import datetime
import time
import subprocess
import sys
import os

import requests

from streamonitor.manager import Manager
from streamonitor.clean_exit import CleanExit
import streamonitor.log as log


class TelegramManager(Manager):
    def __init__(self, streamers, bot_token, chat_id):
        super().__init__(streamers)
        self.logger = log.Logger("telegram_manager")
        self.bot_token = bot_token
        self.chat_id = chat_id

        # Track recording states to detect changes
        self.recording_states = {}

        # Track last status update time
        self.last_status_update = datetime.now()
        self.status_update_interval = 1800  # 30 minutes in seconds
        
        # Track last update ID to avoid processing same message twice
        self.last_update_id = None
        
        # Timeout for waiting updates (in seconds)
        self.polling_timeout = 30

    def send_message(self, message):
        """Send a message to the configured Telegram chat via raw HTTP"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            response = requests.post(url, data={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }, timeout=10)
            if not response.ok:
                self.logger.error(f"Telegram API error: {response.text}")
            else:
                self.logger.debug(f"Sent message: {message}")
        except requests.RequestException as e:
            self.logger.error(f"Failed to send Telegram message: {e}")

    def send_message_with_split(self, message, max_length=4096):
        """Send message, splitting if too long for Telegram (max 4096 chars)"""
        if len(message) <= max_length:
            self.send_message(message)
        else:
            # Split message into chunks
            chunks = [message[i:i+max_length] for i in range(0, len(message), max_length)]
            for chunk in chunks:
                self.send_message(chunk)
                time.sleep(0.5)  # Small delay between messages

    def get_updates(self):
        """Poll Telegram for new messages"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            params = {
                "timeout": self.polling_timeout,
                "allowed_updates": ["message"]
            }
            
            if self.last_update_id:
                params["offset"] = self.last_update_id + 1
            
            response = requests.get(url, params=params, timeout=self.polling_timeout + 5)
            
            if response.ok:
                return response.json().get("result", [])
            else:
                self.logger.error(f"Telegram API error: {response.text}")
                return []
        except requests.RequestException as e:
            self.logger.error(f"Failed to get Telegram updates: {e}")
            return []

    def execute_controller_command(self, command_line):
        """Execute Controller.py with given command line and return output"""
        try:
            # Get the root directory (go up 2 levels from streamonitor/managers)
            current_dir = os.path.dirname(os.path.abspath(__file__))
            streamonitor_dir = os.path.dirname(current_dir)  # Go up to streamonitor/
            root_dir = os.path.dirname(streamonitor_dir)      # Go up to root/
            
            controller_path = os.path.join(root_dir, "Controller.py")
            
            if not os.path.exists(controller_path):
                return f"Error: Controller.py not found at {controller_path}"
            
            # Parse command and arguments
            parts = command_line.split()
            
            # Build command - pass as command-line arguments
            cmd = [sys.executable, controller_path] + parts
            
            # Execute with timeout
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=root_dir
            )
            
            output = result.stdout.strip()
            if result.returncode == 0:
                return output or "Command executed successfully"
            else:
                error_msg = result.stderr.strip() or output or "Unknown error"
                return f"Error: {error_msg}"
                
        except subprocess.TimeoutExpired:
            return "Error: Command timed out (30 seconds)"
        except Exception as e:
            return f"Error executing command: {str(e)}"

    def parse_and_execute_command(self, message_text):
        """Parse Telegram message and execute command"""
        if not message_text:
            return None
        
        message_text = message_text.strip()
        
        # Help command
        if message_text.lower() in ['/help', '/start']:
            return (
                "*Available Commands:*\n\n"
                "`add <username> <site>` - Add streamer (starts monitoring)\n"
                "`remove <username> [<site>]` - Remove streamer\n"
                "`start <username> [<site>]` - Start monitoring\n"
                "`stop <username> [<site>]` - Stop monitoring\n"
                "`status` - Show online/recording status\n"
                "`quit` - Clean exit\n\n"
            )
        
        # Status command (local handling)
        if message_text.lower() == 'status':
            return self.get_status_local()
        
        # Quit command - don't execute via controller
        if message_text.lower() == 'quit':
            return "Warning: Use /quit only from the main application. Cannot quit from Telegram."
        
        # All other commands go through Controller
        return self.execute_controller_command(message_text)

    def get_status_local(self):
        """Get status from local streamers list (filtered - no offline)"""
        if not self.streamers:
            return "No streamers configured"
        
        recording = []
        monitoring = []
        
        for streamer in self.streamers:
            if streamer.recording:
                recording.append(streamer)
            elif streamer.running:
                monitoring.append(streamer)
        
        if not recording and not monitoring:
            return "No online models"
        
        status_msg = "*Current Status:*\n\n"
        
        if recording:
            status_msg += "*Recording:*\n"
            for streamer in recording:
                status_msg += f"`{streamer.username}` ({streamer.site})\n"
        
        total = len(recording) + len(monitoring)
        status_msg += f"\nTotal Online: {total} (Recording: {len(recording)}, Monitoring: {len(monitoring)})"
        
        return status_msg

    def handle_message(self, message):
        """Handle incoming Telegram message"""
        try:
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "").strip()
            
            if not text or chat_id != int(self.chat_id):
                return
            
            self.logger.debug(f"Received message: {text}")
            
            # Parse and execute command
            response = self.parse_and_execute_command(text)
            
            if response:
                self.send_message_with_split(response)
            
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
            self.send_message(f"Error processing command: {str(e)}")

    def check_and_notify_changes(self):
        """Check for recording state changes and send notifications"""
        for streamer in self.streamers:
            streamer_id = f"{streamer.siteslug}_{streamer.username}"
            previous_state = self.recording_states.get(streamer_id, False)
            current_state = streamer.recording

            if previous_state != current_state:
                if current_state:
                    message = (
                        f"*[REC] Recording Started*\n"
                        f"*Model:* `{streamer.username}`\n"
                        f"*Site:* `{streamer.site}`\n"
                        f"*Route:* `{getattr(streamer, 'route_description', 'direct')}`\n"
                        f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    self.send_message(message)
                else:
                    message = (
                        f"*[STOP] Recording Stopped*\n"
                        f"*Model:* `{streamer.username}`\n"
                        f"*Site:* `{streamer.site}`\n"
                        f"*Route:* `{getattr(streamer, 'route_description', 'direct')}`\n"
                        f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    self.send_message(message)
                
                self.recording_states[streamer_id] = current_state

    def send_status_update(self):
        """Send periodic status update of all online models"""
        current_time = datetime.now()

        if (current_time - self.last_status_update).total_seconds() < self.status_update_interval:
            return

        recording_models = []
        online_models = []

        for streamer in self.streamers:
            if streamer.recording:
                recording_models.append(streamer)
            elif streamer.running:
                online_models.append(streamer)

        # Only send if there are online models
        if not recording_models and not online_models:
            return

        message = f"*Status Update* - {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        if recording_models:
            message += "*Recording:*\n"
            for model in recording_models:
                message += f"  `{model.username}` ({model.site})\n"

        total = len(recording_models) + len(online_models)
        message += f"\nTotal Online: {total} (Recording: {len(recording_models)}, Monitoring: {len(online_models)})"

        self.send_message_with_split(message)
        self.last_status_update = current_time

    def run(self):
        """Main loop for checking messages and sending notifications"""
        try:
            self.logger.info("Telegram manager started. Waiting for messages...")
            self.send_message("*Telegram Manager Started*\nType /help for available commands")
            
            while True:
                try:
                    # Check for incoming messages
                    updates = self.get_updates()
                    for update in updates:
                        self.last_update_id = update.get("update_id")
                        if "message" in update:
                            self.handle_message(update["message"])
                    
                    # Check for recording state changes
                    self.check_and_notify_changes()
                    self.send_status_update()
                    
                except Exception as e:
                    self.logger.error(f"Error in telegram manager: {e}")
                
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Telegram manager stopped")

    def do_quit(self, _=None, __=None, ___=None):
        CleanExit(self.streamers)()

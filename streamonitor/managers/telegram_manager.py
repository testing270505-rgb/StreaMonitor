import asyncio
from datetime import datetime, timedelta
from time import sleep

from telegram import Bot
from telegram.error import TelegramError

from streamonitor.manager import Manager
from streamonitor.clean_exit import CleanExit
import streamonitor.log as log


class TelegramManager(Manager):
    def __init__(self, streamers, bot_token, chat_id):
        super().__init__(streamers)
        self.logger = log.Logger("telegram_manager")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = Bot(token=bot_token)
        
        # Track recording states to detect changes
        self.recording_states = {}
        
        # Track last status update time
        self.last_status_update = datetime.now()
        self.status_update_interval = 1800  # 30 minutes in seconds
        
    async def send_message(self, message):
        """Send a message to the configured Telegram chat"""
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=message)
            self.logger.debug(f"Sent message: {message}")
        except TelegramError as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
    
    async def check_and_notify_changes(self):
        """Check for recording state changes and send notifications"""
        for streamer in self.streamers:
            if not streamer.running:
                continue
            
            streamer_id = f"{streamer.siteslug}_{streamer.username}"
            previous_state = self.recording_states.get(streamer_id, False)
            current_state = streamer.recording
            
            # Detect changes
            if previous_state != current_state:
                if current_state:
                    # Started recording
                    message = (
                        f"**Recording Started**\n"
                        f"Model: {streamer.username}\n"
                        f"Site: {streamer.site}\n"
                        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    # Stopped recording
                    message = (
                        f"**Recording Stopped**\n"
                        f"Model: {streamer.username}\n"
                        f"Site: {streamer.site}\n"
                        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                
                await self.send_message(message)
                self.recording_states[streamer_id] = current_state
    
    async def send_status_update(self):
        """Send periodic status update of all online models"""
        current_time = datetime.now()
        
        if (current_time - self.last_status_update).total_seconds() < self.status_update_interval:
            return
        
        # Get online/recording models
        online_models = []
        recording_models = []
        
        for streamer in self.streamers:
            if not streamer.running:
                continue
            
            if streamer.recording:
                recording_models.append(streamer)
            elif streamer.sc.value == 0:  # Status.PUBLIC
                online_models.append(streamer)
        
        # Build message
        message = f"📊 **Status Update** - {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        if recording_models:
            message += "**Currently Recording:**\n"
            for model in recording_models:
                message += f"  • {model.username} ({model.site})\n"
        
        if online_models:
            message += "\n**Online (Not Recording):**\n"
            for model in online_models:
                message += f"  • {model.username} ({model.site})\n"
        
        if not recording_models and not online_models:
            message += "No models online"
        
        await self.send_message(message)
        self.last_status_update = current_time
    
    async def run_async(self):
        """Main async loop for checking and sending notifications"""
        while True:
            try:
                await self.check_and_notify_changes()
                await self.send_status_update()
                await asyncio.sleep(10)  # Check every 10 seconds
            except Exception as e:
                self.logger.error(f"Error in telegram manager: {e}")
                await asyncio.sleep(10)
    
    def run(self):
        """Sync wrapper for the async run method"""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            self.logger.info("Telegram manager stopped")
    
    def do_quit(self, _=None, __=None, ___=None):
        CleanExit(self.streamers)()
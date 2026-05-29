import json
import sys
import time

from streamonitor.bot import Bot
from streamonitor.log import Logger

logger = Logger('[CONFIG]').get_logger()
config_loc = "config.json"


def load_config():
    try:
        with open(config_loc, "r+") as f:
            return json.load(f)
    except FileNotFoundError:
        with open(config_loc, "w+") as f:
            json.dump([], f, indent=4)
            return []
    except Exception as e:
        print(e)
        sys.exit(1)


def save_config(config):
    try:
        with open(config_loc, "w+") as f:
            json.dump(config, f, indent=4)

        return True
    except Exception as e:
        print(e)
        sys.exit(1)


def loadStreamers():
    """
    Load streamers from config and establish parent-child relationships for multiplatform models.
    """
    streamers = []
    parent_map = {}  # Map to store parent references: (username, site) -> Bot instance
    
    config = load_config()
    
    # First pass: Create all streamer instances
    for streamer in config:
        username = streamer["username"]
        site = streamer["site"]

        bot_class = Bot.str2site(site)
        if not bot_class:
            logger.warning(f'Unknown site: {site} (user: {username})')
            continue

        streamer_bot = bot_class.fromConfig(streamer)
        streamers.append(streamer_bot)
        streamer_bot.start()
        time.sleep(0.1)
        
        # Store parent references
        parent_username = streamer.get("parent_username")
        parent_site = streamer.get("parent_site")
        if parent_username and parent_site:
            parent_map[(parent_username, parent_site)] = streamer_bot

    # Second pass: Establish parent-child relationships
    for i, streamer_bot in enumerate(streamers):
        config_entry = config[i]
        parent_username = config_entry.get("parent_username")
        parent_site = config_entry.get("parent_site")
        
        if parent_username and parent_site:
            # This is a child stream, find its parent
            parent_bot = None
            for parent in streamers:
                if parent.username == parent_username and parent.site == parent_site:
                    parent_bot = parent
                    break
            
            if parent_bot:
                streamer_bot.parent = parent_bot
                streamer_bot.is_child = True
                parent_bot.children.append(streamer_bot)
                logger.info(f"Established parent-child relationship: {parent_username} [{parent_site}] -> {streamer_bot.username} [{streamer_bot.site}]")
            else:
                logger.warning(f"Parent not found for {streamer_bot.username}: {parent_username} [{parent_site}]")
    
    return streamers

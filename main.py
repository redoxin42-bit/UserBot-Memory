"""
Main entry point for the Hikka-style Telegram UserBot.
Handles configuration loading, interactive authentication, dynamic module discovery, 
and startup sequence.
"""

import os
import sys
import logging
import asyncio
import importlib.util
from typing import List
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from dotenv import load_dotenv

# Define base paths
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR: str = os.path.join(BASE_DIR, "modules")
LOG_FILE: str = os.path.join(BASE_DIR, "userbot.log")

# Setup dual logging to both console and log file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)
logger: logging.Logger = logging.getLogger("UserBot")

# Load configuration from environment file
dotenv_path: str = os.path.join(BASE_DIR, ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    logger.warning(".env file not found. System environment variables will be used.")

API_ID_STR: str | None = os.getenv("API_ID")
API_HASH: str | None = os.getenv("API_HASH")
PHONE: str | None = os.getenv("PHONE")

if not API_ID_STR or not API_HASH or not PHONE:
    logger.error("Missing critical configuration in .env (API_ID, API_HASH, or PHONE)")
    sys.exit(1)

try:
    API_ID: int = int(API_ID_STR)
except ValueError:
    logger.error("API_ID must be an integer value")
    sys.exit(1)

# Initialize Telethon client using the specified session path
session_path: str = os.path.join(BASE_DIR, "userbot")
client: TelegramClient = TelegramClient(session_path, API_ID, API_HASH)


async def authenticate_user() -> None:
    """
    Handles interactive user authentication with the Telegram API.
    Supports phone-based login, verification code input, and 2FA password handling.
    """
    await client.connect()
    if not await client.is_user_authorized():
        logger.info(f"Initiating login sequence for: {PHONE}")
        try:
            await client.send_code_request(PHONE)
            verification_code = input("Please enter the verification code sent to Telegram: ")
            try:
                await client.sign_in(PHONE, verification_code)
            except SessionPasswordNeededError:
                two_factor_password = input("2FA password required. Enter your 2FA password: ")
                await client.sign_in(password=two_factor_password)
        except Exception as err:
            logger.error(f"Authentication failure: {err}")
            sys.exit(1)
    logger.info("Successfully authenticated.")


async def bootstrap_modules() -> int:
    """
    Scans the modules directory, dynamically loads available python files,
    and initializes them via their respective setup functions.

    Returns:
        int: Total number of successfully loaded modules.
    """
    loaded_count: int = 0
    if not os.path.exists(MODULES_DIR):
        os.makedirs(MODULES_DIR)
        logger.info(f"Created empty modules directory: {MODULES_DIR}")

    for file_name in os.listdir(MODULES_DIR):
        if file_name.endswith(".py") and file_name != "__init__.py":
            module_name: str = file_name[:-3]
            file_path: str = os.path.join(MODULES_DIR, file_name)
            try:
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"Unable to retrieve specification for {file_name}")
                
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                if hasattr(module, "setup") and callable(module.setup):
                    module.setup(client)
                    loaded_count += 1
                    logger.info(f"Module '{module_name}' initialized successfully.")
                else:
                    logger.warning(f"Module {file_name} does not contain a valid setup(client) function.")
            except Exception as err:
                logger.exception(f"Failed to load module {file_name} due to an error: {err}")

    return loaded_count


async def start_bot() -> None:
    """
    Manages the complete lifecycle initialization, startup message dispatch, 
    and event execution loop.
    """
    await authenticate_user()
    module_count: int = await bootstrap_modules()

    try:
        startup_text: str = (
            "🤖 UserBot запущен\n"
            f"├ Модулей загружено: {module_count}\n"
            f"├ Сессия: userbot.session\n"
            "└ Версия: 1.0.0"
        )
        await client.send_message("me", startup_text)
        logger.info("Startup notification sent to Saved Messages.")
    except Exception as err:
        logger.error(f"Could not send startup message: {err}")

    logger.info("UserBot is online and listening for commands. Press Ctrl+C to terminate.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("UserBot execution terminated by user request.")

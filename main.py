import os
import json
import logging
import asyncio
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PasswordHashInvalid

# Создаем необходимые папки СРАЗУ при запуске, чтобы избежать ошибок инициализации
os.makedirs("sessions", exist_ok=True)
os.makedirs("modules", exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("host.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("HostManager")

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not BOT_TOKEN or not API_ID or not API_HASH:
    logger.critical("BOT_TOKEN, API_ID или API_HASH отсутствуют в конфигурации!")
    exit(1)

SESSIONS_DIR = "sessions"
MODULES_DIR = "modules"
CONFIG_FILE = os.path.join(SESSIONS_DIR, "config.json")

# Хранилище временных состояний авторизации и запущенных юзерботов
user_states = {}
active_userbots = {}

# Инициализируем управляющего хост-бота
manager_bot = Client(
    name="sessions/manager_bot",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


def save_user_credentials(user_id: int, api_id: str, api_hash: str):
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            pass
    config[str(user_id)] = {"api_id": api_id, "api_hash": api_hash}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)


def load_user_credentials():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def create_default_modules():
    # 1. Модуль Ping (.ping)
    ping_path = os.path.join(MODULES_DIR, "ping.py")
    if not os.path.exists(ping_path):
        with open(ping_path, "w", encoding="utf-8") as f:
            f.write('''import time
from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.me & filters.command("ping", prefixes="."))
async def ping_handler(client: Client, message: Message):
    start_time = time.perf_counter()
    await message.edit_text("<code>Pinging...</code>")
    end_time = time.perf_counter()
    ping_ms = round((end_time - start_time) * 1000, 2)
    await message.edit_text(f"<b>Pong!</b> 🏓\\nЗадержка: <code>{ping_ms} ms</code>")
''')

    # 2. Модуль загрузки модулей (.dlm) с исправленным shutil.move (Anti-Scam)
    dlm_path = os.path.join(MODULES_DIR, "dlm.py")
    if not os.path.exists(dlm_path):
        with open(dlm_path, "w", encoding="utf-8") as f:
            f.write('''import os
import shutil
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger("Userbot.DLM")

@Client.on_message(filters.me & filters.command("dlm", prefixes="."))
async def dlm_handler(client: Client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.edit_text("❌ **Ошибка:** Ответьте на .py файл модуля этой командой.")
        return
        
    doc = message.reply_to_message.document
    if not doc.file_name.endswith(".py"):
        await message.edit_text("❌ **Ошибка:** Модуль должен быть файлом с расширением .py")
        return
        
    await message.edit_text("⏳ **Скачивание и проверка безопасности...**")
    
    # Скачиваем во временный файл
    temp_path = await message.reply_to_message.download()
    
    try:
        with open(temp_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
    except Exception as e:
        await message.edit_text(f"❌ **Ошибка чтения файла:** {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return

    # Проверка на вредоносный код (Anti-Scam)
    suspicious_keywords = [
        "session_string", "bot_token", "shutil.rmtree", 
        "os.system", "subprocess", "eval", "exec"
    ]
    
    found_keywords = [kw for kw in suspicious_keywords if kw.lower() in code.lower()]
    
    if found_keywords:
        os.remove(temp_path)
        keywords_str = ", ".join([f"`{k}`" for k in found_keywords])
        await message.edit_text(
            f"⚠️ **Внимание! Обнаружена угроза (Anti-Scam)!**\\n\\n"
            f"В коде модуля найдены потенциально опасные конструкции:\\n"
            f"📍 {keywords_str}\\n\\n"
            f"Установка заблокирована, файл удален ради безопасности вашего аккаунта."
        )
        return

    # Переносим проверенный модуль (shutil.move корректно работает в Docker)
    dest_path = os.path.join("modules", doc.file_name)
    try:
        shutil.move(temp_path, dest_path)
    except Exception as e:
        await message.edit_text(f"❌ **Ошибка перемещения файла в Docker:** {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return
    
    await message.edit_text(
        f"✅ **Модуль {doc.file_name} успешно установлен!**\\n\\n"
        f"Пожалуйста, перезапустите хост для применения изменений."
    )
''')


# --- ЛОГИКА ХОСТ-БОТА ---

@manager_bot.on_message(filters.private & filters.command("start"))
async def start_handler(client, message: Message):
    user_id = message.from_user.id
    user_states[user_id] = {"step": "waiting_api_id"}
    await message.reply_text(
        "👋 Привет! Это **UserBot Memory**.\n\n"
        "Для продолжения настройки введите ваш **API_ID**:"
    )


@manager_bot.on_message(filters.private & ~filters.command(["start"]))
async def input_handler(client, message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    
    if not state:
        return

    step = state["step"]
    text = message.text.strip() if message.text else ""

    if step == "waiting_api_id":
        state["api_id"] = text
        state["step"] = "waiting_api_hash"
        await message.reply_text("Отлично. Теперь введите ваш **API_HASH**:")

    elif step == "waiting_api_hash":
        state["api_hash"] = text
        state["step"] = "waiting_phone"
        await message.reply_text("Теперь введите ваш **номер телефона** (в формате +79991234567):")

    elif step == "waiting_phone":
        state["phone"] = text
        await message.reply_text("⏳ Инициализирую подключение к Telegram... Пожалуйста, подождите.")
        
        try:
            user_client = Client(
                name=f"sessions/user_{user_id}",
                api_id=int(state["api_id"]),
                api_hash=state["api_hash"],
                phone_number=state["phone"],
                plugins=dict(root="modules")
            )
            await user_client.connect()
            sent_code = await user_client.send_code(state["phone"])
            
            state["client"] = user_client
            state["phone_code_hash"] = sent_code.phone_code_hash
            state["step"] = "waiting_code"
            
            await message.reply_text("💬 Код авторизации отправлен в ваш Telegram. Введите его ниже:")
        except Exception as e:
            await message.reply_text(f"❌ Ошибка подключения: `{e}`\nОтправьте /start, чтобы попробовать снова.")
            user_states.pop(user_id, None)

    elif step == "waiting_code":
        user_client = state["client"]
        try:
            await user_client.sign_in(
                phone_number=state["phone"],
                phone_code_hash=state["phone_code_hash"],
                phone_code=text
            )
            save_user_credentials(user_id, state["api_id"], state["api_hash"])
            await message.reply_text(
                "✅ **Авторизация успешна!** Ваш юзербот запущен.\n\n"
                "• Напишите `.ping` для проверки работы.\n"
                "• Отправьте файл модуля `.py` и напишите в ответ на него `.dlm` для установки."
            )
            await user_client.disconnect()
            await user_client.start()
            active_userbots[user_id] = user_client
            user_states.pop(user_id, None)
            
        except SessionPasswordNeeded:
            state["step"] = "waiting_password"
            await message.reply_text("🔐 Введите ваш облачный пароль (2FA):")
        except PhoneCodeInvalid:
            await message.reply_text("❌ Неверный код. Введите его еще раз:")
        except Exception as e:
            await message.reply_text(f"❌ Ошибка авторизации: `{e}`\nОтправьте /start.")
            user_states.pop(user_id, None)

    elif step == "waiting_password":
        user_client = state["client"]
        try:
            await user_client.check_password(text)
            save_user_credentials(user_id, state["api_id"], state["api_hash"])
            await message.reply_text("✅ **Авторизация успешна!** Ваш юзербот запущен.")
            
            await user_client.disconnect()
            await user_client.start()
            active_userbots[user_id] = user_client
            user_states.pop(user_id, None)
        except PasswordHashInvalid:
            await message.reply_text("❌ Неверный облачный пароль. Попробуйте еще раз:")
        except Exception as e:
            await message.reply_text(f"❌ Ошибка: `{e}`\nОтправьте /start.")
            user_states.pop(user_id, None)


# --- ЗАПУСК АКТИВНЫХ СЕССИЙ ---

async def start_active_userbots():
    configs = load_user_credentials()
    for user_id_str, creds in configs.items():
        user_id = int(user_id_str)
        logger.info(f"Восстановление сессии для пользователя {user_id}...")
        try:
            user_client = Client(
                name=f"sessions/user_{user_id}",
                api_id=int(creds["api_id"]),
                api_hash=creds["api_hash"],
                plugins=dict(root="modules")
            )
            await user_client.start()
            active_userbots[user_id] = user_client
            logger.info(f"Сессия пользователя {user_id} успешно запущена.")
        except Exception as e:
            logger.error(f"Не удалось запустить сессию {user_id}: {e}")


async def main():
    # Генерируем базовые модули (.ping и .dlm)
    create_default_modules()
    
    # Запускаем ранее подключенных пользователей
    await start_active_userbots()
    
    # Запускаем управляющего хост-бота
    logger.info("Запуск управляющего хост-бота...")
    await manager_bot.start()
    
    # Поддерживаем процесс активным
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Хост-менеджер остановлен.")

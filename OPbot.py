import asyncio
import aiohttp
import json
import logging
import sys
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from telegram import (
    Update, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    LabeledPrice
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    filters
)

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8834524362:AAGqnZ3WF20IUTQhqLhC8h9109BE2D04V9s"
JSONBIN_API_KEY = "$2a$10$oQFi.r.b4KoxCupZTsKdzeH6ZktFfBr12SBHnTXgkmRwGBJr1bRdm"
JSONBIN_BIN_ID = "6a8d8008f5f4af5e293ffedd"

ADMIN_IDS = [8669060906]

PREMIUM_PRICE_STARS = 5
PREMIUM_DURATION_DAYS = 30

# ========== КЛАСС ДЛЯ РАБОТЫ С JSONBIN ==========
class JSONBinStorage:
    def __init__(self, api_key: str, bin_id: str):
        self.api_key = api_key
        self.bin_id = bin_id
        self.base_url = f"https://api.jsonbin.io/v3/b/{bin_id}"
        self.headers = {
            "X-Master-Key": api_key,
            "Content-Type": "application/json"
        }
        self.cache = None
        self.cache_time = None
        logger.info("JSONBinStorage инициализирован")
    
    async def get_data(self) -> dict:
        try:
            if self.cache and self.cache_time:
                if datetime.now() - self.cache_time < timedelta(minutes=5):
                    return self.cache
            
            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.cache = data.get("record", {})
                        self.cache_time = datetime.now()
                        return self.cache
                    else:
                        return self._get_default_data()
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return self._get_default_data()
    
    async def update_data(self, data: dict) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(self.base_url, headers=self.headers, json=data) as response:
                    if response.status == 200:
                        self.cache = data
                        self.cache_time = datetime.now()
                        return True
                    return False
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return False
    
    def _get_default_data(self) -> dict:
        return {
            "users": {},
            "subscriptions": [],
            "settings": {
                "button_subscribe_text": "📢 Подписаться",
                "button_verify_text": "✅ Проверить подписку",
                "notification_text": "❌ {name}, подпишитесь на каналы ниже, чтобы я пропускал ваши сообщения!"
            }
        }
    
    async def get_user(self, user_id: int) -> dict:
        data = await self.get_data()
        user_id_str = str(user_id)
        
        if user_id_str not in data["users"]:
            data["users"][user_id_str] = {
                "tariff": "regular",
                "premium_until": None,
                "settings": {}
            }
            await self.update_data(data)
        
        return data["users"][user_id_str]
    
    async def set_tariff(self, user_id: int, tariff: str, duration: Optional[timedelta] = None):
        data = await self.get_data()
        user_id_str = str(user_id)
        
        if user_id_str not in data["users"]:
            data["users"][user_id_str] = {
                "tariff": "regular",
                "premium_until": None,
                "settings": {}
            }
        
        data["users"][user_id_str]["tariff"] = tariff
        
        if tariff == "premium" and duration:
            data["users"][user_id_str]["premium_until"] = (datetime.now() + duration).isoformat()
        elif tariff == "regular":
            data["users"][user_id_str]["premium_until"] = None
        
        await self.update_data(data)
    
    async def extend_premium(self, user_id: int, duration: timedelta) -> Tuple[bool, str]:
        user = await self.get_user(user_id)
        
        if user.get("premium_until"):
            current_premium_until = datetime.fromisoformat(user["premium_until"])
            if current_premium_until > datetime.now():
                new_premium_until = current_premium_until + duration
            else:
                new_premium_until = datetime.now() + duration
        else:
            new_premium_until = datetime.now() + duration
        
        data = await self.get_data()
        user_id_str = str(user_id)
        
        if user_id_str not in data["users"]:
            data["users"][user_id_str] = {
                "tariff": "regular",
                "premium_until": None,
                "settings": {}
            }
        
        data["users"][user_id_str]["tariff"] = "premium"
        data["users"][user_id_str]["premium_until"] = new_premium_until.isoformat()
        
        await self.update_data(data)
        
        return True, new_premium_until.strftime('%d.%m.%Y %H:%M')
    
    async def is_premium(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        
        if user["tariff"] != "premium":
            return False
        
        if user.get("premium_until"):
            premium_until = datetime.fromisoformat(user["premium_until"])
            if premium_until < datetime.now():
                await self.set_tariff(user_id, "regular")
                return False
        
        return True
    
    async def get_premium_info(self, user_id: int) -> Optional[str]:
        user = await self.get_user(user_id)
        
        if user.get("premium_until"):
            premium_until = datetime.fromisoformat(user["premium_until"])
            if premium_until > datetime.now():
                return premium_until.strftime('%d.%m.%Y %H:%M')
        
        return None
    
    async def update_user_settings(self, user_id: int, settings: dict):
        data = await self.get_data()
        user_id_str = str(user_id)
        
        if user_id_str not in data["users"]:
            data["users"][user_id_str] = {
                "tariff": "regular",
                "premium_until": None,
                "settings": {}
            }
        
        data["users"][user_id_str]["settings"].update(settings)
        await self.update_data(data)
    
    async def get_user_settings(self, user_id: int) -> dict:
        user = await self.get_user(user_id)
        data = await self.get_data()
        
        settings = {
            "button_subscribe_text": data["settings"]["button_subscribe_text"],
            "button_verify_text": data["settings"]["button_verify_text"],
            "notification_text": data["settings"]["notification_text"]
        }
        
        user_settings = user.get("settings", {})
        settings.update(user_settings)
        
        return settings
    
    async def get_next_available_id(self) -> int:
        data = await self.get_data()
        subscriptions = data.get("subscriptions", [])
        
        if not subscriptions:
            return 1
        
        used_ids = {sub["id"] for sub in subscriptions}
        
        next_id = 1
        while next_id in used_ids:
            next_id += 1
        
        return next_id
    
    async def add_subscription(self, chat_id: str, link: str) -> dict:
        data = await self.get_data()
        
        new_id = await self.get_next_available_id()
        
        subscription = {
            "id": new_id,
            "chat_id": chat_id,
            "link": link,
            "created_at": datetime.now().isoformat(),
            "expires_at": None
        }
        
        data["subscriptions"].append(subscription)
        data["subscriptions"].sort(key=lambda x: x["id"])
        
        if len(data["subscriptions"]) > 10:
            data["subscriptions"] = data["subscriptions"][-10:]
        
        await self.update_data(data)
        logger.info(f"Добавлена подписка: {link} (ID: {new_id})")
        return subscription
    
    async def delete_subscription(self, sub_number: int) -> Tuple[bool, str]:
        data = await self.get_data()
        subscriptions = data.get("subscriptions", [])
        
        for i, sub in enumerate(subscriptions):
            if sub["id"] == sub_number:
                removed = subscriptions.pop(i)
                await self.update_data(data)
                logger.info(f"Удалена подписка: {removed['link']} (ID: {sub_number})")
                return True, removed["link"]
        
        return False, "Подписка с таким ID не найдена"
    
    async def delete_subscription_by_link(self, link: str) -> Tuple[bool, str]:
        data = await self.get_data()
        subscriptions = data.get("subscriptions", [])
        
        for i, sub in enumerate(subscriptions):
            if sub["link"].lower() == link.lower() or link.lower() in sub["link"].lower():
                removed = subscriptions.pop(i)
                await self.update_data(data)
                logger.info(f"Удалена подписка: {removed['link']}")
                return True, removed["link"]
        
        return False, "Подписка с такой ссылкой не найдена"
    
    async def get_active_subscriptions(self) -> list:
        data = await self.get_data()
        now = datetime.now()
        active = []
        
        for sub in data.get("subscriptions", []):
            if sub.get("expires_at"):
                expires = datetime.fromisoformat(sub["expires_at"])
                if expires < now:
                    continue
            active.append(sub)
        
        return active
    
    async def get_all_subscriptions(self) -> list:
        data = await self.get_data()
        return data.get("subscriptions", [])
    
    async def set_timer(self, sub_number: int, expires_at: datetime) -> bool:
        data = await self.get_data()
        subscriptions = data.get("subscriptions", [])
        
        for i, sub in enumerate(subscriptions):
            if sub["id"] == sub_number:
                subscriptions[i]["expires_at"] = expires_at.isoformat()
                await self.update_data(data)
                return True
        
        return False
    
    async def remove_expired(self):
        data = await self.get_data()
        now = datetime.now()
        
        active = []
        for sub in data.get("subscriptions", []):
            if sub.get("expires_at"):
                expires = datetime.fromisoformat(sub["expires_at"])
                if expires < now:
                    continue
            active.append(sub)
        
        data["subscriptions"] = active
        await self.update_data(data)

# Инициализация
storage = JSONBinStorage(JSONBIN_API_KEY, JSONBIN_BIN_ID)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def parse_time(time_str: str) -> timedelta:
    unit = time_str[-1].lower()
    value = int(time_str[:-1])
    
    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    else:
        raise ValueError("Неверный формат времени")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def format_duration(duration: timedelta) -> str:
    total_seconds = int(duration.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    parts = []
    if days > 0:
        parts.append(f"{days} дн.")
    if hours > 0:
        parts.append(f"{hours} ч.")
    if minutes > 0:
        parts.append(f"{minutes} мин.")
    if seconds > 0 and not parts:
        parts.append(f"{seconds} сек.")
    
    return " ".join(parts) if parts else "0 сек."

async def resolve_chat_id(link: str, context: ContextTypes.DEFAULT_TYPE) -> Tuple[Optional[str], Optional[str]]:
    link = link.strip()
    
    if link.startswith('@'):
        username = link[1:]
        try:
            chat = await context.bot.get_chat(f"@{username}")
            return str(chat.id), None
        except:
            return None, f"Канал @{username} не найден."
    
    elif 't.me/' in link:
        parts = link.split('t.me/')
        if len(parts) > 1:
            chat_ref = parts[1].strip('/')
            
            if chat_ref.startswith('+'):
                try:
                    chat = await context.bot.get_chat(f"https://t.me/{chat_ref}")
                    return str(chat.id), None
                except:
                    return None, "Не удалось получить доступ."
            else:
                try:
                    chat = await context.bot.get_chat(f"@{chat_ref}")
                    return str(chat.id), None
                except:
                    return None, f"Канал @{chat_ref} не найден."
    
    elif link.startswith('-100') or (link.lstrip('-').isdigit() and len(link) > 5):
        try:
            chat = await context.bot.get_chat(link)
            return str(chat.id), None
        except:
            return None, f"Чат с ID {link} не найден."
    
    else:
        try:
            chat = await context.bot.get_chat(f"@{link}")
            return str(chat.id), None
        except:
            return None, f"Канал {link} не найден."
    
    return None, "Неверный формат ссылки."

# ========== КЛАВИАТУРЫ ==========
def get_main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("⚙️ Настройка чата", callback_data="menu_settings")],
        [InlineKeyboardButton("💎 Тарифы", callback_data="menu_tariffs")],
        [InlineKeyboardButton("📋 Мои подписки", callback_data="menu_subscriptions")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📝 Названия кнопок", callback_data="settings_buttons")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_tariffs_menu(is_premium_user: bool = False) -> InlineKeyboardMarkup:
    keyboard = []
    
    if not is_premium_user:
        keyboard.append([InlineKeyboardButton(f"💎 Купить Premium за {PREMIUM_PRICE_STARS} ⭐", callback_data="buy_premium")])
    else:
        keyboard.append([InlineKeyboardButton("✅ Premium активирован", callback_data="premium_active")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(keyboard)

# ========== ОБРАБОТЧИКИ КОМАНД ==========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Пользователь {user.id} запустил бота")
    
    await storage.get_user(user.id)
    is_premium_user = await storage.is_premium(user.id)
    premium_info = await storage.get_premium_info(user.id)
    
    tariff_text = "Premium" if is_premium_user else "Обычный"
    if is_premium_user and premium_info:
        tariff_text += f" (до {premium_info})"
    
    text = f"""
👋 Привет, {user.first_name}!

📊 Ваш тариф: {tariff_text}

📚 Команды:
/set_proverka <ссылка> - Добавить проверку
/del_proverka <ID или ссылка> - Удалить проверку
/addlist - Список проверок
/set_time <ID> <время> - Таймер (Premium)
/check_channel <ссылка> - Проверить канал (Premium)
"""
    
    if is_admin(user.id):
        text += "\n🔐 Админ:\n/premium <id> <время> - Выдать Premium\n"
    
    await update.message.reply_text(text, reply_markup=get_main_menu())

async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ Использование: /premium <user_id> <время>")
        return
    
    try:
        target_user_id = int(context.args[0])
        time_str = context.args[1]
        duration = parse_time(time_str)
    except:
        await update.message.reply_text("❌ Неверный формат.")
        return
    
    success, premium_until = await storage.extend_premium(target_user_id, duration)
    
    if success:
        duration_text = format_duration(duration)
        await update.message.reply_text(
            f"✅ Premium выдан!\n"
            f"👤 ID: {target_user_id}\n"
            f"⏰ На: {duration_text}\n"
            f"📅 До: {premium_until}"
        )

async def set_proverka_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text("❌ Использование: /set_proverka <ссылка>")
        return
    
    link = context.args[0]
    processing_msg = await update.message.reply_text("⏳ Проверяю...")
    
    try:
        chat_id, error = await resolve_chat_id(link, context)
        
        if error:
            await processing_msg.edit_text(f"❌ {error}")
            return
        
        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status not in ["administrator", "creator"]:
                await processing_msg.edit_text("❌ Бот должен быть админом канала!")
                return
        except:
            await processing_msg.edit_text("❌ Бот не может проверить права.")
            return
        
        subscription = await storage.add_subscription(chat_id, link)
        
        await processing_msg.edit_text(
            f"✅ Подписка добавлена!\n"
            f"🔗 {link}\n"
            f"🆔 ID: {subscription['id']}"
        )
        
    except Exception as e:
        await processing_msg.edit_text(f"❌ Ошибка: {e}")

async def del_proverka_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text(
            "❌ Использование: /del_proverka <ID или ссылка>\n"
            "Пример: /del_proverka 1\n"
            "Или: /del_proverka @channel"
        )
        return
    
    arg = context.args[0]
    
    if arg.isdigit():
        sub_id = int(arg)
        success, link = await storage.delete_subscription(sub_id)
    else:
        success, link = await storage.delete_subscription_by_link(arg)
    
    if success:
        await update.message.reply_text(f"✅ Подписка на {link} удалена!")
    else:
        await update.message.reply_text(f"❌ {link}")

async def check_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    is_premium_user = await storage.is_premium(user.id)
    
    if not is_premium_user:
        await update.message.reply_text("❌ Только для Premium!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Использование: /check_channel <ссылка>")
        return
    
    link = context.args[0]
    processing_msg = await update.message.reply_text("⏳ Проверяю...")
    
    chat_id, error = await resolve_chat_id(link, context)
    
    if error:
        await processing_msg.edit_text(f"❌ {error}")
        return
    
    try:
        chat = await context.bot.get_chat(chat_id)
        info_text = f"📋 {chat.title}\n🆔 {chat.id}\n📝 {chat.type}"
        await processing_msg.edit_text(info_text)
    except Exception as e:
        await processing_msg.edit_text(f"❌ Ошибка: {e}")

async def set_time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    is_premium_user = await storage.is_premium(user.id)
    
    if not is_premium_user:
        await update.message.reply_text("❌ Только для Premium!")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ Использование: /set_time <ID> <время>")
        return
    
    try:
        sub_id = int(context.args[0])
        time_str = context.args[1]
        delta = parse_time(time_str)
    except:
        await update.message.reply_text("❌ Неверный формат.")
        return
    
    expires_at = datetime.now() + delta
    success = await storage.set_timer(sub_id, expires_at)
    
    if success:
        await update.message.reply_text(
            f"✅ Таймер установлен!\n"
            f"До: {expires_at.strftime('%d.%m.%Y %H:%M')}"
        )
    else:
        await update.message.reply_text(f"❌ Подписка с ID {sub_id} не найдена.")

async def addlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscriptions = await storage.get_all_subscriptions()
    
    if not subscriptions:
        await update.message.reply_text("📋 Список пуст.\nДобавьте: /set_proverka @channel")
        return
    
    text = "📋 Список проверок:\n\n"
    
    for sub in subscriptions:
        link = sub["link"]
        expires = sub.get("expires_at")
        
        if expires:
            expires_dt = datetime.fromisoformat(expires)
            now = datetime.now()
            if expires_dt > now:
                remaining = expires_dt - now
                hours = remaining.total_seconds() // 3600
                minutes = (remaining.total_seconds() % 3600) // 60
                expires_str = f"осталось {int(hours)}ч {int(minutes)}м"
            else:
                expires_str = "истекла"
        else:
            expires_str = "бессрочно"
        
        text += f"🆔 {sub['id']} | {link} | {expires_str}\n"
    
    text += f"\nВсего: {len(subscriptions)}/10\n"
    text += "Удалить: /del_proverka <ID>"
    
    await update.message.reply_text(text)

# ========== CALLBACK-ЗАПРОСЫ ==========
async def menu_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⚙️ Настройка:", reply_markup=get_settings_menu())

async def menu_tariffs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    is_premium_user = await storage.is_premium(user.id)
    premium_info = await storage.get_premium_info(user.id)
    
    if is_premium_user:
        text = f"💎 Premium\n✅ Активирован!\n📅 До: {premium_info}"
    else:
        text = f"💎 Premium за {PREMIUM_PRICE_STARS} ⭐\nНа {PREMIUM_DURATION_DAYS} дней"
    
    await query.edit_message_text(text, reply_markup=get_tariffs_menu(is_premium_user))

async def buy_premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    try:
        await context.bot.send_invoice(
            chat_id=user.id,
            title="Premium подписка",
            description=f"Premium на {PREMIUM_DURATION_DAYS} дней",
            payload=f"premium_{user.id}_{datetime.now().timestamp()}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Premium", amount=PREMIUM_PRICE_STARS)],
            start_parameter="premium"
        )
        
        await query.edit_message_text(f"💫 Счет отправлен!\nСтоимость: {PREMIUM_PRICE_STARS} ⭐")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    
    duration = timedelta(days=PREMIUM_DURATION_DAYS)
    success, premium_until = await storage.extend_premium(user.id, duration)
    
    if success:
        await message.reply_text(f"🎉 Premium активирован!\n📅 До: {premium_until}")

async def premium_active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ Premium уже активирован!", show_alert=True)

async def menu_subscriptions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    subscriptions = await storage.get_all_subscriptions()
    
    if not subscriptions:
        text = "📋 Список пуст."
    else:
        text = "📋 Проверки:\n\n"
        for sub in subscriptions:
            text += f"🆔 {sub['id']} | {sub['link']}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def back_to_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    is_premium_user = await storage.is_premium(user.id)
    tariff_text = "Premium" if is_premium_user else "Обычный"
    
    text = f"👋 {user.first_name}!\n📊 Тариф: {tariff_text}"
    
    await query.edit_message_text(text, reply_markup=get_main_menu())

async def settings_buttons_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    is_premium_user = await storage.is_premium(user.id)
    
    if not is_premium_user:
        await query.answer("❌ Только для Premium!", show_alert=True)
        return
    
    settings = await storage.get_user_settings(user.id)
    
    keyboard = [
        [InlineKeyboardButton(f"📝 Подписаться: {settings['button_subscribe_text']}", callback_data="edit_subscribe_button")],
        [InlineKeyboardButton(f"📝 Проверить: {settings['button_verify_text']}", callback_data="edit_verify_button")],
        [InlineKeyboardButton("📝 Уведомление", callback_data="edit_notification_text")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_settings")]
    ]
    
    await query.edit_message_text("📝 Настройка:", reply_markup=InlineKeyboardMarkup(keyboard))

# ========== РЕДАКТИРОВАНИЕ ==========
async def edit_subscribe_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['editing'] = 'subscribe_button'
    await query.edit_message_text("📝 Введите текст кнопки 'Подписаться':")

async def edit_verify_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['editing'] = 'verify_button'
    await query.edit_message_text("📝 Введите текст кнопки 'Проверить':")

async def edit_notification_text_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['editing'] = 'notification_text'
    await query.edit_message_text("📝 Введите текст уведомления ({name} для имени):")

async def cancel_editing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'editing' in context.user_data:
        del context.user_data['editing']
    await update.message.reply_text("❌ Отменено.")

# ========== ПРОВЕРКА СООБЩЕНИЙ ==========
async def check_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка сообщений"""
    message = update.message
    
    if not message or not message.from_user or message.from_user.is_bot:
        return
    
    user = message.from_user
    chat_id = message.chat_id
    
    # Обработка редактирования
    if 'editing' in context.user_data:
        editing_type = context.user_data['editing']
        new_text = message.text
        
        if editing_type == 'subscribe_button':
            await storage.update_user_settings(user.id, {"button_subscribe_text": new_text})
            await message.reply_text(f"✅ Обновлено: {new_text}")
        elif editing_type == 'verify_button':
            await storage.update_user_settings(user.id, {"button_verify_text": new_text})
            await message.reply_text(f"✅ Обновлено: {new_text}")
        elif editing_type == 'notification_text':
            await storage.update_user_settings(user.id, {"notification_text": new_text})
            await message.reply_text("✅ Обновлено")
        
        del context.user_data['editing']
        return
    
    # Игнорируем команды
    if message.text and message.text.startswith('/'):
        return
    
    # Проверяем подписки
    subscriptions = await storage.get_active_subscriptions()
    
    if not subscriptions:
        return
    
    not_subscribed = []
    
    for sub in subscriptions:
        try:
            member = await context.bot.get_chat_member(
                chat_id=sub["chat_id"],
                user_id=user.id
            )
            
            if member.status not in ["member", "administrator", "creator"]:
                not_subscribed.append(sub)
                logger.info(f"Пользователь {user.id} не подписан на {sub['link']}")
        except Exception as e:
            logger.error(f"Ошибка проверки {sub['link']}: {e}")
            not_subscribed.append(sub)
            continue
    
    if not_subscribed:
        logger.info(f"Пользователь {user.id} не подписан на {len(not_subscribed)} каналов")
        
        # Удаляем сообщение
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
        
        # Получаем настройки
        settings = await storage.get_user_settings(user.id)
        
        # Создаем клавиатуру
        keyboard = []
        for sub in not_subscribed:
            if sub["link"].startswith("@"):
                url = f"https://t.me/{sub['link'][1:]}"
            elif sub["link"].startswith("https://"):
                url = sub["link"]
            else:
                url = f"https://t.me/{sub['link']}"
            
            keyboard.append([
                InlineKeyboardButton(
                    text=settings["button_subscribe_text"],
                    url=url
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                text=settings["button_verify_text"],
                callback_data="verify_subs"
            )
        ])
        
        # Формируем текст
        notification_text = settings["notification_text"].replace(
            "{name}", user.first_name
        )
        
        # Отправляем НОВОЕ сообщение (не reply)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=notification_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"Уведомление отправлено пользователю {user.id}")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")

async def verify_subscriptions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка подписок по кнопке"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    subscriptions = await storage.get_active_subscriptions()
    
    all_subscribed = True
    not_subscribed = []
    
    for sub in subscriptions:
        try:
            member = await context.bot.get_chat_member(
                chat_id=sub["chat_id"],
                user_id=user.id
            )
            
            if member.status not in ["member", "administrator", "creator"]:
                all_subscribed = False
                not_subscribed.append(sub)
        except:
            continue
    
    if all_subscribed:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=user.id,
            text="✅ Спасибо за подписку!"
        )
    else:
        channels = ", ".join([sub["link"] for sub in not_subscribed])
        await query.answer(f"❌ Не подписаны на: {channels}", show_alert=True)

# ========== ЗАПУСК ==========
def main():
    logger.info("Запуск бота...")
    
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
        logger.error("❌ Токен не указан!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("premium", premium_command))
    application.add_handler(CommandHandler("set_proverka", set_proverka_command))
    application.add_handler(CommandHandler("del_proverka", del_proverka_command))
    application.add_handler(CommandHandler("set_time", set_time_command))
    application.add_handler(CommandHandler("addlist", addlist_command))
    application.add_handler(CommandHandler("check_channel", check_channel_command))
    application.add_handler(CommandHandler("cancel", cancel_editing))
    
    # Callback-запросы
    application.add_handler(CallbackQueryHandler(menu_settings_callback, pattern="^menu_settings$"))
    application.add_handler(CallbackQueryHandler(menu_tariffs_callback, pattern="^menu_tariffs$"))
    application.add_handler(CallbackQueryHandler(menu_subscriptions_callback, pattern="^menu_subscriptions$"))
    application.add_handler(CallbackQueryHandler(back_to_main_callback, pattern="^back_to_main$"))
    application.add_handler(CallbackQueryHandler(buy_premium_callback, pattern="^buy_premium$"))
    application.add_handler(CallbackQueryHandler(premium_active_callback, pattern="^premium_active$"))
    application.add_handler(CallbackQueryHandler(settings_buttons_callback, pattern="^settings_buttons$"))
    application.add_handler(CallbackQueryHandler(edit_subscribe_button_callback, pattern="^edit_subscribe_button$"))
    application.add_handler(CallbackQueryHandler(edit_verify_button_callback, pattern="^edit_verify_button$"))
    application.add_handler(CallbackQueryHandler(edit_notification_text_callback, pattern="^edit_notification_text$"))
    application.add_handler(CallbackQueryHandler(verify_subscriptions_callback, pattern="^verify_subs$"))
    
    # Оплата
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # Сообщения
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_all_messages))
    
    # Ошибки
    application.add_error_handler(error_handler)
    
    # Очистка
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(cleanup_task, interval=3600, first=10)
    
    logger.info("✅ Бот готов!")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

async def cleanup_task(context: ContextTypes.DEFAULT_TYPE):
    await storage.remove_expired()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)
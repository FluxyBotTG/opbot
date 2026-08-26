import json
import random
import asyncio
import requests
import threading
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler
)
import logging

# --- Конфигурация ---
TOKEN = "8881468745:AAF9h_OKXByMvclVIak9EbcBSLO8FYsa5kE"
ADMIN_ID = 8669060906  # ID основателя
JSONBIN_API_KEY = "$2a$10$oQFi.r.b4KoxCupZTsKdzeH6ZktFfBr12SBHnTXgkmRwGBJr1bRdm"
JSONBIN_BIN_ID = "6a8d8b4eda38895dfe0e9076"

# --- Настройка логирования ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Глобальные переменные ---
last_save_time = datetime.now()
save_interval = 30  # секунд
data_lock = threading.Lock()
dirty = False

# --- Класс для работы с JSONBin ---
class JSONBinDB:
    def __init__(self, api_key, bin_id):
        self.api_key = api_key
        self.bin_id = bin_id
        self.base_url = f"https://api.jsonbin.io/v3/b/{bin_id}"
        self.headers = {
            "X-Master-Key": api_key,
            "Content-Type": "application/json"
        }
        
    def get_data(self):
        """Получить все данные из JSONBin"""
        try:
            response = requests.get(self.base_url, headers=self.headers)
            if response.status_code == 200:
                data = response.json()['record']
                default_data = self.get_default_data()
                for key, value in default_data.items():
                    if key not in data:
                        data[key] = value
                return data
            else:
                logger.error(f"Error fetching data: {response.status_code}")
                return self.get_default_data()
        except Exception as e:
            logger.error(f"Exception in get_data: {e}")
            return self.get_default_data()
    
    def update_data(self, data):
        """Обновить данные в JSONBin"""
        try:
            response = requests.put(self.base_url, headers=self.headers, json=data)
            if response.status_code == 200:
                return True
            else:
                logger.error(f"Error updating data: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Exception in update_data: {e}")
            return False
    
    def get_default_data(self):
        """Получить структуру данных по умолчанию"""
        return {
            "users": {},
            "faq": {},
            "black_list": [],
            "admins": [ADMIN_ID],
            "bot_enabled": True,
            "total_users": 0,
            "new_users_today": 0,
            "last_update_day": datetime.now().day
        }

# Инициализация БД
db = JSONBinDB(JSONBIN_API_KEY, JSONBIN_BIN_ID)
data = db.get_data()

# Добавляем поле last_income_time для существующих пользователей
for user_id, user in data['users'].items():
    if 'last_income_time' not in user:
        user['last_income_time'] = datetime.now().isoformat()

# --- Вспомогательные функции ---
def mark_dirty():
    """Пометить данные как измененные"""
    global dirty
    dirty = True

def save_data():
    """Сохранить данные в JSONBin и локальный файл"""
    global dirty, last_save_time
    try:
        # Сохраняем в локальный файл
        with open('bot_data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Пробуем сохранить в JSONBin
        try:
            response = requests.put(
                db.base_url, 
                headers=db.headers, 
                json=data,
                timeout=10
            )
            if response.status_code == 200:
                logger.info("Data saved to JSONBin successfully")
            else:
                logger.warning(f"JSONBin save failed: {response.status_code}")
        except Exception as e:
            logger.warning(f"JSONBin not available: {e}")
        
        dirty = False
        last_save_time = datetime.now()
        return True
    except Exception as e:
        logger.error(f"Save error: {e}")
        return False

def save_data_if_needed():
    """Сохранить данные если они были изменены и прошло достаточно времени"""
    global dirty, last_save_time
    current_time = datetime.now()
    if dirty and (current_time - last_save_time).total_seconds() >= save_interval:
        with data_lock:
            if dirty:
                save_data()

def get_user(user_id):
    """Получить данные пользователя или создать нового"""
    user_id = str(user_id)
    if user_id not in data['users']:
        data['users'][user_id] = {
            'username': '',
            'first_name': '',
            'balance': 0,
            'ore': 0,
            'energy': 100,
            'mines': [],
            'mines_upgrades': {},
            'pickaxe_upgrades': 0,
            'level': 1,
            'exp': 0,
            'exp_to_next': 500,
            'registered_at': datetime.now().isoformat(),
            'last_energy_update': datetime.now().isoformat(),
            'last_income_time': datetime.now().isoformat()
        }
        data['total_users'] += 1
        data['new_users_today'] += 1
        mark_dirty()
    return data['users'][user_id]

def get_rank(balance):
    """Определить ранг по балансу"""
    if balance >= 100_000_000: return "Легенда"
    if balance >= 50_000_000: return "Бизнесмен"
    if balance >= 25_000_000: return "Богач"
    if balance >= 5_000_000: return "Профессионал"
    if balance >= 1_000_000: return "Опытный"
    return "Новичок"

def get_level_multiplier(level):
    """Множитель уровня"""
    if 3 <= level < 5: return 1.5
    if 5 <= level < 10: return 2.0
    if 10 <= level <= 15: return 2.5
    return 1.0

def get_exp_for_level(level):
    """Необходимый опыт для уровня"""
    exp_table = {
        1: 500, 2: 1000, 3: 1500, 4: 2000, 5: 2500,
        6: 3000, 7: 4000, 8: 5000, 9: 6000, 10: 7500,
        11: 10000, 12: 12500, 13: 15000, 14: 17500, 15: 20000
    }
    return exp_table.get(level, 20000)

def get_mine_info(mine_index):
    """Информация о шахте"""
    mines_data = {
        0: {'name': 'Шахта 1', 'cost': 5_000_000, 'income': 50},
        1: {'name': 'Шахта 2', 'cost': 50_000_000, 'income': 250},
        2: {'name': 'Шахта 3', 'cost': 500_000_000, 'income': 2500},
    }
    return mines_data.get(mine_index)

def get_pickaxe_upgrade_cost(user):
    """Стоимость улучшения кирки"""
    return 500 + (user['pickaxe_upgrades'] * 500)

def check_admin(user_id):
    """Проверить права администратора"""
    return user_id in data['admins']

def update_energy(user):
    """Обновить энергию пользователя"""
    now = datetime.now()
    last_update = datetime.fromisoformat(user['last_energy_update'])
    elapsed_seconds = (now - last_update).total_seconds()
    
    if elapsed_seconds >= 10:
        energy_recovered = int(elapsed_seconds / 10)
        if energy_recovered > 0:
            user['energy'] = min(100, user['energy'] + energy_recovered)
            user['last_energy_update'] = now.isoformat()
            mark_dirty()

def mine_income_per_second(user):
    """Рассчитать доход от шахт в секунду"""
    income = 0
    for mine_index in user['mines']:
        base_income = get_mine_info(int(mine_index))['income']
        upgrades = user['mines_upgrades'].get(str(mine_index), 0)
        income += base_income * (1 + upgrades)
    return income

def check_and_add_income(user):
    """Начислить доход от шахт за прошедшее время"""
    if 'last_income_time' not in user:
        user['last_income_time'] = datetime.now().isoformat()
        return 0
    
    try:
        last_time = datetime.fromisoformat(user['last_income_time'])
    except:
        user['last_income_time'] = datetime.now().isoformat()
        return 0
    
    now = datetime.now()
    elapsed_seconds = (now - last_time).total_seconds()
    
    if elapsed_seconds > 0 and user['mines']:
        income_per_sec = mine_income_per_second(user)
        total_income = int(income_per_sec * elapsed_seconds)
        
        if total_income > 0:
            user['balance'] += total_income
            mark_dirty()
        
        user['last_income_time'] = now.isoformat()
        return total_income
    
    user['last_income_time'] = now.isoformat()
    return 0

def format_balance(balance):
    """Форматировать баланс с разделителями тысяч"""
    return f"{balance:,}".replace(',', '.')

def get_top_players(limit=15):
    """Получить топ игроков по балансу"""
    players = []
    for user_id, user_data in data['users'].items():
        if user_data.get('username'):
            name = f"@{user_data['username']}"
        elif user_data.get('first_name'):
            name = user_data['first_name']
        else:
            name = f"ID:{user_id}"
        
        players.append({
            'name': name,
            'balance': user_data['balance'],
            'level': user_data['level']
        })
    
    players.sort(key=lambda x: x['balance'], reverse=True)
    return players[:limit]

def mine_once(user):
    """Выполнить одну добычу руды"""
    if user['energy'] < 5:
        return None, "⚡ Недостаточно энергии!"
    
    base_ore = random.randint(1, 50)
    ore_gained = int(base_ore * (1 + user['pickaxe_upgrades'] * 0.1))
    
    user['ore'] += ore_gained
    user['energy'] -= 5
    
    user['exp'] += ore_gained
    while user['exp'] >= user['exp_to_next']:
        user['exp'] -= user['exp_to_next']
        user['level'] += 1
        user['exp_to_next'] = get_exp_for_level(user['level'])
    
    mark_dirty()
    return ore_gained, None

def mine_keyboard():
    """Клавиатура для сообщения о добыче"""
    keyboard = [
        [InlineKeyboardButton("⛏ Добыть еще раз", callback_data="mine_again"),
         InlineKeyboardButton("Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Клавиатуры ---
def main_menu_keyboard(user_id=None):
    keyboard = []
    
    if user_id and check_admin(user_id):
        keyboard.append([InlineKeyboardButton("⭐️Админ панель бота", callback_data="admin_panel")])
    
    keyboard.append([InlineKeyboardButton("⛏Начать копать", callback_data="start_mining")])
    keyboard.append([
        InlineKeyboardButton("👤Профиль", callback_data="profile"), 
        InlineKeyboardButton("🛍Магазин", callback_data="shop")
    ])
    keyboard.append([
        InlineKeyboardButton("🏆 Топ игроков", callback_data="top_players"),
        InlineKeyboardButton("📋Команды", callback_data="commands")
    ])
    keyboard.append([InlineKeyboardButton("❓Поддержка", callback_data="support")])
    keyboard.append([InlineKeyboardButton("➕Добавить в чат", url="https://t.me/Games_mine_bot?startgroup=true")])
    
    return InlineKeyboardMarkup(keyboard)

def admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("⚙ Настройки бота", callback_data="admin_settings")],
        [InlineKeyboardButton("⛔️ Черный список бота", callback_data="admin_blacklist")],
        [InlineKeyboardButton("💰 Выдать деньги", callback_data="admin_give_money")],
        [InlineKeyboardButton("📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton("📩 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("👥 Управление админами", callback_data="admin_manage_admins")],
        [InlineKeyboardButton("🗑 Удалить пользователя", callback_data="admin_del_user")],
        [InlineKeyboardButton("💾 Сохранить данные", callback_data="admin_save_data")],
        [InlineKeyboardButton("Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def shop_keyboard():
    keyboard = [
        [InlineKeyboardButton("🏭 Магазин шахт", callback_data="shop_mines")],
        [InlineKeyboardButton("🆙 Улучшения шахты", callback_data="shop_mine_upgrades")],
        [InlineKeyboardButton("🆙 Улучшения добычи", callback_data="shop_pickaxe_upgrade")],
        [InlineKeyboardButton("Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def mines_shop_keyboard():
    keyboard = [
        [InlineKeyboardButton("🏭 Купить шахту 1 (5.000.000)", callback_data="buy_mine_0")],
        [InlineKeyboardButton("🏭 Купить шахту 2 (50.000.000)", callback_data="buy_mine_1")],
        [InlineKeyboardButton("🏭 Купить шахту 3 (500.000.000)", callback_data="buy_mine_2")],
        [InlineKeyboardButton("Назад", callback_data="back_to_shop")]
    ]
    return InlineKeyboardMarkup(keyboard)

def mine_upgrades_keyboard(user_id):
    keyboard = []
    user = get_user(user_id)
    for mine_index in user['mines']:
        mine_index = int(mine_index)
        info = get_mine_info(mine_index)
        count = user['mines_upgrades'].get(str(mine_index), 0)
        keyboard.append([InlineKeyboardButton(
            f"⬆️ Улучшить {info['name']} (+{info['income']}/с) | {count} шт.",
            callback_data=f"upgrade_mine_{mine_index}"
        )])
    keyboard.append([InlineKeyboardButton("Назад", callback_data="back_to_shop")])
    return InlineKeyboardMarkup(keyboard)

def pickaxe_upgrade_keyboard(user_id):
    user = get_user(user_id)
    cost = get_pickaxe_upgrade_cost(user)
    keyboard = [
        [InlineKeyboardButton(f"⬆️ Улучшить +1 за {format_balance(cost)}", callback_data="upgrade_pickaxe")],
        [InlineKeyboardButton("Назад", callback_data="back_to_shop")]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_to_main_keyboard():
    keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
    return InlineKeyboardMarkup(keyboard)

# --- Обработчики команд ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    update_energy(user)
    check_and_add_income(user)
    
    user['username'] = update.effective_user.username or ''
    user['first_name'] = update.effective_user.first_name or ''
    mark_dirty()
    
    await update.message.reply_text(
        f"⛏ Добро пожаловать в Шахтер Бот 💎\n\n"
        f"Ты - шахтер!\n"
        f"Добывай кристаллы, покупай улучшения и шахты, заработай как можно больше и попади в топ 1!\n\n"
        f"🎖 Ваш ранг: {get_rank(user['balance'])}\n"
        f"⭐️ Ваш уровень: {user['level']} (x{get_level_multiplier(user['level'])})\n"
        f"🔅 Ваш опыт: {user['exp']}/{user['exp_to_next']}\n\n"
        f"💎 Руда: {user['ore']}\n"
        f"⚡ Энергия: {user['energy']}/100\n"
        f"🏭 Шахты: {len(user['mines'])}\n"
        f"💰 Баланс: {format_balance(user['balance'])} монет\n"
        f"📈 Доход: {mine_income_per_second(user)}/сек\n\n"
        f"❗️Используй кнопки или команду /mine",
        reply_markup=main_menu_keyboard(user_id)
    )

async def cmd_mine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    update_energy(user)
    check_and_add_income(user)
    
    if not data['bot_enabled'] and not check_admin(user_id):
        await update.message.reply_text("❌ Бот временно выключен.")
        return
    
    ore_gained, error = mine_once(user)
    
    if error:
        await update.message.reply_text(
            error,
            reply_markup=back_to_main_keyboard()
        )
        return
    
    await update.message.reply_text(
        f"⛏ Добыча успешная!\n\n"
        f"💎 +{ore_gained} Руды!\n"
        f"⚡️ Ваша энергия: {user['energy']}/100\n"
        f"🪎 Кол-во руды: {user['ore']}",
        reply_markup=mine_keyboard()
    )

async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    update_energy(user)
    income_added = check_and_add_income(user)
    
    mines_str = ', '.join([get_mine_info(int(i))['name'] for i in user['mines']]) if user['mines'] else 'Нет шахт'
    income_per_second = mine_income_per_second(user)
    income_per_minute = income_per_second * 60
    income_per_hour = income_per_second * 3600
    
    income_msg = ""
    if income_added > 0:
        income_msg = f"\n💵 Начислено с шахт: +{format_balance(income_added)} монет"
    
    await update.message.reply_text(
        f"👤 Ваш профиль:\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"🎖 Ваш ранг: {get_rank(user['balance'])}\n"
        f"🆔 Ваш ID: {user_id}\n"
        f"💰 Ваш баланс: {format_balance(user['balance'])} монет\n"
        f"💎 Руда: {user['ore']}\n"
        f"⚡ Энергия: {user['energy']}/100\n"
        f"🆙 Ваши улучшения: {user['pickaxe_upgrades']}\n\n"
        f"🏭 Ваши шахты: {mines_str}\n"
        f"🆙 Улучшения шахты: {sum(user['mines_upgrades'].values())}\n"
        f"📈 Доход от шахт:\n"
        f"  • {format_balance(income_per_second)}/сек\n"
        f"  • {format_balance(income_per_minute)}/мин\n"
        f"  • {format_balance(income_per_hour)}/час"
        f"{income_msg}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Нажмите на «Назад» чтобы вернуться в меню.",
        reply_markup=back_to_main_keyboard()
    )

async def cmd_top_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ игроков по балансу"""
    for user_id, user in data['users'].items():
        check_and_add_income(user)
    
    top_players = get_top_players(15)
    
    if not top_players:
        await update.message.reply_text("Пока нет игроков в топе.")
        return
    
    top_text = "🏆 Топ игроков:\n"
    top_text += "━━━━━━━━━━━━━━━━\n\n"
    
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, player in enumerate(top_players, 1):
        if i in medals:
            prefix = medals[i]
        else:
            prefix = f"{i}."
        
        balance_formatted = format_balance(player['balance'])
        top_text += f"{prefix} {player['name']} - {balance_formatted} монет\n"
    
    top_text += "\n━━━━━━━━━━━━━━━━"
    
    await update.message.reply_text(
        top_text,
        reply_markup=back_to_main_keyboard()
    )

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику пользователя (свою или по reply/ID)"""
    
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        user = get_user(target_id)
        check_and_add_income(user)
        await update.message.reply_text(
            f"👤 Профиль пользователя {target_id}:\n"
            f"🎖 Ранг: {get_rank(user['balance'])}\n"
            f"💰 Баланс: {format_balance(user['balance'])} монет\n"
            f"💎 Руда: {user['ore']}\n"
            f"⚡ Энергия: {user['energy']}/100\n"
            f"🏭 Шахты: {len(user['mines'])}"
        )
        return
    
    args = context.args
    if args and args[0].isdigit():
        target_id = args[0]
        user = get_user(target_id)
        check_and_add_income(user)
        await update.message.reply_text(
            f"👤 Профиль пользователя {target_id}:\n"
            f"🎖 Ранг: {get_rank(user['balance'])}\n"
            f"💰 Баланс: {format_balance(user['balance'])} монет\n"
            f"💎 Руда: {user['ore']}\n"
            f"⚡ Энергия: {user['energy']}/100\n"
            f"🏭 Шахты: {len(user['mines'])}"
        )
    else:
        user_id = update.effective_user.id
        user = get_user(user_id)
        check_and_add_income(user)
        await update.message.reply_text(
            f"👤 Ваш профиль:\n"
            f"🎖 Ранг: {get_rank(user['balance'])}\n"
            f"💰 Баланс: {format_balance(user['balance'])} монет\n"
            f"💎 Руда: {user['ore']}\n"
            f"⚡ Энергия: {user['energy']}/100\n"
            f"🏭 Шахты: {len(user['mines'])}\n\n"
            f"Использование:\n"
            f"/stats - своя статистика\n"
            f"/stats [ID] - статистика по ID\n"
            f"Ответьте на сообщение + /stats - статистика пользователя"
        )

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    moscow_time = datetime.now() + timedelta(hours=3)
    await update.message.reply_text(
        f"🏓 Пинг: {context.bot.latency*1000:.2f} мс\n"
        f"🕐 Время (МСК): {moscow_time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать ID пользователя (свой или по reply)"""
    
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        await update.message.reply_text(
            f"👤 Информация о пользователе:\n"
            f"🆔 ID: {replied_user.id}\n"
            f"👤 Имя: {replied_user.first_name}\n"
            f"📝 Username: @{replied_user.username if replied_user.username else 'нет'}"
        )
    else:
        await update.message.reply_text(
            f"👤 Ваша информация:\n"
            f"🆔 Ваш ID: {update.effective_user.id}\n"
            f"👤 Имя: {update.effective_user.first_name}\n"
            f"📝 Username: @{update.effective_user.username if update.effective_user.username else 'нет'}"
        )

async def cmd_sell_ore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    check_and_add_income(user)
    
    if user['ore'] > 0:
        earnings = user['ore'] * 10
        user['balance'] += earnings
        user['ore'] = 0
        mark_dirty()
        await update.message.reply_text(
            f"✅ Продажа руды успешна!\n"
            f"💰 Заработано: {format_balance(earnings)} монет\n"
            f"🏦 Ваш баланс: {format_balance(user['balance'])} монет"
        )
    else:
        await update.message.reply_text("❌ У вас нет руды для продажи!")

async def cmd_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для принудительного сохранения данных: /save"""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    msg = await update.message.reply_text("💾 Сохраняю данные...")
    
    success = save_data()
    
    if success:
        total_balance = sum(u['balance'] for u in data['users'].values())
        await msg.edit_text(
            f"✅ Данные успешно сохранены!\n\n"
            f"📊 Статистика:\n"
            f"👥 Пользователей: {data['total_users']}\n"
            f"💰 Всего монет: {format_balance(total_balance)}\n"
            f"🏭 Всего шахт: {sum(len(u['mines']) for u in data['users'].values())}\n"
            f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        await msg.edit_text(
            f"❌ Ошибка при сохранении данных!\n"
            f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

async def cmd_teach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для обучения бота: /teach вопрос | ответ"""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде!")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /teach вопрос | ответ")
        return
    
    text = ' '.join(context.args)
    if '|' not in text:
        await update.message.reply_text("Использование: /teach вопрос | ответ")
        return
    
    question, answer = text.split('|', 1)
    question = question.strip().lower()
    answer = answer.strip()
    
    if not question or not answer:
        await update.message.reply_text("Вопрос и ответ не могут быть пустыми!")
        return
    
    data['faq'][question] = answer
    mark_dirty()
    
    await update.message.reply_text(f"✅ Обучение успешно!\nВопрос: {question}\nОтвет: {answer}")

async def cmd_permban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заблокировать пользователя (по ID или reply)"""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    if update.message.reply_to_message:
        target_id = str(update.message.reply_to_message.from_user.id)
        if target_id not in data['black_list']:
            data['black_list'].append(target_id)
            mark_dirty()
            await update.message.reply_text(f"✅ Пользователь {target_id} добавлен в черный список.")
        else:
            await update.message.reply_text(f"❌ Пользователь {target_id} уже в черном списке.")
        return
    
    args = context.args
    if args and args[0].isdigit():
        target_id = args[0]
        if target_id not in data['black_list']:
            data['black_list'].append(target_id)
            mark_dirty()
            await update.message.reply_text(f"✅ Пользователь {target_id} добавлен в черный список.")
        else:
            await update.message.reply_text(f"❌ Пользователь {target_id} уже в черном списке.")
    else:
        await update.message.reply_text(
            "Использование:\n"
            "/permban [ID] - заблокировать по ID\n"
            "Ответьте на сообщение + /permban - заблокировать пользователя"
        )

async def cmd_unperm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разблокировать пользователя (по ID или reply)"""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    if update.message.reply_to_message:
        target_id = str(update.message.reply_to_message.from_user.id)
        if target_id in data['black_list']:
            data['black_list'].remove(target_id)
            mark_dirty()
            await update.message.reply_text(f"✅ Пользователь {target_id} убран из черного списка.")
        else:
            await update.message.reply_text(f"❌ Пользователь {target_id} не в черном списке.")
        return
    
    args = context.args
    if args and args[0].isdigit():
        target_id = args[0]
        if target_id in data['black_list']:
            data['black_list'].remove(target_id)
            mark_dirty()
            await update.message.reply_text(f"✅ Пользователь {target_id} убран из черного списка.")
        else:
            await update.message.reply_text(f"❌ Пользователь {target_id} не в черном списке.")
    else:
        await update.message.reply_text(
            "Использование:\n"
            "/unperm [ID] - разблокировать по ID\n"
            "Ответьте на сообщение + /unperm - разблокировать пользователя"
        )

async def cmd_givemoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдать деньги пользователю (по ID или reply)"""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    if update.message.reply_to_message:
        target_id = str(update.message.reply_to_message.from_user.id)
        
        args = context.args
        if args and args[0].isdigit():
            amount = int(args[0])
            user = get_user(target_id)
            user['balance'] += amount
            mark_dirty()
            await update.message.reply_text(
                f"✅ Пользователю {target_id} выдано {format_balance(amount)} монет.\n"
                f"💰 Новый баланс: {format_balance(user['balance'])} монет"
            )
        else:
            await update.message.reply_text(
                "Использование с ответом:\n"
                "Ответьте на сообщение + /givemoney [сумма]\n"
                "Пример: /givemoney 1000"
            )
        return
    
    args = context.args
    if len(args) >= 2 and args[0].isdigit() and args[1].isdigit():
        target_id = args[0]
        amount = int(args[1])
        user = get_user(target_id)
        user['balance'] += amount
        mark_dirty()
        await update.message.reply_text(
            f"✅ Пользователю {target_id} выдано {format_balance(amount)} монет.\n"
            f"💰 Новый баланс: {format_balance(user['balance'])} монет"
        )
    else:
        await update.message.reply_text(
            "Использование:\n"
            "/givemoney [ID] [сумма] - выдать по ID\n"
            "Ответьте на сообщение + /givemoney [сумма] - выдать пользователю"
        )

async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить администратора: /addadmin [ID]"""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    args = context.args
    if args and args[0].isdigit():
        target_id = int(args[0])
        if target_id not in data['admins']:
            data['admins'].append(target_id)
            mark_dirty()
            await update.message.reply_text(f"✅ Пользователь {target_id} добавлен в администраторы.")
        else:
            await update.message.reply_text(f"❌ Пользователь {target_id} уже администратор.")
    else:
        await update.message.reply_text("Использование: /addadmin [ID]")

async def cmd_removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить администратора: /removeadmin [ID]"""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    args = context.args
    if args and args[0].isdigit():
        target_id = int(args[0])
        if target_id == ADMIN_ID:
            await update.message.reply_text("❌ Нельзя удалить основателя!")
            return
        if target_id in data['admins']:
            data['admins'].remove(target_id)
            mark_dirty()
            await update.message.reply_text(f"✅ Пользователь {target_id} удален из администраторов.")
        else:
            await update.message.reply_text(f"❌ Пользователь {target_id} не администратор.")
    else:
        await update.message.reply_text("Использование: /removeadmin [ID]")

async def cmd_deluser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить пользователя из базы данных: /deluser [ID]"""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    # Проверяем, есть ли ответ на сообщение
    if update.message.reply_to_message:
        target_id = str(update.message.reply_to_message.from_user.id)
    else:
        args = context.args
        if args and args[0].isdigit():
            target_id = args[0]
        else:
            await update.message.reply_text(
                "Использование:\n"
                "/deluser [ID] - удалить по ID\n"
                "Ответьте на сообщение + /deluser - удалить пользователя"
            )
            return
    
    # Нельзя удалить основателя
    if int(target_id) == ADMIN_ID:
        await update.message.reply_text("❌ Нельзя удалить основателя бота!")
        return
    
    if target_id in data['users']:
        user = data['users'][target_id]
        username = user.get('username', '')
        first_name = user.get('first_name', '')
        balance = user.get('balance', 0)
        
        del data['users'][target_id]
        
        if data['total_users'] > 0:
            data['total_users'] -= 1
        
        if int(target_id) in data['admins']:
            data['admins'].remove(int(target_id))
        
        if target_id in data['black_list']:
            data['black_list'].remove(target_id)
        
        mark_dirty()
        save_data()
        
        name = f"@{username}" if username else first_name
        await update.message.reply_text(
            f"✅ Пользователь удален!\n\n"
            f"🆔 ID: {target_id}\n"
            f"👤 Имя: {name}\n"
            f"💰 Баланс: {format_balance(balance)} монет\n"
            f"📊 Осталось: {data['total_users']}"
        )
    else:
        await update.message.reply_text(f"❌ Пользователь {target_id} не найден.")

async def cmd_delallusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить всех пользователей: /delallusers confirm"""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    if not context.args or context.args[0].lower() != 'confirm':
        await update.message.reply_text(
            "⚠️ Внимание! Вы собираетесь удалить ВСЕХ пользователей!\n\n"
            "Для подтверждения используйте:\n"
            "/delallusers confirm"
        )
        return
    
    users_count = len(data['users'])
    
    data['users'] = {}
    data['total_users'] = 0
    data['new_users_today'] = 0
    data['admins'] = [ADMIN_ID]
    data['black_list'] = []
    
    mark_dirty()
    save_data()
    
    await update.message.reply_text(
        f"✅ Все пользователи удалены!\n\n"
        f"👥 Удалено пользователей: {users_count}\n"
        f"👑 Администраторы сброшены (остался только основатель)\n"
        f"⛔️ Черный список очищен"
    )

# --- Callback Query Handlers ---
async def handle_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    await query.edit_message_text(
        "Главное меню:",
        reply_markup=main_menu_keyboard(user_id)
    )

async def handle_back_to_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🛍 Магазин\n━━━━━━━━━━━━━━━━",
        reply_markup=shop_keyboard()
    )

async def handle_mine_again(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для кнопки 'Добыть еще раз'"""
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    update_energy(user)
    check_and_add_income(user)
    
    if not data['bot_enabled'] and not check_admin(user_id):
        await query.answer("❌ Бот временно выключен", show_alert=True)
        return
    
    ore_gained, error = mine_once(user)
    
    if error:
        await query.answer(error, show_alert=True)
        return
    
    await query.answer(f"⛏ Добыто {ore_gained} руды!")
    await query.edit_message_text(
        f"⛏ Добыча успешная!\n\n"
        f"💎 +{ore_gained} Руды!\n"
        f"⚡️ Ваша энергия: {user['energy']}/100\n"
        f"🪎 Кол-во руды: {user['ore']}",
        reply_markup=mine_keyboard()
    )

async def handle_top_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для кнопки топа игроков"""
    query = update.callback_query
    
    for user_id, user in data['users'].items():
        check_and_add_income(user)
    
    top_players = get_top_players(15)
    
    if not top_players:
        await query.answer("Пока нет игроков в топе.", show_alert=True)
        return
    
    top_text = "🏆 Топ игроков:\n"
    top_text += "━━━━━━━━━━━━━━━━\n\n"
    
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, player in enumerate(top_players, 1):
        if i in medals:
            prefix = medals[i]
        else:
            prefix = f"{i}."
        
        balance_formatted = format_balance(player['balance'])
        top_text += f"{prefix} {player['name']} - {balance_formatted} монет\n"
    
    top_text += "\n━━━━━━━━━━━━━━━━"
    
    await query.answer()
    await query.edit_message_text(
        top_text,
        reply_markup=back_to_main_keyboard()
    )

async def handle_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    await query.edit_message_text(
        "Админ панель бота",
        reply_markup=admin_panel_keyboard()
    )

async def handle_admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton(
            f"{'✅' if data['bot_enabled'] else '❌'} Бот {'включен' if data['bot_enabled'] else 'выключен'}", 
            callback_data="toggle_bot"
        )],
        [InlineKeyboardButton("Назад", callback_data="admin_panel")]
    ]
    
    await query.answer()
    await query.edit_message_text(
        "⚙ Настройка бота",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_toggle_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    data['bot_enabled'] = not data['bot_enabled']
    mark_dirty()
    
    await query.answer(f"Бот {'включен' if data['bot_enabled'] else 'выключен'}")
    await handle_admin_settings(update, context)

async def handle_admin_save_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки сохранения данных"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    if save_data():
        await query.answer("✅ Данные сохранены!", show_alert=True)
        await query.edit_message_text(
            f"✅ Данные успешно сохранены!\n"
            f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await query.answer("❌ Ошибка сохранения!", show_alert=True)

async def handle_admin_del_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки удаления пользователя"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    keyboard = [[InlineKeyboardButton("Назад", callback_data="admin_panel")]]
    
    await query.answer()
    await query.edit_message_text(
        "🗑 Удаление пользователя\n\n"
        "Используйте команду:\n"
        "/deluser [ID]\n\n"
        "Или ответьте на сообщение:\n"
        "/deluser\n\n"
        "Для удаления всех:\n"
        "/delallusers confirm",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_admin_manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление администраторами"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить админа", callback_data="admin_add_prompt")],
        [InlineKeyboardButton("➖ Удалить админа", callback_data="admin_remove_prompt")],
        [InlineKeyboardButton("Назад", callback_data="admin_panel")]
    ]
    
    admins_list = '\n'.join([f"• {aid}" for aid in data['admins']])
    
    await query.answer()
    await query.edit_message_text(
        f"👥 Управление администраторами\n\n"
        f"Текущие админы:\n{admins_list}\n\n"
        f"Для добавления: /addadmin [ID]\n"
        f"Для удаления: /removeadmin [ID]",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_admin_add_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос на добавление админа"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    await query.edit_message_text(
        "➕ Добавление администратора\n\n"
        "Используйте команду:\n"
        "/addadmin [ID]\n\n"
        "Например:\n"
        "/addadmin 123456789",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin_manage_admins")]])
    )

async def handle_admin_remove_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос на удаление админа"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    await query.edit_message_text(
        "➖ Удаление администратора\n\n"
        "Используйте команду:\n"
        "/removeadmin [ID]\n\n"
        "Например:\n"
        "/removeadmin 123456789",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin_manage_admins")]])
    )

async def handle_admin_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    keyboard = [[InlineKeyboardButton("Назад", callback_data="admin_panel")]]
    
    black_list_str = '\n'.join(data['black_list']) if data['black_list'] else 'Список пуст'
    
    await query.answer()
    await query.edit_message_text(
        f"⛔️ Черный список:\n\n{black_list_str}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_admin_give_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    keyboard = [[InlineKeyboardButton("Назад", callback_data="admin_panel")]]
    
    await query.answer()
    await query.edit_message_text(
        "💰 Выдача денег\n\n"
        "Используйте команду:\n"
        "/givemoney [ID] [сумма]\n\n"
        "Или ответьте на сообщение:\n"
        "/givemoney [сумма]",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    total_money = sum(user['balance'] for user in data['users'].values())
    total_mines = sum(len(user['mines']) for user in data['users'].values())
    
    stats_text = (
        f"📊 Статистика бота\n\n"
        f"Всего пользователей: {data['total_users']}\n"
        f"Новых сегодня: {data['new_users_today']}\n"
        f"Всего монет: {format_balance(total_money)}\n"
        f"Всего шахт: {total_mines}\n"
        f"Всего в ЧС: {len(data['black_list'])}\n"
        f"Админов: {len(data['admins'])}\n"
        f"FAQs: {len(data['faq'])}"
    )
    
    keyboard = [[InlineKeyboardButton("Назад", callback_data="admin_panel")]]
    
    await query.answer()
    await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not check_admin(user_id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("📨 Рассылка в ЛС", callback_data="broadcast_ls")],
        [InlineKeyboardButton("📢 Рассылка в чаты", callback_data="broadcast_chats")],
        [InlineKeyboardButton("Назад", callback_data="admin_panel")]
    ]
    
    await query.answer()
    await query.edit_message_text(
        "📩 Рассылка\n\nВыберите куда отправить:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_start_mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    update_energy(user)
    check_and_add_income(user)
    
    if not data['bot_enabled'] and not check_admin(user_id):
        await query.answer("❌ Бот временно выключен", show_alert=True)
        return
    
    ore_gained, error = mine_once(user)
    
    if error:
        await query.answer(error, show_alert=True)
        return
    
    await query.answer(f"⛏ Добыто {ore_gained} руды!")
    await query.edit_message_text(
        f"⛏ Добыча успешная!\n\n"
        f"💎 +{ore_gained} Руды!\n"
        f"⚡️ Ваша энергия: {user['energy']}/100\n"
        f"🪎 Кол-во руды: {user['ore']}",
        reply_markup=mine_keyboard()
    )

async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    update_energy(user)
    income_added = check_and_add_income(user)
    
    mines_str = ', '.join([get_mine_info(int(i))['name'] for i in user['mines']]) if user['mines'] else 'Нет шахт'
    income_per_second = mine_income_per_second(user)
    income_per_minute = income_per_second * 60
    
    income_msg = ""
    if income_added > 0:
        income_msg = f"\n💵 Начислено с шахт: +{format_balance(income_added)} монет"
    
    await query.answer()
    await query.edit_message_text(
        f"👤 Ваш профиль:\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"🎖 Ваш ранг: {get_rank(user['balance'])}\n"
        f"🆔 Ваш ID: {user_id}\n"
        f"💰 Ваш баланс: {format_balance(user['balance'])} монет\n"
        f"💎 Руда: {user['ore']}\n"
        f"⚡ Энергия: {user['energy']}/100\n"
        f"🆙 Ваши улучшения: {user['pickaxe_upgrades']}\n\n"
        f"🏭 Ваши шахты: {mines_str}\n"
        f"🆙 Улучшения шахты: {sum(user['mines_upgrades'].values())}\n"
        f"📈 Доход от шахт: {format_balance(income_per_second)}/сек ({format_balance(income_per_minute)}/мин)"
        f"{income_msg}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Нажмите на «Назад» чтобы вернуться в меню.",
        reply_markup=back_to_main_keyboard()
    )

async def handle_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🛍 Магазин\n━━━━━━━━━━━━━━━━",
        reply_markup=shop_keyboard()
    )

async def handle_shop_mines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🏭 Магазин шахт\n━━━━━━━━━━━━━━━━\n"
        "Шахта 1 | 5.000.000 монет | 50/сек\n"
        "Шахта 2 | 50.000.000 монет | 250/сек\n"
        "Шахта 3 | 500.000.000 монет | 2500/сек",
        reply_markup=mines_shop_keyboard()
    )

async def handle_buy_mine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    check_and_add_income(user)
    
    mine_index = int(query.data.split('_')[-1])
    mine_info = get_mine_info(mine_index)
    
    if str(mine_index) in user['mines']:
        await query.answer("Эта шахта уже куплена!", show_alert=True)
        return
    
    if user['balance'] < mine_info['cost']:
        await query.answer("Недостаточно средств!", show_alert=True)
        return
    
    user['balance'] -= mine_info['cost']
    user['mines'].append(str(mine_index))
    user['last_income_time'] = datetime.now().isoformat()
    mark_dirty()
    
    await query.answer(f"✅ Шахта куплена!")
    await query.edit_message_text(
        f"✅ Шахта {mine_info['name']} куплена!\n"
        f"💰 Ваш баланс: {format_balance(user['balance'])} монет\n"
        f"📈 Новый доход: {mine_income_per_second(user)}/сек",
        reply_markup=shop_keyboard()
    )

async def handle_shop_mine_upgrades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    check_and_add_income(user)
    
    if not user['mines']:
        await query.answer("У вас нет шахт для улучшения!", show_alert=True)
        return
    
    await query.answer()
    await query.edit_message_text(
        "🆙 Улучшения шахты\n━━━━━━━━━━━━━━━━\n"
        "Выберите шахту для улучшения:",
        reply_markup=mine_upgrades_keyboard(user_id)
    )

async def handle_upgrade_mine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    check_and_add_income(user)
    
    mine_index = int(query.data.split('_')[-1])
    
    if str(mine_index) not in user['mines']:
        await query.answer("Шахта не куплена!", show_alert=True)
        return
    
    mine_info = get_mine_info(mine_index)
    upgrade_cost = mine_info['cost'] // 10
    
    if user['balance'] < upgrade_cost:
        await query.answer("Недостаточно средств!", show_alert=True)
        return
    
    user['balance'] -= upgrade_cost
    user['mines_upgrades'][str(mine_index)] = user['mines_upgrades'].get(str(mine_index), 0) + 1
    user['last_income_time'] = datetime.now().isoformat()
    mark_dirty()
    
    new_income = mine_info['income'] * (1 + user['mines_upgrades'][str(mine_index)])
    
    await query.answer(f"✅ Улучшение куплено!")
    await query.edit_message_text(
        f"✅ Улучшение для {mine_info['name']} куплено!\n"
        f"📈 Новый доход шахты: {format_balance(new_income)}/сек",
        reply_markup=mine_upgrades_keyboard(user_id)
    )

async def handle_shop_pickaxe_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    check_and_add_income(user)
    
    await query.answer()
    await query.edit_message_text(
        f"🆙 Улучшение добычи\n━━━━━━━━━━━━━━━━\n"
        f"Ваши улучшения: {user['pickaxe_upgrades']}",
        reply_markup=pickaxe_upgrade_keyboard(user_id)
    )

async def handle_upgrade_pickaxe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    check_and_add_income(user)
    
    cost = get_pickaxe_upgrade_cost(user)
    
    if user['balance'] < cost:
        await query.answer("Недостаточно средств!", show_alert=True)
        return
    
    user['balance'] -= cost
    user['pickaxe_upgrades'] += 1
    mark_dirty()
    
    await query.answer(f"✅ Улучшение куплено!")
    await query.edit_message_text(
        f"✅ Улучшение добычи куплено!\n"
        f"🆙 Ваши улучшения: {user['pickaxe_upgrades']}",
        reply_markup=pickaxe_upgrade_keyboard(user_id)
    )

async def handle_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❓ Поддержка\n\n"
        "Задайте ваш вопрос, и я постараюсь найти ответ!\n"
        "Если я не знаю ответа, посетите форум @forum_minebot",
        reply_markup=back_to_main_keyboard()
    )

async def handle_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📋 Команды бота:\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "📌 Основные:\n"
        "/start - запустить бота\n"
        "/profile - открыть профиль\n"
        "/stats - посмотреть профиль пользователя\n"
        "/top_money - топ игроков по балансу\n"
        "/ping - посмотреть пинг бота и время(мск)\n"
        "/id - узнать ID пользователя\n"
        "/sellore - продать руду\n\n"
        "⛏ Заработок:\n"
        "/mine - начать копать руду\n\n"
        "💡 Подсказка:\n"
        "Некоторые команды работают через ответ на сообщение (reply)!",
        reply_markup=back_to_main_keyboard()
    )

# --- Message Handler для поддержки ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if str(user_id) in data['black_list']:
        await update.message.reply_text("❌ Вы заблокированы в боте.")
        return
    
    if not data['bot_enabled'] and not check_admin(user_id):
        await update.message.reply_text("❌ Бот временно выключен.")
        return
    
    message_text = update.message.text.lower()
    
    if message_text in data['faq']:
        await update.message.reply_text(data['faq'][message_text])
        return
    
    for question, answer in data['faq'].items():
        if any(word in message_text for word in question.split()):
            await update.message.reply_text(answer)
            return

def main():
    """Запуск бота"""
    application = Application.builder().token(TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("mine", cmd_mine))
    application.add_handler(CommandHandler("profile", cmd_profile))
    application.add_handler(CommandHandler("top_money", cmd_top_money))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("ping", cmd_ping))
    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(CommandHandler("sellore", cmd_sell_ore))
    application.add_handler(CommandHandler("save", cmd_save))
    application.add_handler(CommandHandler("teach", cmd_teach))
    application.add_handler(CommandHandler("permban", cmd_permban))
    application.add_handler(CommandHandler("unperm", cmd_unperm))
    application.add_handler(CommandHandler("givemoney", cmd_givemoney))
    application.add_handler(CommandHandler("addadmin", cmd_addadmin))
    application.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    application.add_handler(CommandHandler("deluser", cmd_deluser))
    application.add_handler(CommandHandler("delallusers", cmd_delallusers))
    
    # Callback Query Handlers
    application.add_handler(CallbackQueryHandler(handle_mine_again, pattern="^mine_again$"))
    application.add_handler(CallbackQueryHandler(handle_back_to_main, pattern="^back_to_main$"))
    application.add_handler(CallbackQueryHandler(handle_back_to_shop, pattern="^back_to_shop$"))
    application.add_handler(CallbackQueryHandler(handle_top_players, pattern="^top_players$"))
    application.add_handler(CallbackQueryHandler(handle_admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(handle_admin_settings, pattern="^admin_settings$"))
    application.add_handler(CallbackQueryHandler(handle_toggle_bot, pattern="^toggle_bot$"))
    application.add_handler(CallbackQueryHandler(handle_admin_save_data, pattern="^admin_save_data$"))
    application.add_handler(CallbackQueryHandler(handle_admin_del_user, pattern="^admin_del_user$"))
    application.add_handler(CallbackQueryHandler(handle_admin_manage_admins, pattern="^admin_manage_admins$"))
    application.add_handler(CallbackQueryHandler(handle_admin_add_prompt, pattern="^admin_add_prompt$"))
    application.add_handler(CallbackQueryHandler(handle_admin_remove_prompt, pattern="^admin_remove_prompt$"))
    application.add_handler(CallbackQueryHandler(handle_admin_blacklist, pattern="^admin_blacklist$"))
    application.add_handler(CallbackQueryHandler(handle_admin_give_money, pattern="^admin_give_money$"))
    application.add_handler(CallbackQueryHandler(handle_admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(handle_admin_broadcast, pattern="^admin_broadcast$"))
    application.add_handler(CallbackQueryHandler(handle_start_mining, pattern="^start_mining$"))
    application.add_handler(CallbackQueryHandler(handle_profile, pattern="^profile$"))
    application.add_handler(CallbackQueryHandler(handle_shop, pattern="^shop$"))
    application.add_handler(CallbackQueryHandler(handle_shop_mines, pattern="^shop_mines$"))
    application.add_handler(CallbackQueryHandler(handle_buy_mine, pattern="^buy_mine_"))
    application.add_handler(CallbackQueryHandler(handle_shop_mine_upgrades, pattern="^shop_mine_upgrades$"))
    application.add_handler(CallbackQueryHandler(handle_upgrade_mine, pattern="^upgrade_mine_"))
    application.add_handler(CallbackQueryHandler(handle_shop_pickaxe_upgrade, pattern="^shop_pickaxe_upgrade$"))
    application.add_handler(CallbackQueryHandler(handle_upgrade_pickaxe, pattern="^upgrade_pickaxe$"))
    application.add_handler(CallbackQueryHandler(handle_support, pattern="^support$"))
    application.add_handler(CallbackQueryHandler(handle_commands, pattern="^commands$"))
    
    # Message Handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    logger.info("Bot started. Income will be calculated on user interaction.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
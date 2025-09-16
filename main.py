import os
import logging
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

logging.basicConfig(level=logging.INFO)

# ====== Config ======
BOT_TOKEN = os.getenv("TOKEN")
OWNER = os.getenv("OWNER", "")       # admin username (without @)
GROUP = os.getenv("GROUP", "")       # group username (without @)
CHANNEL = os.getenv("CHANNEL", "")   # channel username (without @)
RENDER_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN or not RENDER_HOSTNAME:
    logging.error("TOKEN yoki RENDER_EXTERNAL_HOSTNAME muhit o'zgaruvchilari belgilanmagan.")
    raise SystemExit("TOKEN va RENDER_EXTERNAL_HOSTNAME muhim!")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{RENDER_HOSTNAME}{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ====== Bot state (in-memory) ======
waiting = []            # queue of user ids waiting for partner
active = {}             # user_id -> partner_id (both directions)
profiles = {}           # user_id -> {"username": str}

# Buttons / texts
LIKE = "👍 Yoqtiraman"
DISLIKE = "👎 Yoqtirmayman"

TXT_START = "👋 Salom! Anonim chatga xush kelibsiz.\nYangi suhbat uchun «Yangi suhbat» tugmasini bosing."
TXT_NO_USERNAME = "❌ Iltimos, Telegram username o‘rnating (Settings → Username)."
TXT_NOT_SUBSCRIBED = "📢 Botdan foydalanish uchun kanal va guruhga obuna bo‘ling."
TXT_WAITING = "⌛ Suhbatdosh qidirilmoqda..."
TXT_CONNECTED = "✅ Suhbat boshlandi! Xabar yuboring. (Like/Dislike tugmalaridan foydalaning.)"
TXT_NOT_IN_CHAT = "⚠️ Siz hozircha suhbatda emassiz. Yangi suhbat uchun tugmani bosing."
TXT_STOPPED = "🛑 Suhbat tugatildi."
TXT_MATCH = lambda a, b: f"💖 Match! @{a} ❤️ @{b}"

# Helper: check subscription (user must be member/admin/creator)
async def is_subscribed(user_id: int) -> bool:
    try:
        # bot.get_chat_member can raise if bot is not admin or chat not found
        ch = await bot.get_chat_member(f"@{CHANNEL}", user_id)
        if ch.status in ("left", "kicked"):
            return False
        gr = await bot.get_chat_member(f"@{GROUP}", user_id)
        if gr.status in ("left", "kicked"):
            return False
        return True
    except Exception as e:
        logging.warning(f"Subscription check failed for {user_id}: {e}")
        return False

# Start handler
@dp.message(Command(commands=["start"]))
async def cmd_start(message: Message):
    uid = message.from_user.id
    username = message.from_user.username
    if not username:
        await message.answer(TXT_NO_USERNAME)
        return
    # check subscription
    if not await is_subscribed(uid):
        kb = [
            [{"text": f"📣 Kanal: @{CHANNEL}", "url": f"https://t.me/{CHANNEL}"}],
            [{"text": f"👥 Guruh: @{GROUP}", "url": f"https://t.me/{GROUP}"}],
            [{"text": "✅ Men obunaman (Tekshirish)", "callback_data": "check_sub"}]
        ]
        # build simple inline keyboard
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📣 Kanal: @{CHANNEL}", url=f"https://t.me/{CHANNEL}")],
            [InlineKeyboardButton(text=f"👥 Guruh: @{GROUP}", url=f"https://t.me/{GROUP}")],
            [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")]
        ])
        await message.answer(TXT_NOT_SUBSCRIBED, reply_markup=markup)
        return

    # save profile
    profiles[uid] = {"username": username}
    # show main inline menu (Yangi suhbat)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Yangi suhbat", callback_data="new_chat")],
        [InlineKeyboardButton(text=f"🔵 Admin: @{OWNER}", url=f"https://t.me/{OWNER}")]
    ])
    await message.answer(TXT_START, reply_markup=markup)

# Check subscription callback
@dp.callback_query(lambda c: c.data == "check_sub")
async def cb_check_sub(call: CallbackQuery):
    uid = call.from_user.id
    ok = await is_subscribed(uid)
    if ok:
        # save username if not exist
        if uid not in profiles:
            profiles[uid] = {"username": call.from_user.username or f"user{uid}"}
        await call.message.edit_text("✅ Obuna tekshirildi. /start bilan qayta boshlang.")
    else:
        await call.answer("❌ Hali ham kanal yoki guruhga qo‘shilmadingiz!", show_alert=True)

# New chat callback
@dp.callback_query(lambda c: c.data == "new_chat")
async def cb_new_chat(call: CallbackQuery):
    uid = call.from_user.id
    if uid not in profiles:
        # ensure username saved
        if not call.from_user.username:
            await call.message.answer(TXT_NO_USERNAME)
            return
        profiles[uid] = {"username": call.from_user.username}
    # ensure subscribed
    if not await is_subscribed(uid):
        await call.message.answer(TXT_NOT_SUBSCRIBED)
        return

    # if user already active
    if uid in active:
        await call.message.answer("⚠️ Siz allaqachon suhbatdasiz.")
        return

    # if user already waiting, inform
    if uid in waiting:
        await call.message.answer(TXT_WAITING)
        return

    # try match with first waiting (FIFO)
    partner = None
    while waiting:
        cand = waiting.pop(0)
        # skip if candidate became active or same user
        if cand == uid or cand in active:
            continue
        partner = cand
        break

    if partner:
        # create active links both ways
        active[uid] = partner
        active[partner] = uid
        # ensure both profiles exist
        if partner not in profiles:
            # try to fetch username
            try:
                chat = await bot.get_chat(partner)
                profiles[partner] = {"username": chat.username or f"user{partner}"}
            except:
                profiles[partner] = {"username": f"user{partner}"}
        if uid not in profiles:
            profiles[uid] = {"username": call.from_user.username or f"user{uid}"}

        # send connected messages with like/dislike keyboard
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        kb.add(KeyboardButton(LIKE), KeyboardButton(DISLIKE))

        await bot.send_message(uid, TXT_CONNECTED, reply_markup=kb)
        await bot.send_message(partner, TXT_CONNECTED, reply_markup=kb)
    else:
        # put user in waiting queue
        waiting.append(uid)
        await call.message.answer(TXT_WAITING)

# Stop command
@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    uid = message.from_user.id
    if uid in active:
        partner = active.get(uid)
        # notify partner
        try:
            await bot.send_message(partner, TXT_STOPPED, reply_markup=None)
        except:
            pass
        # clean both
        active.pop(partner, None)
        active.pop(uid, None)
    # remove from waiting if present
    if uid in waiting:
        try:
            waiting.remove(uid)
        except ValueError:
            pass
    await message.answer("Suhbat tugatildi.", reply_markup=None)

# Like/Dislike message handler
@dp.message()
async def message_handler(message: Message):
    uid = message.from_user.id

    # handle only when in active chat
    if uid not in active:
        # ignore commands handled elsewhere
        return

    partner = active.get(uid)
    if not partner:
        return

    text = message.text or ""
    # LIKE handling
    if text == LIKE:
        # mark like
        # store likes in a dict inside active? Use separate mapping:
        # we'll use profiles[uid]["liked"]=True
        profiles.setdefault(uid, {})["liked"] = True
        # check partner liked?
        if profiles.get(partner, {}).get("liked"):
            # both liked -> reveal usernames to each other
            u1 = profiles.get(uid, {}).get("username", f"user{uid}")
            u2 = profiles.get(partner, {}).get("username", f"user{partner}")
            await bot.send_message(uid, TXT_STOPPED)  # remove chat UX
            await bot.send_message(partner, TXT_STOPPED)
            await bot.send_message(uid, f"💖 Match! @{u1} ❤️ @{u2}")
            await bot.send_message(partner, f"💖 Match! @{u1} ❤️ @{u2}")
            # cleanup
            active.pop(uid, None)
            active.pop(partner, None)
            # clear liked flags
            profiles.get(uid, {}).pop("liked", None)
            profiles.get(partner, {}).pop("liked", None)
        else:
            await bot.send_message(uid, "✅ Siz like bildirdingiz. Agar partner ham like qilsa — username chiqadi.")
        return

    if text == DISLIKE:
        try:
            await bot.send_message(partner, "❌ Sizni partner rad etdi.", reply_markup=None)
        except:
            pass
        # cleanup
        active.pop(partner, None)
        active.pop(uid, None)
        profiles.get(uid, {}).pop("liked", None)
        profiles.get(partner, {}).pop("liked", None)
        await bot.send_message(uid, "✅ Suhbat tugatildi.", reply_markup=None)
        return

    # else: forward media/text to partner
    try:
        ct = message.content_type
        if ct == ContentType.TEXT:
            await bot.send_message(partner, message.text)
        elif ct == ContentType.STICKER:
            await bot.send_sticker(partner, message.sticker.file_id)
        elif ct == ContentType.PHOTO:
            file_id = message.photo[-1].file_id
            await bot.send_photo(partner, file_id, caption=message.caption or "")
        elif ct == ContentType.VIDEO:
            await bot.send_video(partner, message.video.file_id, caption=message.caption or "")
        elif ct == ContentType.AUDIO:
            await bot.send_audio(partner, message.audio.file_id, caption=message.caption or "")
        elif ct == ContentType.VOICE:
            await bot.send_voice(partner, message.voice.file_id)
        else:
            # fallback: text representation
            await bot.send_message(partner, message.text or "📨 (file)")
    except Exception as e:
        logging.exception(f"Forward failed: {e}")
        await bot.send_message(uid, "⚠️ Xabar yuborishda xatolik yuz berdi.")

# Webhook setup for Render (aiohttp)
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")

async def on_shutdown():
    await bot.delete_webhook()
    await bot.session.close()
    logging.info("Shutting down")

def build_app():
    app = web.Application()
    # register aiogram webhook handler
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(lambda _: on_startup())
    app.on_shutdown.append(lambda _: on_shutdown())
    # simple healthcheck
    async def root(request):
        return web.Response(text="Bot ishlayapti 🚀")
    app.router.add_get("/", root)
    return app

if __name__ == "__main__":
    app = build_app()
    web.run_app(app, host="0.0.0.0", port=PORT)

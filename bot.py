import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread
from dotenv import load_dotenv
load_dotenv()

# --- RENDER KEEP-ALIVE SERVER ---
app = Flask('')
@app.route('/')
def home(): return "Bot is running and healthy!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web).start()

# --- CONFIGURATION (Environment Variables) ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME')

bot = telebot.TeleBot(BOT_TOKEN)
WORK_CHANNEL = -1003877478828
client = MongoClient(MONGO_URI)
db = client['sub_management']
channels_col = db['channels']
users_col = db['users']

# --- ADMIN LOGIC ---

@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = message.from_user.id
    text = message.text.split()

    # User entry via Deep Link
    if len(text) > 1:
        try:
            ch_id = int(text[1])
            ch_data = channels_col.find_one({"channel_id": ch_id})
            if ch_data:
                markup = InlineKeyboardMarkup()
                # Display Dynamic Plans
                for p_time, p_price in ch_data['plans'].items():
                    label = f"{p_time} Pics"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{p_price}", callback_data=f"select_{ch_id}_{p_time}"))
                
                markup.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
                bot.send_message(message.chat.id, 
                    f"Welcome!\n\nYou are joining: *{ch_data['name']}*.\n\nPlease select a subscription plan below:", 
                    reply_markup=markup, parse_mode="Markdown")
                return
        except: pass

    # Admin Panel Greeting
    if user_id == ADMIN_ID:
        bot.send_message(message.chat.id, "✅ Admin Panel Active!\n\n/add - Add/Edit Channel & Prices\n/channels - Manage Existing Channels")
    else:
        bot.send_message(message.chat.id, "Welcome! To join a channel, please use the link provided by the Admin.")

@bot.message_handler(commands=['channels'], func=lambda m: m.from_user.id == ADMIN_ID)
def list_channels(message):
    markup = InlineKeyboardMarkup()
    # Fetch all channels managed by this admin
    cursor = channels_col.find({"admin_id": ADMIN_ID})
    count = 0
    for ch in cursor:
        markup.add(InlineKeyboardButton(f"Channel: {ch['name']}", callback_data=f"manage_{ch['channel_id']}"))
        count += 1
    
    markup.add(InlineKeyboardButton("➕ Add New Channel", callback_data="add_new"))
    
    if count == 0:
        bot.send_message(ADMIN_ID, "No channels found. Click below to add one.", reply_markup=markup)
    else:
        bot.send_message(ADMIN_ID, "Your Managed Channels:", reply_markup=markup)

@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def add_channel_start(message):
    msg = bot.send_message(ADMIN_ID, "Please ensure the bot is an Admin in your channel, then FORWARD any message from that channel here.")
    bot.register_next_step_handler(msg, get_plans)

# Callback for Add New button
@bot.callback_query_handler(func=lambda call: call.data == "add_new")
def cb_add_new(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "Please FORWARD any message from your channel here.")
    bot.register_next_step_handler(msg, get_plans)

def get_plans(message):
    if message.forward_from_chat:
        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title
        msg = bot.send_message(ADMIN_ID, 
            f"Channel Detected: *{ch_name}*\n\nEnter plans in format (Pics:Price)Example:2:99, 4:199, 6:299, 6:299:Example:2:99, 4:199, 6:299, 6:299:\n`Min:Price, Min:Price` \n\n"
            "Example:\n`1440:99, 43200:199` (1 Day and 30 Days)", parse_mode="Markdown")
        bot.register_next_step_handler(msg, finalize_channel, ch_id, ch_name)
    else:
        bot.send_message(ADMIN_ID, "❌ Error: Message was not forwarded. Use /add to try again.")

def finalize_channel(message, ch_id, ch_name):
    try:
        raw_plans = [p.strip() for p in message.text.replace('\n','').replace('\r','').split(',') if ':' in p]
        plans_dict = {}
        for p in raw_plans:
            t, pr = [x.strip() for x in p.split(':')]
            plans_dict[t] = pr
        
        channels_col.update_one({"channel_id": ch_id}, {"$set": {"name": ch_name, "plans": plans_dict, "admin_id": ADMIN_ID}}, upsert=True)
        bot_username = bot.get_me().username
        bot.send_message(ADMIN_ID, f"✅ Setup Successful!\n\nInvite Link for users:\n`https://t.me/{bot_username}?start={ch_id}`", parse_mode="Markdown")
    except:
        bot.send_message(ADMIN_ID, "❌ Invalid format. Please use `Min:Price, Min:Price`. Use /add to retry.")

# --- USER: PAYMENT FLOW ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def user_pays(call):
    _, ch_id, mins = call.data.split('_')
    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    price = ch_data['plans'][mins]
    
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=upi://pay?pa={UPI_ID}&am={price}&cu=INR"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{ch_id}_{mins}"))
    markup.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
    
    bot.send_photo(call.message.chat.id, qr_url, 
                   caption=f"Plan: {mins} Pics\nPrice: ₹{price}\nUPI ID: `{UPI_ID}`\n\nPlease complete the payment and click 'I Have Paid'.", 
                   reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def admin_notify(call):
    _, ch_id, mins = call.data.split('_')
    user = call.from_user
    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    price = ch_data['plans'][mins]
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{ch_id}_{mins}"))
    markup.add(InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}"))
    
    bot.send_message(ADMIN_ID, f"🔔 *Payment Verification Required!*\n\nUser: {user.first_name}\nChannel: {ch_data['name']}\nPlan: {mins} Pics\nPrice: ₹{price}", 
                     reply_markup=markup, parse_mode="Markdown")
    
    u_markup = InlineKeyboardMarkup().add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
    bot.send_message(call.message.chat.id, "✅ Your payment request has been sent. Please wait for Admin approval.", reply_markup=u_markup)

# --- APPROVAL & EXPIRY ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def approve_now(call):
    _, u_id, ch_id, mins = call.data.split('_')
    u_id, ch_id, mins = int(u_id), int(ch_id), int(mins)
    
    try:
        expiry_datetime = datetime.now() + timedelta(minutes=mins)
        expiry_ts = int(expiry_datetime.timestamp())

        # Link expires when sub ends
        link = bot.create_chat_invite_link(WORK_CHANNEL, member_limit=1)
        bot.send_message(WORK_CHANNEL, f"📥 New User Joined!\n\n👤 ID: {u_id}\n🎯 Plan: {mins} Pics\n\n📸 Upload your photo here 👇")
        
        users_col.update_one({"user_id": u_id, "channel_id": ch_id}, {"$set": {
    "expiry": expiry_datetime.timestamp(),
    "pics_left": mins
}}, upsert=True)
        
        bot.send_message(u_id, f"""
✅ Payment Approved!

👉 Join here:
{link.invite_link}

📸 Upload your photo in the channel 👇  
🎯 Plan: {mins} Pics  

⚡ One photo = one credit  
⏳ Processing time ~1 hour  

🔥 Send your pic now!
""")
        bot.edit_message_text(f"✅ Approved user {u_id} for {mins} pics.", call.message.chat.id, call.message.message_id)
        
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_'))
def manage_ch(call):
    ch_id = int(call.data.split('_')[1])
    ch_data = channels_col.find_one({"channel_id": ch_id})
    bot_username = bot.get_me().username
    link = f"https://t.me/{bot_username}?start={ch_id}"
    
    bot.edit_message_text(f"Settings for: *{ch_data['name']}*\n\nYour Link: `{link}`\n\nTo edit prices, use /add and forward a message from this channel again.", 
                          call.message.chat.id, call.message.message_id, parse_mode="Markdown")

# Automate Kicking
def kick_expired_users():
    
    now = datetime.now().timestamp()
    expired_users = users_col.find({"expiry": {"$lte": now}})
    bot_username = bot.get_me().username
    

    for user in expired_users:
        try:
            bot.ban_chat_member(user['channel_id'], user['user_id'])
            bot.unban_chat_member(user['channel_id'], user['user_id'])
            
            rejoin_url = f"https://t.me/{bot_username}?start={user['channel_id']}"
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Re-join / Renew", url=rejoin_url))
            
            bot.send_message(user['user_id'], "⚠️ Your subscription has expired.\n\nTo join again or renew, please click the button below:", reply_markup=markup)
            users_col.delete_one({"_id": user['_id']})
        except: pass
@bot.callback_query_handler(func=lambda call: call.data.startswith("sendto_"))
def select_user(call):
    uid = int(call.data.split("_")[1])

@bot.callback_query_handler(func=lambda call: call.data.startswith("sendto_"))
def select_user(call):
    uid = int(call.data.split("_")[1])

    bot.clear_step_handler_by_chat_id(ADMIN_ID)
    msg = bot.send_message(ADMIN_ID, f"Send photo for user {uid}")
    bot.register_next_step_handler(msg, send_photo_to_user, uid)
        

@bot.message_handler(commands=['panel'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return

    users = users_col.find()

    markup = InlineKeyboardMarkup()
    for u in users:
        uid = u['user_id']
        markup.add(InlineKeyboardButton(f"👤 {uid} | {u.get('pics_left',0)} left", callback_data=f"sendto_{uid}"))

    bot.send_message(ADMIN_ID, "📊 Select user to send result:", reply_markup=markup)
    

@bot.message_handler(commands=['send'])
def send_result(message):
    if message.from_user.id != ADMIN_ID:
        return

    msg = bot.send_message(ADMIN_ID, "Enter user ID")
    bot.register_next_step_handler(msg, get_uid)

def get_uid(message):
    uid = int(message.text) if message.text.isdigit() else None
    msg = bot.send_message(ADMIN_ID, "Send edited photo")
    if uid is None: return bot.send_message(ADMIN_ID, "❌ Invalid User ID")
    bot.register_next_step_handler(msg, send_photo_to_user, uid)

def send_photo_to_user(message, uid):
    if message.photo:
        file_id = message.photo[-1].file_id

        bot.send_photo(uid, file_id)

        WORK_CHANNEL = -1003877478828
        bot.send_photo(WORK_CHANNEL, file_id)

        bot.send_message(ADMIN_ID, "✅ Sent to user + channel")

@bot.message_handler(content_types=['photo'])
        
def handle_photo(message):
    if message.chat.type in ["supergroup", "group"]:
        user_id = message.from_user.id

        user = users_col.find_one({"user_id": user_id})
        if not user:
            return

        if user.get("pics_left", 0) <= 0:
            bot.send_message(user_id, "❌ Plan finished!")
            return

        users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"pics_left": -1}}
        )

        bot.send_message(ADMIN_ID, f"📸 New request from user {user_id}")
        bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)

        bot.send_message(user_id, "⏳ Processing (~1 hour)")

        updated = users_col.find_one({"user_id": user_id})

        if updated["pics_left"] <= 0:
            try:
                bot.ban_chat_member(message.chat.id, user_id)
                bot.unban_chat_member(message.chat.id, user_id)

                bot.send_message(user_id, "⚠️ Plan completed! Buy again.")
            except:
                pass
if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_expired_users, 'interval', minutes=1)
    scheduler.start()
    bot.remove_webhook()
    print("Bot is running...")
    
    bot.infinity_polling(timeout=20, long_polling_timeout=10)

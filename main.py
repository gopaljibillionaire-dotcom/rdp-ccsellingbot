import asyncio
import os
import sys
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

import aiohttp
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import config

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("OneWayStore")

# Check essential env vars
if not config.BOT_TOKEN:
    logger.critical("BOT_TOKEN is missing! Set it in environment variables.")
    sys.exit(1)

# -------------------------------------------------------------------
# Database Initialization (Motor AsyncIO)
# -------------------------------------------------------------------
mongo_client = AsyncIOMotorClient(config.MONGO_URI)
db = mongo_client["onewaystore_db"]

users_col = db["users"]
products_col = db["products"]
orders_col = db["orders"]
transactions_col = db["transactions"]

# -------------------------------------------------------------------
# Bot & Dispatcher Setup
# -------------------------------------------------------------------
bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# -------------------------------------------------------------------
# FSM States
# -------------------------------------------------------------------
class AdminStates(StatesGroup):
    waiting_for_product_name = State()
    waiting_for_product_category = State()
    waiting_for_product_price = State()
    waiting_for_product_stock = State()

class DepositStates(StatesGroup):
    waiting_for_amount = State()

# -------------------------------------------------------------------
# Helper Keyboards matching your Layout
# -------------------------------------------------------------------
def get_custom_emoji_btn(text: str, callback_data: str, emoji_key: str, style: str = "primary") -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        custom_emoji_id=config.EMOJI.get(emoji_key),
        style=style
    )

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🛒 Store", callback_data="shop", style="primary")
        ],
        [
            InlineKeyboardButton(text="🛍️ My Purchases", callback_data="my_orders", style="primary"),
            InlineKeyboardButton(text="🟠 Wallet", callback_data="wallet", style="primary"),
        ],
        [
            InlineKeyboardButton(text="🎁 Refer & Earn", callback_data="referral", style="primary"),
            InlineKeyboardButton(text="👤 Profile", callback_data="profile", style="primary"),
        ],
        [
            InlineKeyboardButton(text="💬 Support", callback_data="support", style="primary"),
            InlineKeyboardButton(text="💻 Developer", callback_data="developer", style="primary"),
        ],
        [
            InlineKeyboardButton(text="💀 Join our Channel", url=getattr(config, "CHANNEL_URL", "https://t.me/OneWayStoreChannel"))
        ]
    ]
    if user_id in config.ADMIN_IDS:
        buttons.append([
            InlineKeyboardButton(text="⚡ Admin Control Panel", callback_data="admin_panel", style="danger")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# -------------------------------------------------------------------
# Database Helper Operations
# -------------------------------------------------------------------
async def get_or_create_user(user_id: int, username: Optional[str], full_name: str) -> dict:
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "balance": 0.0,
            "referred_by": None,
            "created_at": datetime.utcnow()
        }
        await users_col.insert_one(user)
    else:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"username": username, "full_name": full_name}}
        )
    return user

# -------------------------------------------------------------------
# User Handlers & Welcome Screen
# -------------------------------------------------------------------
WELCOME_BANNER_URL = getattr(config, "WELCOME_BANNER_URL", "https://i.ibb.co/6y4G82h/welcome.jpg")

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    await get_or_create_user(user_id, username, full_name)
    
    caption = (
        f"👋 Hii @{username if username else full_name}, Welcome to <b>One Way Store</b>\n\n"
        f"<blockquote>Your one stop solution for AI & OTT Subscriptions 💀</blockquote>\n\n"
        f"Use the buttons below to navigate 👇"
    )
    
    try:
        await message.answer_photo(
            photo=WELCOME_BANNER_URL,
            caption=caption,
            reply_markup=main_menu_keyboard(user_id)
        )
    except Exception:
        await message.answer(caption, reply_markup=main_menu_keyboard(user_id))

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    username = callback.from_user.username
    full_name = callback.from_user.full_name
    
    caption = (
        f"👋 Hii @{username if username else full_name}, Welcome to <b>One Way Store</b>\n\n"
        f"<blockquote>Your one stop solution for AI & OTT Subscriptions 💀</blockquote>\n\n"
        f"Use the buttons below to navigate 👇"
    )
    
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=WELCOME_BANNER_URL, caption=caption),
            reply_markup=main_menu_keyboard(user_id)
        )
    except Exception:
        await callback.message.edit_text(caption, reply_markup=main_menu_keyboard(user_id))
    await callback.answer()

@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    user = await get_or_create_user(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name
    )
    purchases_count = await orders_col.count_documents({"user_id": callback.from_user.id})
    
    text = (
        f"<b>👤 User Profile</b>\n\n"
        f"<b>🆔 ID:</b> <code>{user['user_id']}</code>\n"
        f"<b>📛 Name:</b> {user['full_name']}\n"
        f"<b>🌐 Username:</b> @{user['username'] if user['username'] else 'None'}\n"
        f"<b>💰 Balance:</b> <code>${user.get('balance', 0.0):.2f}</code>\n"
        f"<b>📦 Total Purchases:</b> <code>{purchases_count}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟠 Add Funds / Wallet", callback_data="wallet", style="success")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "wallet")
async def cb_wallet(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    text = (
        f"<b>🟠 My Wallet</b>\n\n"
        f"Current Balance: <code>${user.get('balance', 0.0):.2f}</code>\n\n"
        f"Deposit funds instantly via cryptocurrency (OxaPay auto-verification)."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Deposit Funds", callback_data="deposit", style="success")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"
    text = (
        f"<b>🎁 Refer & Earn Program</b>\n\n"
        f"Invite your friends and earn rewards when they top up their wallet!\n\n"
        f"Your Referral Link:\n<code>{ref_link}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    text = (
        f"<b>💬 Customer Support</b>\n\n"
        f"Facing issues with activation or deposits?\n"
        f"Contact our support team: <b>@OneWayStoreSupport</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "developer")
async def cb_developer(callback: CallbackQuery):
    text = (
        f"<b>💻 Developer Info</b>\n\n"
        f"Bot designed & built for <b>One Way Store</b>.\n"
        f"Powered by Python, Aiogram & MongoDB."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# -------------------------------------------------------------------
# Store & Shopping Catalog
# -------------------------------------------------------------------
@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery):
    categories = await products_col.distinct("category")
    if not categories:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")]
        ])
        await callback.message.edit_text("<b>🛒 Store Catalogue</b>\n\nNo products available right now. Check back soon!", reply_markup=kb)
        await callback.answer()
        return

    buttons = []
    for cat in categories:
        buttons.append([
            InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"cat_{cat}", style="primary")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")])

    text = (
        "<b>🛒 One Way Store Product Catalogue</b>\n\n"
        "✨ Instant Delivery\n"
        "⚡ Fast & Secure\n"
        "🤖 Auto Payment Verification\n\n"
        "<b>Select a category below 👇</b>"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("cat_"))
async def cb_category(callback: CallbackQuery):
    category = callback.data.split("cat_")[1]
    products = await products_col.find({"category": category}).to_list(length=100)
    
    if not products:
        await callback.answer("No products found in this category.", show_alert=True)
        return

    buttons = []
    for p in products:
        stock_count = len(p.get("stock", []))
        btn_text = f"📦 {p['name']} - ${p['price']:.2f} ({stock_count} in stock)"
        buttons.append([
            InlineKeyboardButton(text=btn_text, callback_data=f"prod_{str(p['_id'])}", style="primary")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Back to Store", callback_data="shop", style="danger")])

    await callback.message.edit_text(f"<b>📁 Category: {category}</b>\nChoose an item below:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("prod_"))
async def cb_product_view(callback: CallbackQuery):
    from bson.objectid import ObjectId
    prod_id = callback.data.split("prod_")[1]
    
    try:
        product = await products_col.find_one({"_id": ObjectId(prod_id)})
    except Exception:
        product = None

    if not product:
        await callback.answer("Product no longer exists.", show_alert=True)
        return

    stock_count = len(product.get("stock", []))
    text = (
        f"<b>🛒 {product['name']}</b>\n\n"
        f"📁 <b>Category:</b> {product['category']}\n"
        f"💵 <b>Price:</b> <code>${product['price']:.2f}</code>\n"
        f"📦 <b>Available Stock:</b> <code>{stock_count}</code>\n\n"
        f"🔥 <i>Stock is limited — grab yours before it's gone!</i> 🔥"
    )

    buttons = []
    if stock_count > 0:
        buttons.append([
            InlineKeyboardButton(text=f"🛒 Buy Now (${product['price']:.2f})", callback_data=f"buy_{str(product['_id'])}", style="success")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"cat_{product['category']}", style="danger")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("buy_"))
async def cb_buy_product(callback: CallbackQuery):
    from bson.objectid import ObjectId
    prod_id = callback.data.split("buy_")[1]
    user_id = callback.from_user.id

    try:
        product = await products_col.find_one({"_id": ObjectId(prod_id)})
    except Exception:
        product = None

    if not product:
        await callback.answer("Product not found.", show_alert=True)
        return

    user = await users_col.find_one({"user_id": user_id})
    if not user or user.get("balance", 0.0) < product["price"]:
        await callback.answer("❌ Insufficient balance! Please deposit funds in your wallet first.", show_alert=True)
        return

    stock = product.get("stock", [])
    if not stock:
        await callback.answer("❌ Sorry, this item is out of stock!", show_alert=True)
        return

    item_content = stock.pop(0)

    await products_col.update_one(
        {"_id": product["_id"]},
        {"$set": {"stock": stock}}
    )
    await users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": -product["price"]}}
    )

    order = {
        "user_id": user_id,
        "product_name": product["name"],
        "category": product["category"],
        "price": product["price"],
        "content": item_content,
        "created_at": datetime.utcnow()
    }
    await orders_col.insert_one(order)

    success_text = (
        f"<b>✅ Purchase Successful!</b>\n\n"
        f"<b>Item:</b> {product['name']}\n"
        f"<b>Price Paid:</b> ${product['price']:.2f}\n\n"
        f"<b>Your Content / Account Details:</b>\n"
        f"<code>{item_content}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Return to Store", callback_data="shop", style="primary")]
    ])
    await callback.message.edit_text(success_text, reply_markup=kb)
    await callback.answer("Purchase complete!")

@router.callback_query(F.data == "my_orders")
async def cb_my_orders(callback: CallbackQuery):
    user_id = callback.from_user.id
    orders = await orders_col.find({"user_id": user_id}).sort("created_at", -1).to_list(length=10)

    if not orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")]
        ])
        await callback.message.edit_text("<b>🛍️ You have no order history yet.</b>", reply_markup=kb)
        await callback.answer()
        return

    text = "<b>🛍️ Your Recent Purchases:</b>\n\n"
    for idx, order in enumerate(orders, 1):
        date_str = order.get("created_at", datetime.utcnow()).strftime("%Y-%m-%d %H:%M")
        text += (
            f"<b>{idx}. {order['product_name']}</b> - ${order['price']:.2f}\n"
            f"📅 Date: {date_str}\n"
            f"🔑 Content: <code>{order['content']}</code>\n"
            f"----------------------------------------\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# -------------------------------------------------------------------
# OxaPay Crypto Deposit & Auto-Verification Flow with Check Payment
# -------------------------------------------------------------------
@router.callback_query(F.data == "deposit")
async def cb_deposit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.waiting_for_amount)
    text = (
        f"<b>💳 Deposit Funds via OxaPay</b>\n\n"
        f"Please enter the amount in USD you want to deposit (e.g. <code>10</code> or <code>25.50</code>):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="wallet", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.message(DepositStates.waiting_for_amount)
async def process_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError()
    except ValueError:
        await message.answer("Please enter a valid positive numerical amount (e.g., 10 or 25.50).")
        return

    await state.clear()
    
    if not config.OXAPAY_MERCHANT_API_KEY:
        await message.answer("⚠️ Deposit gateway is not configured (Missing OxaPay API Key).")
        return

    payload = {
        "merchant": config.OXAPAY_MERCHANT_API_KEY,
        "amount": amount,
        "currency": "USD",
        "lifeTime": 30,
        "feePaidByBuyer": 0,
        "callbackUrl": config.OXAPAY_CALLBACK_URL,
        "returnUrl": config.OXAPAY_RETURN_URL,
        "description": f"Deposit for Telegram User {message.from_user.id}"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post("https://api.oxapay.com/merchants/request", json=payload) as resp:
                result = await resp.json()
        except Exception as e:
            logger.error(f"Error connecting to OxaPay: {e}")
            await message.answer("Failed to communicate with payment gateway. Try again later.")
            return

    if result.get("result") == 100 and "payLink" in result:
        pay_url = result["payLink"]
        track_id = result.get("trackId")

        await transactions_col.insert_one({
            "track_id": track_id,
            "user_id": message.from_user.id,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.utcnow()
        })

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Pay Now", url=pay_url)],
            [InlineKeyboardButton(text="🔄 Check Payment", callback_data=f"check_pay_{track_id}", style="success")],
            [InlineKeyboardButton(text="🔙 Back to Wallet", callback_data="wallet", style="danger")]
        ])
        await message.answer(
            f"<b>📄 Payment Invoice Created!</b>\n\n"
            f"<b>Amount:</b> ${amount:.2f}\n"
            f"<b>Track ID:</b> <code>{track_id}</code>\n\n"
            f"1. Click <b>Pay Now</b> to complete payment.\n"
            f"2. Once paid, click <b>Check Payment</b> below to verify instantly!",
            reply_markup=kb
        )
    else:
        err_msg = result.get("message", "Unknown error")
        await message.answer(f"Failed to generate invoice: {err_msg}")

@router.callback_query(F.data.startswith("check_pay_"))
async def cb_check_payment(callback: CallbackQuery):
    track_id = callback.data.split("check_pay_")[1]
    
    tx = await transactions_col.find_one({"track_id": track_id})
    if not tx:
        await callback.answer("Transaction not found.", show_alert=True)
        return

    if tx.get("status") == "completed":
        await callback.answer("✅ Payment is already verified and credited!", show_alert=True)
        return

    # Verify transaction status via OxaPay Inquiry API or In-memory check
    payload = {
        "merchant": config.OXAPAY_MERCHANT_API_KEY,
        "trackId": track_id
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post("https://api.oxapay.com/merchants/inquiry", json=payload) as resp:
                res = await resp.json()
        except Exception as e:
            logger.error(f"OxaPay inquiry error: {e}")
            await callback.answer("Failed to check status with payment gateway.", show_alert=True)
            return

    status = res.get("status") # depending on oxapay inquiry response structure (e.g., 'Paid' or status code)
    # Alternatively check via status code / status string
    is_paid = (res.get("result") == 100 and str(res.get("status")).lower() in ["paid", "complete", "completed", "1"]) or (res.get("payStatus") == 2)

    if is_paid or res.get("status") == "Paid":
        await transactions_col.update_one(
            {"_id": tx["_id"]},
            {"$set": {"status": "completed", "completed_at": datetime.utcnow()}}
        )
        await users_col.update_one(
            {"user_id": tx["user_id"]},
            {"$inc": {"balance": float(tx["amount"])}}
        )
        await callback.message.edit_text(
            f"<b>✅ Payment Verified Successfully!</b>\n\nYour wallet has been credited with <b>${float(tx['amount']):.2f}</b>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Go to Store", callback_data="shop", style="success")]
            ])
        )
        await callback.answer("Payment confirmed!")
    else:
        await callback.answer("⏳ Payment not detected yet. Please complete the payment first.", show_alert=True)

# OxaPay Webhook Handler for automated callbacks
async def oxapay_callback_handler(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        if not data:
            data = await request.json()
    except Exception:
        return web.Response(text="Invalid body", status=400)

    track_id = data.get("trackId")
    status = data.get("status")

    if track_id and status in ["Paid", "paid", "Completed", "completed"]:
        tx = await transactions_col.find_one({"track_id": track_id})
        if tx and tx.get("status") != "completed":
            await transactions_col.update_one(
                {"_id": tx["_id"]},
                {"$set": {"status": "completed", "completed_at": datetime.utcnow()}}
            )
            await users_col.update_one(
                {"user_id": tx["user_id"]},
                {"$inc": {"balance": float(tx["amount"])}}
            )
            try:
                await bot.send_message(
                    chat_id=tx["user_id"],
                    text=f"<b>✅ Deposit Confirmed!</b>\n\nYour wallet has been credited with <b>${float(tx['amount']):.2f}</b>."
                )
            except Exception as e:
                logger.error(f"Failed to notify user {tx['user_id']}: {e}")

    return web.Response(text="ok", status=200)

# -------------------------------------------------------------------
# Admin Panel Handlers
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return

    text = "<b>⚡ Admin Control Panel</b>\nManage store products, stock, and view metrics."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Product", callback_data="admin_add_product", style="success")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_add_product")
async def cb_admin_add_product(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_product_name)
    await callback.message.edit_text("<b>Step 1/4:</b> Enter Product Name:")
    await callback.answer()

@router.message(AdminStates.waiting_for_product_name)
async def process_admin_name(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(AdminStates.waiting_for_product_category)
    await message.answer("<b>Step 2/4:</b> Enter Product Category (e.g., Canva Pro, Netflix, AI Tools):")

@router.message(AdminStates.waiting_for_product_category)
async def process_admin_category(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await state.update_data(category=message.text.strip())
    await state.set_state(AdminStates.waiting_for_product_price)
    await message.answer("<b>Step 3/4:</b> Enter Product Price in USD (e.g. 4.99):")

@router.message(AdminStates.waiting_for_product_price)
async def process_admin_price(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    try:
        price = float(message.text.strip())
        if price < 0:
            raise ValueError()
    except ValueError:
        await message.answer("Please enter a valid price (e.g. 4.99).")
        return

    await state.update_data(price=price)
    await state.set_state(AdminStates.waiting_for_product_stock)
    await message.answer("<b>Step 4/4:</b> Send stock items/accounts (one item per line):")

@router.message(AdminStates.waiting_for_product_stock)
async def process_admin_stock(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return

    stock_items = [line.strip() for line in message.text.split("\n") if line.strip()]
    data = await state.get_data()
    await state.clear()

    product_doc = {
        "name": data["name"],
        "category": data["category"],
        "price": data["price"],
        "stock": stock_items,
        "created_at": datetime.utcnow()
    }
    await products_col.insert_one(product_doc)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Admin Panel", callback_data="admin_panel", style="primary")]
    ])
    await message.answer(
        f"<b>✅ Product Added Successfully!</b>\n\n"
        f"<b>Name:</b> {data['name']}\n"
        f"<b>Category:</b> {data['category']}\n"
        f"<b>Price:</b> ${data['price']:.2f}\n"
        f"<b>Stock Added:</b> {len(stock_items)} items",
        reply_markup=kb
    )

# -------------------------------------------------------------------
# Startup & Webserver Setup
# -------------------------------------------------------------------
async def on_startup(app: web.Application):
    asyncio.create_task(dp.start_polling(bot))
    logger.info("Bot started and polling for updates...")

async def main():
    app = web.Application()
    app.router.add_post("/oxapay/callback", oxapay_callback_handler)
    app.on_startup.append(on_startup)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    logger.info(f"Starting web server on port {config.PORT}...")
    await site.start()

    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")

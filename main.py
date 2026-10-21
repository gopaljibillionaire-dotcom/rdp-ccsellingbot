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
categories_col = db["categories"]

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
    waiting_for_category_name = State()
    waiting_for_product_name = State()
    waiting_for_product_price = State()
    waiting_for_product_stock = State()
    waiting_for_broadcast_message = State()

class DepositStates(StatesGroup):
    waiting_for_amount = State()

# -------------------------------------------------------------------
# Helper Keyboards
# -------------------------------------------------------------------
def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🛒 Store", callback_data="shop")
        ],
        [
            InlineKeyboardButton(text="🛍️ My Purchases", callback_data="my_orders"),
            InlineKeyboardButton(text="🟠 Wallet", callback_data="wallet"),
        ],
        [
            InlineKeyboardButton(text="👤 Profile", callback_data="profile"),
            InlineKeyboardButton(text="💬 Support", callback_data="support"),
        ],
        [
            InlineKeyboardButton(text="💻 Developer", callback_data="developer"),
        ],
        [
            InlineKeyboardButton(text="💀 Join our Channel", url=getattr(config, "CHANNEL_URL", "https://t.me/OneWayStoreChannel"))
        ]
    ]
    if user_id in config.ADMIN_IDS:
        buttons.append([
            InlineKeyboardButton(text="⚡ Admin Control Panel", callback_data="admin_panel")
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
            "created_at": datetime.utcnow()
        }
        await users_col.insert_one(user)
    else:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"username": username, "full_name": full_name}}
        )
    return user

async def notify_admins(text: str):
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

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
    
    thunder = config.EMOJI.get("thunder", "")
    caption = (
        f"👋 Hii @{username if username else full_name}, Welcome to <b>One Way Store</b>\n\n"
        f"<blockquote>Your one stop solution for AI & OTT Subscriptions <tg-emoji emoji-id='{thunder}'>💀</tg-emoji></blockquote>\n\n"
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
    
    thunder = config.EMOJI.get("thunder", "")
    caption = (
        f"👋 Hii @{username if username else full_name}, Welcome to <b>One Way Store</b>\n\n"
        f"<blockquote>Your one stop solution for AI & OTT Subscriptions <tg-emoji emoji-id='{thunder}'>💀</tg-emoji></blockquote>\n\n"
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
        [InlineKeyboardButton(text="🟠 Add Funds / Wallet", callback_data="wallet")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
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
        [InlineKeyboardButton(text="💳 Deposit Funds", callback_data="deposit")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
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
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "developer")
async def cb_developer(callback: CallbackQuery):
    text = (
        f"<b>💻 Developer Info</b>\n\n"
        f"Bot designed & built for <b>One Way Store</b> by <b>@Gopalji369</b>.\n"
        f"Powered by Python, Aiogram & MongoDB."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# -------------------------------------------------------------------
# Store & Shopping Catalog
# -------------------------------------------------------------------
@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery):
    categories = await categories_col.distinct("name")
    if not categories:
        categories = await products_col.distinct("category")

    if not categories:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
        ])
        await callback.message.edit_text("<b>🛒 Store Catalogue</b>\n\nNo categories or products available right now. Check back soon!", reply_markup=kb)
        await callback.answer()
        return

    buttons = []
    for cat in categories:
        buttons.append([
            InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"cat_{cat}")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")])

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
            InlineKeyboardButton(text=btn_text, callback_data=f"prod_{str(p['_id'])}")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Back to Store", callback_data="shop")])

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
    fire_emoji = config.EMOJI.get("fire")

    text = (
        f"<b>🛒 {product['name']}</b>\n\n"
        f"📁 <b>Category:</b> {product['category']}\n"
        f"💵 <b>Price:</b> <code>${product['price']:.2f}</code>\n"
        f"📦 <b>Available Stock:</b> <code>{stock_count}</code>\n\n"
        f"<tg-emoji emoji-id='{fire_emoji}'>🔥</tg-emoji> <i>Stock is limited — grab yours before it's gone!</i>"
    )

    buttons = []
    if stock_count > 0:
        buttons.append([
            InlineKeyboardButton(text=f"🛒 Buy Now (${product['price']:.2f})", callback_data=f"buy_{str(product['_id'])}")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"cat_{product['category']}")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("buy_"))
async def cb_buy_product(callback: CallbackQuery):
    from bson.objectid import ObjectId
    prod_id = callback.data.split("buy_")[1]
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.full_name

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

    tick_emoji = config.EMOJI.get("tick", "")
    await notify_admins(
        f"🚨 <b>New Purchase Alert!</b>\n\n"
        f"👤 <b>User:</b> @{username} (<code>{user_id}</code>)\n"
        f"📦 <b>Product:</b> {product['name']}\n"
        f"📁 <b>Category:</b> {product['category']}\n"
        f"💵 <b>Paid:</b> ${product['price']:.2f}\n"
        f"<tg-emoji emoji-id='{tick_emoji}'>✅</tg-emoji> <i>Stock delivered automatically.</i>"
    )

    success_text = (
        f"<b>✅ Purchase Successful!</b>\n\n"
        f"<b>Item:</b> {product['name']}\n"
        f"<b>Price Paid:</b> ${product['price']:.2f}\n\n"
        f"<b>Your Content / Account Details:</b>\n"
        f"<code>{item_content}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Return to Store", callback_data="shop")]
    ])
    await callback.message.edit_text(success_text, reply_markup=kb)
    await callback.answer("Purchase complete!")

@router.callback_query(F.data == "my_orders")
async def cb_my_orders(callback: CallbackQuery):
    user_id = callback.from_user.id
    orders = await orders_col.find({"user_id": user_id}).sort("created_at", -1).to_list(length=10)

    if not orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
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
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# -------------------------------------------------------------------
# OxaPay Crypto Deposit & Auto-Verification Flow
# -------------------------------------------------------------------
@router.callback_query(F.data == "deposit")
async def cb_deposit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.waiting_for_amount)
    text = (
        f"<b>💳 Deposit Funds via OxaPay</b>\n\n"
        f"Please enter the amount in USD you want to deposit (e.g. <code>10</code> or <code>25.50</code>):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="wallet")]
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
            "username": message.from_user.username or message.from_user.full_name,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.utcnow()
        })

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Pay Now", url=pay_url)],
            [InlineKeyboardButton(text="🔄 Check Payment", callback_data=f"check_pay_{track_id}")],
            [InlineKeyboardButton(text="🔙 Back to Wallet", callback_data="wallet")]
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

        await notify_admins(
            f"🟠 <b>Wallet Topup Successful!</b>\n\n"
            f"👤 <b>User:</b> @{tx.get('username')} (<code>{tx['user_id']}</code>)\n"
            f"💵 <b>Amount Credited:</b> ${float(tx['amount']):.2f}"
        )

        await callback.message.edit_text(
            f"<b>✅ Payment Verified Successfully!</b>\n\nYour wallet has been credited with <b>${float(tx['amount']):.2f}</b>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Go to Store", callback_data="shop")]
            ])
        )
        await callback.answer("Payment confirmed!")
    else:
        await callback.answer("⏳ Payment not detected yet. Please complete the payment first.", show_alert=True)

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
            await notify_admins(
                f"🟠 <b>Wallet Topup Successful (Webhook)!</b>\n\n"
                f"👤 <b>User:</b> @{tx.get('username')} (<code>{tx['user_id']}</code>)\n"
                f"💵 <b>Amount Credited:</b> ${float(tx['amount']):.2f}"
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
# Admin Control Panel Handlers
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return

    text = "<b>⚡ Admin Control Panel</b>\nManage store categories, products, stock, broadcast, and database."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Add Category", callback_data="admin_add_category"),
         InlineKeyboardButton(text="➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton(text="📢 All User Broadcast", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="👥 See User Activity", callback_data="admin_user_activity")],
        [InlineKeyboardButton(text="🗑️ Delete Products", callback_data="admin_delete_products"),
         InlineKeyboardButton(text="⚠️ Delete Database", callback_data="admin_delete_db")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# --- Add Category Flow ---
@router.callback_query(F.data == "admin_add_category")
async def cb_admin_add_category(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_category_name)
    await callback.message.edit_text("<b>📁 Enter Category Name:</b>")
    await callback.answer()

@router.message(AdminStates.waiting_for_category_name)
async def process_admin_category_name(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    cat_name = message.text.strip()
    await state.clear()
    
    await categories_col.update_one(
        {"name": cat_name},
        {"$set": {"name": cat_name, "created_at": datetime.utcnow()}},
        upsert=True
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Admin Panel", callback_data="admin_panel")]
    ])
    await message.answer(f"<b>✅ Category '{cat_name}' added successfully!</b>", reply_markup=kb)

# --- Add Product Flow ---
@router.callback_query(F.data == "admin_add_product")
async def cb_admin_add_product(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return

    categories = await categories_col.distinct("name")
    if not categories:
        categories = await products_col.distinct("category")

    if not categories:
        await callback.answer("Please add a Category first before adding products!", show_alert=True)
        return

    buttons = []
    for cat in categories:
        buttons.append([InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"admcat_{cat}")])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_panel")])

    await callback.message.edit_text("<b>Select the category where you want to add the product:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("admcat_"))
async def cb_admin_select_category(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    category = callback.data.split("admcat_")[1]
    await state.update_data(category=category)
    await state.set_state(AdminStates.waiting_for_product_name)
    await callback.message.edit_text(f"<b>Selected Category:</b> {category}\n\n<b>Now enter the Product Name:</b>")
    await callback.answer()

@router.message(AdminStates.waiting_for_product_name)
async def process_admin_product_name(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(AdminStates.waiting_for_product_price)
    await message.answer("<b>Now enter the USD Price (e.g. <code>4.99</code>):</b>")

@router.message(AdminStates.waiting_for_product_price)
async def process_admin_product_price(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    try:
        price = float(message.text.strip())
        if price < 0:
            raise ValueError()
    except ValueError:
        await message.answer("Please enter a valid USD price (e.g. 4.99).")
        return

    await state.update_data(price=price)
    await state.set_state(AdminStates.waiting_for_product_stock)
    await message.answer("<b>Now enter stock / details (one item per line). This will be given to the user after successful payment:</b>")

@router.message(AdminStates.waiting_for_product_stock)
async def process_admin_product_stock(message: Message, state: FSMContext):
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
        [InlineKeyboardButton(text="⚡ Admin Panel", callback_data="admin_panel")]
    ])
    await message.answer(
        f"<b>✅ Product Added Successfully!</b>\n\n"
        f"<b>Name:</b> {data['name']}\n"
        f"<b>Category:</b> {data['category']}\n"
        f"<b>Price:</b> ${data['price']:.2f}\n"
        f"<b>Stock Items Added:</b> {len(stock_items)}",
        reply_markup=kb
    )

# --- Broadcast Flow ---
@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("<b>📢 Send Broadcast</b>\n\nSend the message (text, photo, etc.) you want to broadcast to all users:", reply_markup=kb)
    await callback.answer()

@router.message(AdminStates.waiting_for_broadcast_message)
async def execute_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await state.clear()

    users = await users_col.find({}).to_list(length=100000)
    sent_count = 0
    fail_count = 0

    status_msg = await message.answer("📢 Broadcasting message to all users...")

    for user in users:
        try:
            await message.send_copy(chat_id=user["user_id"])
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Admin Panel", callback_data="admin_panel")]
    ])
    await status_msg.edit_text(
        f"<b>📢 Broadcast Completed!</b>\n\n"
        f"✅ Sent: <code>{sent_count}</code> users\n"
        f"❌ Failed: <code>{fail_count}</code> users",
        reply_markup=kb
    )

# --- See User Activity ---
@router.callback_query(F.data == "admin_user_activity")
async def cb_admin_user_activity(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return

    total_users = await users_col.count_documents({})
    total_orders = await orders_col.count_documents({})
    recent_orders = await orders_col.find({}).sort("created_at", -1).to_list(length=5)

    text = (
        f"<b>👥 User Activity & Stats</b>\n\n"
        f"👤 Total Registered Users: <code>{total_users}</code>\n"
        f"📦 Total Orders Completed: <code>{total_orders}</code>\n\n"
        f"<b>Recent Purchases:</b>\n"
    )
    for ord_item in recent_orders:
        text += f"- User <code>{ord_item['user_id']}</code> bought <b>{ord_item['product_name']}</b> for ${ord_item['price']:.2f}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# --- Delete Products ---
@router.callback_query(F.data == "admin_delete_products")
async def cb_admin_delete_products(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return

    products = await products_col.find({}).to_list(length=50)
    if not products:
        await callback.answer("No products found to delete.", show_alert=True)
        return

    buttons = []
    for p in products:
        buttons.append([
            InlineKeyboardButton(text=f"🗑️ Delete: {p['name']} (${p['price']})", callback_data=f"delprod_{str(p['_id'])}")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_panel")])

    await callback.message.edit_text("<b>🗑️ Select a product to delete:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("delprod_"))
async def cb_confirm_delete_product(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    from bson.objectid import ObjectId
    prod_id = callback.data.split("delprod_")[1]

    try:
        await products_col.delete_one({"_id": ObjectId(prod_id)})
        await callback.answer("✅ Product deleted successfully!", show_alert=True)
        await cb_admin_delete_products(callback)
    except Exception as e:
        await callback.answer(f"Error: {e}", show_alert=True)

# --- Delete Entire Database ---
@router.callback_query(F.data == "admin_delete_db")
async def cb_admin_delete_db_prompt(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ YES, DELETE EVERYTHING", callback_data="confirm_del_db")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(
        "<b>⚠️ DANGER ZONE: Delete Entire Database</b>\n\n"
        "This will permanently wipe all users, products, categories, orders, and transactions.\n"
        "Are you absolutely sure?",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "confirm_del_db")
async def cb_confirm_delete_db(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Unauthorized!", show_alert=True)
        return

    await users_col.delete_many({})
    await products_col.delete_many({})
    await orders_col.delete_many({})
    await transactions_col.delete_many({})
    await categories_col.delete_many({})

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Admin Panel", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("<b>⚠️ Entire database has been successfully wiped and reset.</b>", reply_markup=kb)
    await callback.answer("Database cleared!")

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

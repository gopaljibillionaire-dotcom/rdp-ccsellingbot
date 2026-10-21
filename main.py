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
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
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
bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
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
# Helper Keyboards with Premium Custom Emojis & Styles
# -------------------------------------------------------------------
def get_custom_emoji_btn(text: str, callback_data: str, emoji_key: str, style: str = "primary") -> InlineKeyboardButton:
    """Helper to build an InlineKeyboardButton with a custom Telegram emoji and color style."""
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        custom_emoji_id=config.EMOJI.get(emoji_key),
        style=style
    )

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            get_custom_emoji_btn(" Shop Products", "shop", "bag", "primary"),
            get_custom_emoji_btn(" Deposit Funds", "deposit", "wallet", "success"),
        ],
        [
            get_custom_emoji_btn(" My Profile", "profile", "profile", "primary"),
            get_custom_emoji_btn(" Order History", "my_orders", "buy", "primary"),
        ],
        [
            get_custom_emoji_btn(" Support", "support", "support", "primary"),
        ]
    ]
    if user_id in config.ADMIN_IDS:
        buttons.append([
            InlineKeyboardButton(text="⚡ Admin Panel", callback_data="admin_panel", style="danger")
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
        # Keep profile information updated
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"username": username, "full_name": full_name}}
        )
    return user

# -------------------------------------------------------------------
# User Handlers
# -------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message):
    await get_or_create_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    welcome_text = (
        f"<b>Welcome to One Way Store!</b>\n\n"
        f"Your premium destination for instant digital goods and services.\n"
        f"Select an option below to begin."
    )
    await message.answer(welcome_text, reply_markup=main_menu_keyboard(message.from_user.id))

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    welcome_text = (
        f"<b>One Way Store - Main Menu</b>\n\n"
        f"Choose an action from the options below:"
    )
    await callback.message.edit_text(welcome_text, reply_markup=main_menu_keyboard(callback.from_user.id))
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
        f"<b>User Profile</b>\n\n"
        f"<b>ID:</b> <code>{user['user_id']}</code>\n"
        f"<b>Name:</b> {user['full_name']}\n"
        f"<b>Username:</b> @{user['username'] if user['username'] else 'None'}\n"
        f"<b>Balance:</b> <code>${user.get('balance', 0.0):.2f}</code>\n"
        f"<b>Total Purchases:</b> <code>{purchases_count}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [get_custom_emoji_btn(" Deposit Funds", "deposit", "wallet", "success")],
        [InlineKeyboardButton(text=" Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    text = (
        f"<b>Customer Support</b>\n\n"
        f"Need help with your purchase or deposit?\n"
        f"Contact our official support team at @OneWayStoreSupport."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=" Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# -------------------------------------------------------------------
# Store & Shopping
# -------------------------------------------------------------------
@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery):
    categories = await products_col.distinct("category")
    if not categories:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=" Back", callback_data="main_menu", style="danger")]
        ])
        await callback.message.edit_text("<b>No products available at the moment. Please check back later!</b>", reply_markup=kb)
        await callback.answer()
        return

    buttons = []
    for cat in categories:
        buttons.append([
            InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"cat_{cat}", style="primary")
        ])
    buttons.append([InlineKeyboardButton(text=" Back", callback_data="main_menu", style="danger")])

    await callback.message.edit_text("<b>Select a Category:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
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
        btn_text = f"{p['name']} | ${p['price']:.2f} (Stock: {stock_count})"
        buttons.append([
            InlineKeyboardButton(text=btn_text, callback_data=f"prod_{str(p['_id'])}", style="primary")
        ])
    buttons.append([InlineKeyboardButton(text=" Back to Categories", callback_data="shop", style="danger")])

    await callback.message.edit_text(f"<b>Category: {category}</b>\nSelect an item to purchase:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
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
        f"<b>Product:</b> {product['name']}\n"
        f"<b>Category:</b> {product['category']}\n"
        f"<b>Price:</b> <code>${product['price']:.2f}</code>\n"
        f"<b>Available Stock:</b> <code>{stock_count}</code>"
    )

    buttons = []
    if stock_count > 0:
        buttons.append([
            get_custom_emoji_btn(f" Buy Now (${product['price']:.2f})", f"buy_{str(product['_id'])}", "buy", "success")
        ])
    buttons.append([InlineKeyboardButton(text=" Back", callback_data=f"cat_{product['category']}", style="danger")])

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
        await callback.answer("Insufficient balance! Please deposit funds first.", show_alert=True)
        return

    stock = product.get("stock", [])
    if not stock:
        await callback.answer("Sorry, this item is out of stock!", show_alert=True)
        return

    # Deliver one item from stock atomically
    item_content = stock.pop(0)

    # Update Database
    await products_col.update_one(
        {"_id": product["_id"]},
        {"$set": {"stock": stock}}
    )
    await users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": -product["price"]}}
    )

    # Save Order
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
        f"<b>Purchase Successful!</b>\n\n"
        f"<b>Item:</b> {product['name']}\n"
        f"<b>Price Paid:</b> ${product['price']:.2f}\n\n"
        f"<b>Your Content:</b>\n"
        f"<code>{item_content}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=" Back to Store", callback_data="shop", style="primary")]
    ])
    await callback.message.edit_text(success_text, reply_markup=kb)
    await callback.answer("Purchase complete!")

@router.callback_query(F.data == "my_orders")
async def cb_my_orders(callback: CallbackQuery):
    user_id = callback.from_user.id
    orders = await orders_col.find({"user_id": user_id}).sort("created_at", -1).to_list(length=10)

    if not orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=" Back", callback_data="main_menu", style="danger")]
        ])
        await callback.message.edit_text("<b>You have no order history yet.</b>", reply_markup=kb)
        await callback.answer()
        return

    text = "<b>Your Last 10 Orders:</b>\n\n"
    for idx, order in enumerate(orders, 1):
        date_str = order.get("created_at", datetime.utcnow()).strftime("%Y-%m-%d %H:%M")
        text += (
            f"<b>{idx}. {order['product_name']}</b> - ${order['price']:.2f}\n"
            f"Date: {date_str}\n"
            f"Content: <code>{order['content']}</code>\n"
            f"----------------------------------------\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=" Back", callback_data="main_menu", style="danger")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# -------------------------------------------------------------------
# OxaPay Crypto Deposit Flow
# -------------------------------------------------------------------
@router.callback_query(F.data == "deposit")
async def cb_deposit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.waiting_for_amount)
    text = (
        f"<b>Deposit Balance</b>\n\n"
        f"Please enter the amount in USD you want to deposit (e.g. <code>10</code> or <code>25.50</code>):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=" Cancel", callback_data="main_menu", style="danger")]
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
    
    # Create OxaPay Invoice
    if not config.OXAPAY_MERCHANT_API_KEY:
        await message.answer("Deposit system is currently not configured properly (Missing OxaPay Merchant API Key). Please contact support.")
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

        # Save pending transaction
        await transactions_col.insert_one({
            "track_id": track_id,
            "user_id": message.from_user.id,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.utcnow()
        })

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=" Pay via OxaPay", url=pay_url)],
            [InlineKeyboardButton(text=" Back to Menu", callback_data="main_menu", style="danger")]
        ])
        await message.answer(
            f"<b>Payment Invoice Created!</b>\n\n"
            f"<b>Amount:</b> ${amount:.2f}\n"
            f"<b>Track ID:</b> <code>{track_id}</code>\n\n"
            f"Click the button below to complete your payment. Balance will be updated automatically upon payment confirmation.",
            reply_markup=kb
        )
    else:
        err_msg = result.get("message", "Unknown error")
        logger.error(f"OxaPay error: {result}")
        await message.answer(f"Failed to generate invoice: {err_msg}")

# -------------------------------------------------------------------
# OxaPay Callback Webhook Handler
# -------------------------------------------------------------------
async def oxapay_callback_handler(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        if not data:
            data = await request.json()
    except Exception:
        return web.Response(text="Invalid body", status=400)

    logger.info(f"OxaPay callback received: {data}")

    track_id = data.get("trackId")
    status = data.get("status")

    if track_id and status == "paid":
        tx = await transactions_col.find_one({"track_id": track_id})
        if tx and tx.get("status") != "completed":
            # Update transaction status
            await transactions_col.update_one(
                {"_id": tx["_id"]},
                {"$set": {"status": "completed", "completed_at": datetime.utcnow()}}
            )
            # Add balance to user
            await users_col.update_one(
                {"user_id": tx["user_id"]},
                {"$inc": {"balance": float(tx["amount"])}}
            )
            # Send notification message to user
            try:
                await bot.send_message(
                    chat_id=tx["user_id"],
                    text=f"<b>Deposit Confirmed!</b>\n\nYour account has been credited with <b>${float(tx['amount']):.2f}</b>."
                )
            except Exception as e:
                logger.error(f"Failed to send deposit notification to user {tx['user_id']}: {e}")

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
        [InlineKeyboardButton(text=" Add Product", callback_data="admin_add_product", style="success")],
        [InlineKeyboardButton(text=" Back", callback_data="main_menu", style="danger")]
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
    await message.answer("<b>Step 2/4:</b> Enter Product Category (e.g., Accounts, Keys, Subscriptions):")

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
    await message.answer("<b>Step 4/4:</b> Send stock items (one item per line):")

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
        [InlineKeyboardButton(text=" Back to Admin Panel", callback_data="admin_panel", style="primary")]
    ])
    await message.answer(
        f"<b>Product Added Successfully!</b>\n\n"
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
    # Start Telegram Long Polling in background task
    asyncio.create_task(dp.start_polling(bot))
    logger.info("Bot started and polling for updates...")

async def main():
    app = web.Application()
    # Setup webhook routes for OxaPay callback
    app.router.add_post("/oxapay/callback", oxapay_callback_handler)
    app.on_startup.append(on_startup)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    logger.info(f"Starting web server on port {config.PORT}...")
    await site.start()

    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")

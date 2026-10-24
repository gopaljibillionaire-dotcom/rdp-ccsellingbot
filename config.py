import os
import sys
from typing import List
from dotenv import load_dotenv

load_dotenv()

# Credentials loaded strictly from environment variables
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
OXAPAY_MERCHANT_API_KEY: str = os.getenv("OXAPAY_MERCHANT_API_KEY", "")
OXAPAY_CALLBACK_URL: str = os.getenv("OXAPAY_CALLBACK_URL", "")
OXAPAY_RETURN_URL: str = os.getenv("OXAPAY_RETURN_URL", "")

# Parse ADMIN_IDS as a list of integers
_admin_ids_str = os.getenv("ADMIN_IDS",  "7236482972")
ADMIN_IDS: List[int] = []
if _admin_ids_str:
    for aid in _admin_ids_str.split(","):
        aid_clean = aid.strip()
        if aid_clean.isdigit():
            ADMIN_IDS.append(int(aid_clean))

# Custom Premium Emoji IDs
EMOJI = {
    "thunder": "5992366958681527437",
    "money": "5453901475648390219",
    "fire": "5402406965252989103",
    "buy": "5440841102871517055",
    "bag": "5451937962629544243",
    "support": "5395804191769763641",
    "profile": "5258011929993026890",
    "wallet": "5256186332669035163",
    "tick": "6296367896398399651"
}

# Webserver configuration for webhooks and callbacks
PORT: int = int(os.getenv("PORT", 8080))

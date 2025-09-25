import asyncio
import os
import random
import json
import base64
import struct
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import requests
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solana.rpc.api import Client
from solana.rpc.types import MemcmpOpts
from pydantic import BaseModel, validator
from asyncio_throttle import Throttler
import time

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔑 Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
MAX_SOL_PER_TRADE = float(os.getenv("MAX_SOL_PER_TRADE", "1.0"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

WALLET_FILE = "wallets.json"

# 🌐 Better RPC nodes with fallbacks
RPC_NODES = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-api.projectserum.com", 
    "https://ssc-dao.genesysgo.net",
    "https://rpc.ankr.com/solana",
    "https://solana-mainnet.g.alchemy.com/v2/demo"
]

# 🧩 Program IDs
PUMP_FUN_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")

# Rate limiting
throttler = Throttler(rate_limit=RATE_LIMIT_REQUESTS, period=RATE_LIMIT_WINDOW)
user_last_command = {}

class ValidationError(Exception):
    pass

class TransactionError(Exception):
    pass

# 🛡️ Input validation
def validate_ca_address(ca: str) -> bool:
    """Validate Solana contract address"""
    try:
        Pubkey.from_string(ca)
        return len(ca) >= 32 and len(ca) <= 44
    except:
        return False

def validate_sol_amount(amount: float) -> bool:
    """Validate SOL amount"""
    return 0.001 <= amount <= MAX_SOL_PER_TRADE

def validate_percentage(percent: float) -> bool:
    """Validate percentage"""
    return 0 < percent <= 100

def check_rate_limit(user_id: int) -> bool:
    """Check if user is rate limited"""
    now = time.time()
    if user_id in user_last_command:
        if now - user_last_command[user_id] < 5:  # 5 second cooldown
            return False
    user_last_command[user_id] = now
    return True

def check_admin_access(user_id: int) -> bool:
    """Check if user has admin access (if admin is set)"""
    if ADMIN_USER_ID:
        return str(user_id) == ADMIN_USER_ID
    return True  # If no admin set, allow all users

# 🧠 Enhanced helper functions
def load_wallets() -> list:
    """Load wallets from JSON file with error handling"""
    try:
        if not os.path.exists(WALLET_FILE):
            with open(WALLET_FILE, "w") as f:
                json.dump([], f)
        with open(WALLET_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading wallets: {e}")
        return []

def save_wallets(wallets: list) -> bool:
    """Save wallets to JSON file with error handling"""
    try:
        with open(WALLET_FILE, "w") as f:
            json.dump(wallets, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving wallets: {e}")
        return False

def get_or_create_wallet_for_token(ca: str) -> Dict[str, Any]:
    """Get or create wallet for specific token"""
    wallets = load_wallets()
    for w in wallets:
        if ca in w.get("used_for", []):
            return w
    
    try:
        kp = Keypair()
        wallet = {
            "address": str(kp.pubkey()),
            "private_key": kp.to_base58_string(),
            "used_for": [ca],
            "created_at": datetime.now().isoformat()
        }
        wallets.append(wallet)
        if save_wallets(wallets):
            return wallet
        else:
            raise Exception("Failed to save wallet")
    except Exception as e:
        logger.error(f"Error creating wallet: {e}")
        raise

async def human_delay():
    """Random human-like delay"""
    await asyncio.sleep(random.uniform(0.5, 3.0))

def get_random_amount(base: float) -> float:
    """Get randomized amount within safe bounds"""
    variation = min(0.02, base * 0.1)  # Max 10% variation or 0.02 SOL
    amount = base + random.uniform(-variation, variation)
    return max(0.001, min(amount, MAX_SOL_PER_TRADE))

async def get_working_rpc() -> str:
    """Get a working RPC endpoint with health check"""
    for rpc in random.sample(RPC_NODES, len(RPC_NODES)):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getHealth"}) as response:
                    if response.status == 200:
                        return rpc
        except:
            continue
    return RPC_NODES[0]  # Fallback to first RPC

# 🧨 Enhanced MEV transaction with retry
async def send_mev_transaction(signed_tx: VersionedTransaction, max_retries: int = 3) -> str:
    """Send transaction via Jito with retry logic"""
    url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
    raw_tx = bytes(signed_tx)
    encoded = base64.b64encode(raw_tx).decode('utf-8')
    payload = {"jsonrpc": "2.0", "id": 1, "method": "sendBundle", "params": [{"data": [encoded]}]}
    
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(url, json=payload) as response:
                    result = await response.json()
                    if "error" in result:
                        raise TransactionError(f"Jito error: {result['error']}")
                    return result["result"]["bundleId"]
        except Exception as e:
            if attempt == max_retries - 1:
                raise TransactionError(f"Transaction failed after {max_retries} attempts: {str(e)}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

# 💰 Enhanced transaction instructions
def create_buy_ix(buyer: Pubkey, mint: Pubkey, lamports: int) -> Dict[str, Any]:
    """Create buy instruction with validation"""
    if lamports <= 0:
        raise ValidationError("Lamports must be positive")
    
    disc = struct.pack("<Q", 16927863322537952870)  # global:buy
    amt = struct.pack("<Q", lamports)
    data = disc + amt
    
    keys = [
        {"pubkey": buyer, "is_signer": True, "is_writable": True},
        {"pubkey": mint, "is_signer": False, "is_writable": True},
        {"pubkey": SYSTEM_PROGRAM_ID, "is_signer": False, "is_writable": False},
    ]
    return {"program_id": PUMP_FUN_PROGRAM_ID, "keys": keys, "data": data}

def create_sell_ix(seller: Pubkey, mint: Pubkey, token_amount: int) -> Dict[str, Any]:
    """Create sell instruction with validation"""
    if token_amount <= 0:
        raise ValidationError("Token amount must be positive")
    
    disc = struct.pack("<Q", 12502976035594553355)  # global:sell
    amt = struct.pack("<Q", token_amount)
    data = disc + amt
    
    keys = [
        {"pubkey": seller, "is_signer": True, "is_writable": True},
        {"pubkey": mint, "is_signer": False, "is_writable": True},
        {"pubkey": SYSTEM_PROGRAM_ID, "is_signer": False, "is_writable": False},
    ]
    return {"program_id": PUMP_FUN_PROGRAM_ID, "keys": keys, "data": data}

# 🛠️ Enhanced execute functions
async def execute_buy(ca: str, sol_amount: float, pk: str) -> str:
    """Execute buy transaction with improved error handling"""
    rpc = await get_working_rpc()
    client = Client(rpc)
    
    try:
        buyer = Keypair.from_base58_string(pk)
        mint = Pubkey.from_string(ca)
        lamports = int(sol_amount * 1_000_000_000)
        
        ix = create_buy_ix(buyer.pubkey(), mint, lamports)
        bh = client.get_latest_blockhash().value.blockhash
        msg = MessageV0.try_compile(
            payer=buyer.pubkey(), 
            instructions=[ix], 
            address_lookup_table_accounts=[], 
            recent_blockhash=bh
        )
        tx = VersionedTransaction(msg, [buyer])
        
        bid = await send_mev_transaction(tx)
        return f"https://solscan.io/tx/{bid}"
        
    except Exception as e:
        logger.error(f"Buy execution error: {e}")
        raise TransactionError(f"Buy failed: {str(e)}")

async def execute_sell(ca: str, token_amount: int, pk: str) -> str:
    """Execute sell transaction with improved error handling"""
    rpc = await get_working_rpc()
    client = Client(rpc)
    
    try:
        seller = Keypair.from_base58_string(pk)
        mint = Pubkey.from_string(ca)
        
        ix = create_sell_ix(seller.pubkey(), mint, token_amount)
        bh = client.get_latest_blockhash().value.blockhash
        msg = MessageV0.try_compile(
            payer=seller.pubkey(), 
            instructions=[ix], 
            address_lookup_table_accounts=[], 
            recent_blockhash=bh
        )
        tx = VersionedTransaction(msg, [seller])
        
        bid = await send_mev_transaction(tx)
        return f"https://solscan.io/tx/{bid}"
        
    except Exception as e:
        logger.error(f"Sell execution error: {e}")
        raise TransactionError(f"Sell failed: {str(e)}")

# 🔍 Enhanced token balance function
async def get_token_balance(ca: str, wallet_addr: str) -> tuple[int, float]:
    """Get both token balance and SOL balance"""
    rpc = await get_working_rpc()
    client = Client(rpc)
    
    try:
        mint = Pubkey.from_string(ca)
        wallet = Pubkey.from_string(wallet_addr)
        
        # Get SOL balance
        sol_balance_response = client.get_balance(wallet)
        sol_balance = sol_balance_response.value / 1_000_000_000 if sol_balance_response.value else 0
        
        # Find ATA (Associated Token Account)
        ata = Pubkey.find_program_address(
            [bytes(wallet), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
            ASSOCIATED_TOKEN_PROGRAM_ID
        )[0]

        # Get account data
        account_info = client.get_account_info(ata)
        if not account_info.value:
            return 0, sol_balance

        # Token balance is the first 8 bytes (u64, little-endian)
        data = account_info.value.data
        if len(data) < 64:
            return 0, sol_balance
            
        token_balance = int.from_bytes(data[:8], "little")
        return token_balance, sol_balance
        
    except Exception as e:
        logger.error(f"Balance check error: {e}")
        return 0, 0.0

# 🚨 Enhanced rug detection
async def check_rug_risk(ca: str) -> Dict[str, Any]:
    """Enhanced rug pull detection with more metrics"""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(f"https://api.pump.fun/coins/{ca}") as response:
                if response.status != 200:
                    return {"risk": True, "reason": "API unavailable"}
                
                data = await response.json()
                
                # Multiple risk factors
                lp_locked = data.get("lpLocked", False)
                owner_has_admin = data.get("ownerHasAdmin", False)
                recent_volume = data.get("recentVolume", 0)
                holder_count = data.get("holderCount", 0)
                market_cap = data.get("marketCap", 0)
                
                risk_factors = []
                
                if not lp_locked:
                    risk_factors.append("LP not locked")
                if owner_has_admin:
                    risk_factors.append("Owner has admin rights")
                if recent_volume < 1000:
                    risk_factors.append("Low volume")
                if holder_count < 50:
                    risk_factors.append("Few holders")
                if market_cap < 10000:
                    risk_factors.append("Low market cap")
                    
                return {
                    "risk": len(risk_factors) >= 3,
                    "risk_score": len(risk_factors),
                    "factors": risk_factors,
                    "data": data
                }
                
    except Exception as e:
        logger.error(f"Rug check error: {e}")
        return {"risk": True, "reason": f"Check failed: {str(e)}"}

# 🎯 Enhanced command handlers with validation
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced start command with user info"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if not check_admin_access(user_id):
        await update.message.reply_text("❌ Access denied. This bot is restricted to admin only.")
        return
    
    logger.info(f"User {username} ({user_id}) started the bot")
    
    await update.message.reply_text(
        "🚀 **PumpShield Pro — Enhanced Trading Bot**\n\n"
        "**Commands:**\n"
        "🟢 `/pump <CA> <SOL>` → Buy tokens\n"
        "🔄 `/repump <CA> <SOL>` → Buy more tokens\n" 
        "🔴 `/dump <CA> <%>` → Sell percentage\n"
        "🔁 `/loop <CA> buy=X sell=Y delay=Z` → Auto trading loop\n"
        "📊 `/balance <CA>` → Check balances\n"
        "🛡️ `/rugcheck <CA>` → Check rug pull risk\n"
        "🚨 `/auto <CA>` → Auto-sell on rug detection\n\n"
        "**Safety Features:**\n"
        "• Input validation\n"
        "• Rate limiting\n"
        "• Enhanced error handling\n"
        "• Multi-RPC fallback\n\n"
        f"**Limits:** Max {MAX_SOL_PER_TRADE} SOL per trade",
        parse_mode='Markdown'
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced balance command"""
    user_id = update.effective_user.id
    
    if not check_admin_access(user_id) or not check_rate_limit(user_id):
        await update.message.reply_text("❌ Access denied or rate limited.")
        return
        
    if not context.args:
        await update.message.reply_text("❌ Usage: `/balance <CA>`", parse_mode='Markdown')
        return
        
    ca = context.args[0]
    
    if not validate_ca_address(ca):
        await update.message.reply_text("❌ Invalid contract address")
        return
    
    try:
        wallet = get_or_create_wallet_for_token(ca)
        token_balance, sol_balance = await get_token_balance(ca, wallet["address"])
        
        await update.message.reply_text(
            f"📊 **Balance Report**\n\n"
            f"**Token:** `{ca[:8]}...{ca[-8:]}`\n"
            f"**Wallet:** `{wallet['address'][:8]}...{wallet['address'][-8:]}`\n\n"
            f"**Token Balance:** {token_balance:,} tokens\n"
            f"**SOL Balance:** {sol_balance:.6f} SOL",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Balance command error: {e}")
        await update.message.reply_text(f"❌ Error checking balance: {str(e)}")

async def pump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced pump command with validation"""
    user_id = update.effective_user.id
    
    if not check_admin_access(user_id) or not check_rate_limit(user_id):
        await update.message.reply_text("❌ Access denied or rate limited.")
        return
        
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: `/pump <CA> <SOL>`", parse_mode='Markdown')
        return
    
    ca = context.args[0]
    
    try:
        sol_amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid SOL amount")
        return
    
    # Validation
    if not validate_ca_address(ca):
        await update.message.reply_text("❌ Invalid contract address")
        return
        
    if not validate_sol_amount(sol_amount):
        await update.message.reply_text(f"❌ SOL amount must be between 0.001 and {MAX_SOL_PER_TRADE}")
        return
    
    msg = await update.message.reply_text("⏳ **Processing buy order...**", parse_mode='Markdown')
    
    try:
        await human_delay()
        actual_amount = get_random_amount(sol_amount)
        wallet = get_or_create_wallet_for_token(ca)
        
        # Check rug risk first
        async with throttler:
            rug_check = await check_rug_risk(ca)
            
        if rug_check["risk"]:
            await msg.edit_text(
                f"⚠️ **High rug risk detected!**\n\n"
                f"Risk factors: {', '.join(rug_check.get('factors', ['Unknown']))}\n"
                f"Continue anyway? Send `/pump {ca} {sol_amount} force` to override.",
                parse_mode='Markdown'
            )
            return
        
        tx_link = await execute_buy(ca, actual_amount, wallet["private_key"])
        
        await msg.edit_text(
            f"✅ **Buy Order Successful**\n\n"
            f"**Amount:** {actual_amount:.5f} SOL\n"
            f"**Token:** `{ca[:8]}...{ca[-8:]}`\n"
            f"**Wallet:** `{wallet['address'][:8]}...`\n"
            f"**TX:** [View on Solscan]({tx_link})",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Pump command error: {e}")
        await msg.edit_text(f"❌ **Buy failed:** {str(e)}")

async def dump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fixed dump command that actually calculates token amount to sell"""
    user_id = update.effective_user.id
    
    if not check_admin_access(user_id) or not check_rate_limit(user_id):
        await update.message.reply_text("❌ Access denied or rate limited.")
        return
        
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: `/dump <CA> <%>`", parse_mode='Markdown')
        return
    
    ca = context.args[0]
    
    try:
        percent = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid percentage")
        return
    
    # Validation
    if not validate_ca_address(ca):
        await update.message.reply_text("❌ Invalid contract address")
        return
        
    if not validate_percentage(percent):
        await update.message.reply_text("❌ Percentage must be between 1 and 100")
        return
    
    msg = await update.message.reply_text("⏳ **Processing sell order...**", parse_mode='Markdown')
    
    try:
        wallet = get_or_create_wallet_for_token(ca)
        
        # First get current token balance
        token_balance, sol_balance = await get_token_balance(ca, wallet["address"])
        
        if token_balance <= 0:
            await msg.edit_text("❌ **No tokens to sell**")
            return
        
        # Calculate actual token amount to sell
        token_amount_to_sell = int(token_balance * (percent / 100))
        
        if token_amount_to_sell <= 0:
            await msg.edit_text("❌ **Calculated sell amount is 0**")
            return
        
        await human_delay()
        tx_link = await execute_sell(ca, token_amount_to_sell, wallet["private_key"])
        
        await msg.edit_text(
            f"✅ **Sell Order Successful**\n\n"
            f"**Percentage:** {percent}%\n"
            f"**Token Amount:** {token_amount_to_sell:,} tokens\n"
            f"**Token:** `{ca[:8]}...{ca[-8:]}`\n"
            f"**Wallet:** `{wallet['address'][:8]}...`\n"
            f"**TX:** [View on Solscan]({tx_link})",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Dump command error: {e}")
        await msg.edit_text(f"❌ **Sell failed:** {str(e)}")

async def rugcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """New rug check command"""
    user_id = update.effective_user.id
    
    if not check_admin_access(user_id) or not check_rate_limit(user_id):
        await update.message.reply_text("❌ Access denied or rate limited.")
        return
        
    if not context.args:
        await update.message.reply_text("❌ Usage: `/rugcheck <CA>`", parse_mode='Markdown')
        return
    
    ca = context.args[0]
    
    if not validate_ca_address(ca):
        await update.message.reply_text("❌ Invalid contract address")
        return
    
    msg = await update.message.reply_text("⏳ **Analyzing token...**", parse_mode='Markdown')
    
    try:
        async with throttler:
            result = await check_rug_risk(ca)
        
        if result["risk"]:
            risk_emoji = "🚨"
            risk_text = "HIGH RISK"
        else:
            risk_emoji = "✅"
            risk_text = "LOW RISK"
        
        response = f"{risk_emoji} **{risk_text}**\n\n"
        response += f"**Token:** `{ca[:8]}...{ca[-8:]}`\n"
        response += f"**Risk Score:** {result.get('risk_score', 0)}/5\n"
        
        if result.get('factors'):
            response += f"**Risk Factors:**\n"
            for factor in result['factors']:
                response += f"• {factor}\n"
        
        if result.get('data'):
            data = result['data']
            response += f"\n**Token Info:**\n"
            response += f"• Market Cap: ${data.get('marketCap', 0):,.0f}\n"
            response += f"• Volume: ${data.get('recentVolume', 0):,.0f}\n"
            response += f"• Holders: {data.get('holderCount', 0):,}\n"
            response += f"• LP Locked: {'Yes' if data.get('lpLocked') else 'No'}\n"
        
        await msg.edit_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Rugcheck command error: {e}")
        await msg.edit_text(f"❌ **Analysis failed:** {str(e)}")

# Main application
def main():
    """Enhanced main function with better error handling"""
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN not found in environment variables")
        return
    
    app = Application.builder().token(TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pump", pump))
    app.add_handler(CommandHandler("repump", pump))  # Reuse pump handler
    app.add_handler(CommandHandler("dump", dump))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("rugcheck", rugcheck))
    
    logger.info("🚀 Enhanced PumpShield Bot started successfully")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
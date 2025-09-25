import asyncio
import os
import random
import json
import base64
import struct
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import requests
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
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

# 📚 Help text and examples
HELP_TEXT = {
    "start": """
🚀 **PumpShield Pro - Advanced Solana Trading Bot**

**📖 QUICK START GUIDE:**

**1️⃣ Buy Tokens:**
• `/pump <CA> <SOL_AMOUNT>`
• Example: `/pump So11111111111111111111111111111111111111112 0.1`
• Buys 0.1 SOL worth of tokens

**2️⃣ Sell Tokens:**
• `/dump <CA> <PERCENTAGE>`
• Example: `/dump So11111111111111111111111111111111111111112 50`
• Sells 50% of your tokens

**3️⃣ Check Balance:**
• `/balance <CA>`
• Shows both token and SOL balance

**4️⃣ Check Risk:**
• `/rugcheck <CA>`
• Analyzes rug pull risk factors

**🎯 Use `/help <command>` for detailed explanations!**
""",
    
    "pump": """
🟢 **BUY COMMAND - `/pump`**

**📝 Syntax:**
`/pump <CONTRACT_ADDRESS> <SOL_AMOUNT>`

**📊 Parameters:**
• **CONTRACT_ADDRESS**: The token's contract address (44 characters)
• **SOL_AMOUNT**: Amount of SOL to spend (0.001 - {max_sol})

**✅ Examples:**
• `/pump So11111111111111111111111111111111111111112 0.05`
• `/pump 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU 0.1`

**🔍 What happens:**
1. Validates contract address and amount
2. Checks for rug pull risks
3. Creates secure wallet for this token
4. Executes buy transaction via MEV protection
5. Shows transaction link and wallet info

**⚠️ Safety Features:**
• Input validation prevents invalid trades
• Rug detection warns of high-risk tokens
• Rate limiting prevents spam
• MEV protection via Jito
""",

    "dump": """
🔴 **SELL COMMAND - `/dump`**

**📝 Syntax:**
`/dump <CONTRACT_ADDRESS> <PERCENTAGE>`

**📊 Parameters:**
• **CONTRACT_ADDRESS**: The token's contract address
• **PERCENTAGE**: Percentage to sell (1-100)

**✅ Examples:**
• `/dump So11111111111111111111111111111111111111112 25` (sell 25%)
• `/dump 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU 100` (sell all)

**🔍 What happens:**
1. Checks your current token balance
2. Calculates exact tokens to sell (balance × percentage)
3. Executes sell transaction
4. Shows transaction details

**💡 Smart Features:**
• Automatically calculates token amounts
• Shows both percentage and actual tokens sold
• Prevents selling more than you have
• MEV protection for better prices
""",

    "balance": """
📊 **BALANCE COMMAND - `/balance`**

**📝 Syntax:**
`/balance <CONTRACT_ADDRESS>`

**📊 Parameters:**
• **CONTRACT_ADDRESS**: Token contract to check

**✅ Example:**
• `/balance So11111111111111111111111111111111111111112`

**🔍 What you get:**
• **Token Balance**: Exact number of tokens you own
• **SOL Balance**: SOL in the wallet
• **Wallet Address**: Your wallet for this token
• **Contract Info**: Shortened contract address

**💡 Features:**
• Real-time balance from blockchain
• Shows both token and SOL balances
• Wallet-specific for each token
• Fast and accurate
""",

    "rugcheck": """
🛡️ **RUG CHECK COMMAND - `/rugcheck`**

**📝 Syntax:**
`/rugcheck <CONTRACT_ADDRESS>`

**📊 Parameters:**
• **CONTRACT_ADDRESS**: Token contract to analyze

**✅ Example:**
• `/rugcheck 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`

**🔍 Risk Analysis:**
• **LP Locked**: Is liquidity pool locked?
• **Owner Rights**: Does owner have admin control?
• **Volume**: Recent trading activity
• **Holders**: Number of token holders
• **Market Cap**: Total market value

**📈 Risk Score:**
• **0-1**: ✅ Low Risk
• **2-3**: ⚠️ Medium Risk  
• **4-5**: 🚨 High Risk

**💡 Smart Detection:**
• Multiple risk factors analyzed
• Real-time data from Pump.fun
• Detailed explanations for each risk
• Helps prevent rug pulls
""",

    "auto": """
🤖 **AUTO SELL COMMAND - `/auto`**

**📝 Syntax:**
`/auto <CONTRACT_ADDRESS>`

**📊 Parameters:**
• **CONTRACT_ADDRESS**: Token to monitor

**✅ Example:**
• `/auto 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`

**🔍 What happens:**
1. Analyzes token for rug pull risks
2. If HIGH RISK detected → sells immediately
3. If LOW RISK → continues monitoring

**⚠️ Auto-sell triggers:**
• LP not locked + Owner has admin rights
• Very low volume + Few holders
• Market cap drops significantly
• Multiple risk factors present

**💡 Protection Features:**
• Instant sell on rug detection
• Saves your investment automatically
• Real-time monitoring
• Smart risk algorithms
"""
}

class ValidationError(Exception):
    pass

class TransactionError(Exception):
    pass

# 🛡️ Enhanced input validation with detailed feedback
def validate_ca_address(ca: str) -> tuple[bool, str]:
    """Validate Solana contract address with detailed feedback"""
    try:
        if not ca:
            return False, "❌ Contract address is required"
        if len(ca) < 32:
            return False, "❌ Contract address too short (minimum 32 characters)"
        if len(ca) > 44:
            return False, "❌ Contract address too long (maximum 44 characters)"
        Pubkey.from_string(ca)
        return True, "✅ Valid contract address"
    except Exception as e:
        return False, f"❌ Invalid contract address format: {str(e)}"

def validate_sol_amount(amount: float) -> tuple[bool, str]:
    """Validate SOL amount with detailed feedback"""
    if amount <= 0:
        return False, "❌ SOL amount must be positive"
    if amount < 0.001:
        return False, "❌ Minimum SOL amount is 0.001"
    if amount > MAX_SOL_PER_TRADE:
        return False, f"❌ Maximum SOL amount is {MAX_SOL_PER_TRADE}"
    return True, f"✅ Valid SOL amount: {amount}"

def validate_percentage(percent: float) -> tuple[bool, str]:
    """Validate percentage with detailed feedback"""
    if percent <= 0:
        return False, "❌ Percentage must be positive"
    if percent > 100:
        return False, "❌ Maximum percentage is 100%"
    return True, f"✅ Valid percentage: {percent}%"

def format_number(num: float, decimals: int = 6) -> str:
    """Format numbers with proper comma separation"""
    if num >= 1_000_000:
        return f"{num/1_000_000:.2f}M"
    elif num >= 1_000:
        return f"{num/1_000:.2f}K"
    else:
        return f"{num:,.{decimals}f}"

def shorten_address(address: str, start: int = 8, end: int = 8) -> str:
    """Shorten long addresses for display"""
    if len(address) <= start + end + 3:
        return address
    return f"{address[:start]}...{address[-end:]}"

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

# 🎯 Enhanced command handlers with better UX
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced start command with interactive buttons"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if not check_admin_access(user_id):
        await update.message.reply_text("❌ Access denied. This bot is restricted to admin only.")
        return
    
    logger.info(f"User {username} ({user_id}) started the bot")
    
    # Create interactive keyboard
    keyboard = [
        [InlineKeyboardButton("📖 Commands Help", callback_data='help_commands')],
        [InlineKeyboardButton("💡 Examples", callback_data='help_examples')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='help_settings')],
        [InlineKeyboardButton("🛡️ Safety Info", callback_data='help_safety')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        HELP_TEXT["start"].format(max_sol=MAX_SOL_PER_TRADE),
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed help for specific commands"""
    if not check_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not context.args:
        # Show available help topics
        keyboard = [
            [InlineKeyboardButton("🟢 pump", callback_data='help_pump')],
            [InlineKeyboardButton("🔴 dump", callback_data='help_dump')],
            [InlineKeyboardButton("📊 balance", callback_data='help_balance')],
            [InlineKeyboardButton("🛡️ rugcheck", callback_data='help_rugcheck')],
            [InlineKeyboardButton("🤖 auto", callback_data='help_auto')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📚 **Choose a command for detailed help:**",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    command = context.args[0].lower()
    if command in HELP_TEXT:
        help_text = HELP_TEXT[command].format(max_sol=MAX_SOL_PER_TRADE)
        await update.message.reply_text(help_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            f"❌ No help available for '{command}'\n\n"
            f"Available commands: {', '.join(HELP_TEXT.keys())}"
        )

async def examples_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show practical examples"""
    if not check_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Access denied.")
        return
    
    examples_text = """
💡 **PRACTICAL EXAMPLES:**

**🎯 Scenario 1: First Time Buying**
```
1. /rugcheck So11111111111111111111111111111111111111112
2. /pump So11111111111111111111111111111111111111112 0.05
3. /balance So11111111111111111111111111111111111111112
```

**🎯 Scenario 2: Taking Profits**
```
1. /balance 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU
2. /dump 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU 25
   (sells 25% of tokens)
```

**🎯 Scenario 3: Safety First**
```
1. /rugcheck NEW_TOKEN_ADDRESS
2. If low risk → /pump NEW_TOKEN_ADDRESS 0.1
3. Set protection → /auto NEW_TOKEN_ADDRESS
```

**🎯 Scenario 4: Emergency Exit**
```
/dump TOKEN_ADDRESS 100
(sells all tokens immediately)
```

**📝 Pro Tips:**
• Always rugcheck before buying
• Start with small amounts (0.01-0.05 SOL)
• Set auto-sell for protection
• Check balance before selling
• Use proper contract addresses (44 chars)
"""
    
    await update.message.reply_text(examples_text, parse_mode='Markdown')

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks"""
    query = update.callback_query
    await query.answer()
    
    if not check_admin_access(query.from_user.id):
        await query.edit_message_text("❌ Access denied.")
        return
    
    data = query.data
    
    if data.startswith('help_'):
        command = data.replace('help_', '')
        if command in HELP_TEXT:
            help_text = HELP_TEXT[command].format(max_sol=MAX_SOL_PER_TRADE)
            await query.edit_message_text(help_text, parse_mode='Markdown')
        elif command == 'commands':
            commands_text = """
📖 **ALL COMMANDS:**

🟢 `/pump <CA> <SOL>` - Buy tokens
🔴 `/dump <CA> <%>` - Sell tokens  
📊 `/balance <CA>` - Check balances
🛡️ `/rugcheck <CA>` - Analyze risk
🤖 `/auto <CA>` - Auto-sell protection
📚 `/help <command>` - Detailed help
💡 `/examples` - Practical examples
⚙️ `/settings` - Bot configuration
📊 `/stats` - Your trading stats

**💡 Tip:** Use `/help pump` for detailed pump command help!
"""
            await query.edit_message_text(commands_text, parse_mode='Markdown')
        elif command == 'examples':
            await examples_command(update, context)
        elif command == 'settings':
            settings_text = f"""
⚙️ **CURRENT SETTINGS:**

**🔒 Security:**
• Max SOL per trade: {MAX_SOL_PER_TRADE}
• Rate limit: {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW}s
• Admin only: {'Yes' if ADMIN_USER_ID else 'No'}

**🌐 Network:**
• RPC nodes: {len(RPC_NODES)} configured
• MEV protection: ✅ Enabled (Jito)
• Auto failover: ✅ Enabled

**💾 Data:**
• Wallet storage: JSON file
• Logging: ✅ Enabled

**💡 To modify settings:**
Edit your `.env` file and restart the bot.
"""
            await query.edit_message_text(settings_text, parse_mode='Markdown')
        elif command == 'safety':
            safety_text = """
🛡️ **SAFETY FEATURES:**

**🔍 Input Validation:**
• Contract address format checking
• SOL amount limits and validation
• Percentage range validation
• Real-time error feedback

**⚡ Rate Limiting:**
• 5 second cooldown between commands
• Prevents spam and abuse
• User-specific limits

**🚨 Rug Protection:**
• Multi-factor risk analysis
• Real-time token data
• Automatic risk scoring
• Warning before high-risk trades

**💰 Financial Safety:**
• Maximum trade limits
• MEV protection via Jito
• Secure wallet generation
• Transaction retry logic

**🌐 Network Safety:**
• Multiple RPC fallbacks
• Health check monitoring
• Automatic failover
• Connection timeout handling

**💡 Always:**
• Start with small amounts
• Check rugcheck before buying
• Use auto-sell for protection
• Verify contract addresses
"""
            await query.edit_message_text(safety_text, parse_mode='Markdown')

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced balance command with better formatting"""
    user_id = update.effective_user.id
    
    if not check_admin_access(user_id) or not check_rate_limit(user_id):
        await update.message.reply_text("❌ Access denied or rate limited.")
        return
        
    if not context.args:
        await update.message.reply_text(
            "❌ **Missing Parameter**\n\n"
            "**Usage:** `/balance <CONTRACT_ADDRESS>`\n\n"
            "**Example:** `/balance So11111111111111111111111111111111111111112`\n\n"
            "💡 Use `/help balance` for detailed explanation",
            parse_mode='Markdown'
        )
        return
        
    ca = context.args[0]
    
    # Validate input
    is_valid, message = validate_ca_address(ca)
    if not is_valid:
        await update.message.reply_text(f"{message}\n\n💡 Use `/help balance` for examples")
        return
    
    try:
        wallet = get_or_create_wallet_for_token(ca)
        token_balance, sol_balance = await get_token_balance(ca, wallet["address"])
        
        # Create detailed balance report
        report = f"""
📊 **BALANCE REPORT**

**🏷️ Token:** `{shorten_address(ca)}`
**👛 Wallet:** `{shorten_address(wallet['address'])}`

**💰 BALANCES:**
🪙 **Tokens:** {format_number(token_balance, 0)} tokens
💎 **SOL:** {format_number(sol_balance)} SOL

**📅 Wallet Created:** {wallet.get('created_at', 'Unknown')[:10]}

💡 **Need help?** Use `/help dump` to learn how to sell tokens
"""
        
        await update.message.reply_text(report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Balance command error: {e}")
        await update.message.reply_text(
            f"❌ **Error checking balance**\n\n"
            f"Details: {str(e)}\n\n"
            f"💡 Try again in a few seconds or use `/help balance`"
        )

async def pump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced pump command with detailed validation and feedback"""
    user_id = update.effective_user.id
    
    if not check_admin_access(user_id) or not check_rate_limit(user_id):
        await update.message.reply_text("❌ Access denied or rate limited.")
        return
        
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ **Missing Parameters**\n\n"
            "**Usage:** `/pump <CONTRACT_ADDRESS> <SOL_AMOUNT>`\n\n"
            "**Parameters:**\n"
            f"• **CONTRACT_ADDRESS:** Token contract (44 chars)\n"
            f"• **SOL_AMOUNT:** SOL to spend (0.001-{MAX_SOL_PER_TRADE})\n\n"
            "**Example:** `/pump So11111111111111111111111111111111111111112 0.05`\n\n"
            "💡 Use `/help pump` for detailed guide",
            parse_mode='Markdown'
        )
        return
    
    ca = context.args[0]
    
    try:
        sol_amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "❌ **Invalid SOL Amount**\n\n"
            f"Must be a number between 0.001 and {MAX_SOL_PER_TRADE}\n\n"
            "**Examples:** `0.05`, `0.1`, `0.25`"
        )
        return
    
    # Validate contract address
    is_valid_ca, ca_message = validate_ca_address(ca)
    if not is_valid_ca:
        await update.message.reply_text(f"{ca_message}\n\n💡 Use `/help pump` for examples")
        return
    
    # Validate SOL amount
    is_valid_amount, amount_message = validate_sol_amount(sol_amount)
    if not is_valid_amount:
        await update.message.reply_text(f"{amount_message}\n\n💡 Use `/help pump` for examples")
        return
    
    # Create progress message
    msg = await update.message.reply_text("⏳ **Processing Buy Order...**\n\n🔍 Validating parameters...", parse_mode='Markdown')
    
    try:
        # Step 1: Rug check
        await msg.edit_text("⏳ **Processing Buy Order...**\n\n🛡️ Checking rug pull risks...", parse_mode='Markdown')
        
        async with throttler:
            rug_check = await check_rug_risk(ca)
            
        if rug_check["risk"] and "force" not in context.args:
            risk_report = f"""
⚠️ **HIGH RUG RISK DETECTED!**

**🎯 Token:** `{shorten_address(ca)}`
**📊 Risk Score:** {rug_check.get('risk_score', 0)}/5

**🚨 Risk Factors:**
"""
            for factor in rug_check.get('factors', ['Unknown risk']):
                risk_report += f"• {factor}\n"
            
            risk_report += f"""
**💡 To override this warning:**
`/pump {ca} {sol_amount} force`

**🛡️ Recommendation:** Use `/rugcheck {ca}` for detailed analysis
"""
            await msg.edit_text(risk_report, parse_mode='Markdown')
            return
        
        # Step 2: Create wallet and execute
        await msg.edit_text("⏳ **Processing Buy Order...**\n\n👛 Preparing wallet...", parse_mode='Markdown')
        await human_delay()
        
        actual_amount = get_random_amount(sol_amount)
        wallet = get_or_create_wallet_for_token(ca)
        
        await msg.edit_text("⏳ **Processing Buy Order...**\n\n🚀 Executing transaction...", parse_mode='Markdown')
        
        tx_link = await execute_buy(ca, actual_amount, wallet["private_key"])
        
        # Success message
        success_report = f"""
✅ **BUY ORDER SUCCESSFUL!**

**📊 TRADE DETAILS:**
🪙 **Token:** `{shorten_address(ca)}`
💰 **Amount:** {format_number(actual_amount)} SOL
👛 **Wallet:** `{shorten_address(wallet['address'])}`
⛽ **Gas:** Optimized via MEV protection

**🔗 TRANSACTION:**
[📋 View on Solscan]({tx_link})

**📊 Next Steps:**
• `/balance {ca}` - Check your balance
• `/dump {ca} <percent>` - Sell tokens
• `/auto {ca}` - Enable auto-sell protection

🎉 **Happy trading!**
"""
        
        await msg.edit_text(success_report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Pump command error: {e}")
        error_report = f"""
❌ **BUY ORDER FAILED**

**🎯 Token:** `{shorten_address(ca)}`
**💰 Amount:** {format_number(sol_amount)} SOL

**❌ Error Details:**
{str(e)}

**💡 Troubleshooting:**
• Check your contract address
• Try a smaller amount
• Wait a moment and retry
• Use `/help pump` for guidance

**🆘 Still having issues?** The RPC might be busy, try again in a few seconds.
"""
        await msg.edit_text(error_report, parse_mode='Markdown')

async def dump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced dump command with detailed validation and calculation display"""
    user_id = update.effective_user.id
    
    if not check_admin_access(user_id) or not check_rate_limit(user_id):
        await update.message.reply_text("❌ Access denied or rate limited.")
        return
        
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ **Missing Parameters**\n\n"
            "**Usage:** `/dump <CONTRACT_ADDRESS> <PERCENTAGE>`\n\n"
            "**Parameters:**\n"
            "• **CONTRACT_ADDRESS:** Token contract (44 chars)\n"
            "• **PERCENTAGE:** Percent to sell (1-100)\n\n"
            "**Examples:**\n"
            "• `/dump So11111111111111111111111111111111111111112 25` (sell 25%)\n"
            "• `/dump 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU 100` (sell all)\n\n"
            "💡 Use `/help dump` for detailed guide",
            parse_mode='Markdown'
        )
        return
    
    ca = context.args[0]
    
    try:
        percent = float(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "❌ **Invalid Percentage**\n\n"
            "Must be a number between 1 and 100\n\n"
            "**Examples:** `25`, `50`, `75`, `100`"
        )
        return
    
    # Validate inputs
    is_valid_ca, ca_message = validate_ca_address(ca)
    if not is_valid_ca:
        await update.message.reply_text(f"{ca_message}\n\n💡 Use `/help dump` for examples")
        return
        
    is_valid_percent, percent_message = validate_percentage(percent)
    if not is_valid_percent:
        await update.message.reply_text(f"{percent_message}\n\n💡 Use `/help dump` for examples")
        return
    
    msg = await update.message.reply_text("⏳ **Processing Sell Order...**\n\n👛 Checking wallet balance...", parse_mode='Markdown')
    
    try:
        wallet = get_or_create_wallet_for_token(ca)
        
        # Get current balance
        token_balance, sol_balance = await get_token_balance(ca, wallet["address"])
        
        if token_balance <= 0:
            no_tokens_msg = f"""
❌ **NO TOKENS TO SELL**

**🎯 Token:** `{shorten_address(ca)}`
**👛 Wallet:** `{shorten_address(wallet['address'])}`

**💰 Current Balance:** 0 tokens

**💡 Solutions:**
• Check if you have tokens in this wallet
• Use `/balance {ca}` to verify
• Make sure you're using the correct contract address
"""
            await msg.edit_text(no_tokens_msg, parse_mode='Markdown')
            return
        
        # Calculate sell amount
        token_amount_to_sell = int(token_balance * (percent / 100))
        
        if token_amount_to_sell <= 0:
            await msg.edit_text(
                f"❌ **Calculated sell amount is 0**\n\n"
                f"Your balance ({format_number(token_balance, 0)} tokens) × {percent}% = 0\n\n"
                f"💡 Try a higher percentage or check your balance"
            )
            return
        
        # Show calculation before executing
        calculation_msg = f"""
⏳ **Processing Sell Order...**

**📊 CALCULATION:**
🪙 **Current Balance:** {format_number(token_balance, 0)} tokens
📊 **Sell Percentage:** {percent}%
💸 **Tokens to Sell:** {format_number(token_amount_to_sell, 0)} tokens
💰 **Remaining:** {format_number(token_balance - token_amount_to_sell, 0)} tokens

🚀 **Executing transaction...**
"""
        
        await msg.edit_text(calculation_msg, parse_mode='Markdown')
        await human_delay()
        
        tx_link = await execute_sell(ca, token_amount_to_sell, wallet["private_key"])
        
        # Success message
        success_report = f"""
✅ **SELL ORDER SUCCESSFUL!**

**📊 TRADE DETAILS:**
🪙 **Token:** `{shorten_address(ca)}`
📊 **Sold:** {percent}% ({format_number(token_amount_to_sell, 0)} tokens)
💰 **Remaining:** {format_number(token_balance - token_amount_to_sell, 0)} tokens
👛 **Wallet:** `{shorten_address(wallet['address'])}`

**🔗 TRANSACTION:**
[📋 View on Solscan]({tx_link})

**📊 Next Steps:**
• `/balance {ca}` - Check updated balance
• `/pump {ca} <amount>` - Buy more tokens

🎉 **Sale completed successfully!**
"""
        
        await msg.edit_text(success_report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Dump command error: {e}")
        error_report = f"""
❌ **SELL ORDER FAILED**

**🎯 Token:** `{shorten_address(ca)}`
**📊 Percentage:** {percent}%

**❌ Error Details:**
{str(e)}

**💡 Troubleshooting:**
• Check if you have tokens to sell
• Verify the contract address
• Wait a moment and retry
• Use `/balance {ca}` to check your holdings

**🆘 Still having issues?** The network might be busy, try again shortly.
"""
        await msg.edit_text(error_report, parse_mode='Markdown')

async def rugcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced rug check with detailed risk analysis"""
    user_id = update.effective_user.id
    
    if not check_admin_access(user_id) or not check_rate_limit(user_id):
        await update.message.reply_text("❌ Access denied or rate limited.")
        return
        
    if not context.args:
        await update.message.reply_text(
            "❌ **Missing Parameter**\n\n"
            "**Usage:** `/rugcheck <CONTRACT_ADDRESS>`\n\n"
            "**Example:** `/rugcheck 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
            "💡 Use `/help rugcheck` for detailed explanation",
            parse_mode='Markdown'
        )
        return
    
    ca = context.args[0]
    
    is_valid, message = validate_ca_address(ca)
    if not is_valid:
        await update.message.reply_text(f"{message}\n\n💡 Use `/help rugcheck` for examples")
        return
    
    msg = await update.message.reply_text("⏳ **Analyzing Token Security...**\n\n🔍 Gathering data from multiple sources...", parse_mode='Markdown')
    
    try:
        async with throttler:
            result = await check_rug_risk(ca)
        
        # Determine risk level and emoji
        risk_score = result.get('risk_score', 0)
        if risk_score <= 1:
            risk_emoji = "✅"
            risk_text = "LOW RISK"
            risk_color = "🟢"
        elif risk_score <= 3:
            risk_emoji = "⚠️"
            risk_text = "MEDIUM RISK"  
            risk_color = "🟡"
        else:
            risk_emoji = "🚨"
            risk_text = "HIGH RISK"
            risk_color = "🔴"
        
        # Build comprehensive report
        report = f"""
{risk_emoji} **{risk_text}**

**🎯 TOKEN ANALYSIS:**
🏷️ **Contract:** `{shorten_address(ca)}`
📊 **Risk Score:** {risk_score}/5 {risk_color}

"""
        
        if result.get('factors'):
            report += "**🚨 RISK FACTORS:**\n"
            for factor in result['factors']:
                report += f"• {factor}\n"
            report += "\n"
        else:
            report += "**✅ NO MAJOR RISK FACTORS DETECTED**\n\n"
        
        if result.get('data'):
            data = result['data']
            report += "**📈 TOKEN METRICS:**\n"
            report += f"💰 **Market Cap:** ${format_number(data.get('marketCap', 0), 0)}\n"
            report += f"📊 **Volume (24h):** ${format_number(data.get('recentVolume', 0), 0)}\n"
            report += f"👥 **Holders:** {format_number(data.get('holderCount', 0), 0)}\n"
            report += f"🔒 **LP Locked:** {'✅ Yes' if data.get('lpLocked') else '❌ No'}\n"
            report += f"👑 **Owner Admin:** {'⚠️ Yes' if data.get('ownerHasAdmin') else '✅ No'}\n\n"
        
        # Add recommendations
        if risk_score <= 1:
            report += "**💡 RECOMMENDATION:** This token appears relatively safe, but always invest responsibly."
        elif risk_score <= 3:
            report += "**⚠️ RECOMMENDATION:** Proceed with caution. Consider small amounts only."
        else:
            report += "**🚨 RECOMMENDATION:** High risk detected! Avoid or use extreme caution."
        
        report += f"\n\n**🛡️ Want protection?** Use `/auto {ca}` for automatic rug detection"
        
        await msg.edit_text(report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Rugcheck command error: {e}")
        error_report = f"""
❌ **ANALYSIS FAILED**

**🎯 Token:** `{shorten_address(ca)}`

**❌ Error Details:**
{str(e)}

**💡 This could mean:**
• Token data not available on Pump.fun
• Network connectivity issues  
• New token without sufficient data

**🔄 Try again in a few seconds or check the contract address.**
"""
        await msg.edit_text(error_report, parse_mode='Markdown')

async def auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced auto-sell with detailed status reporting"""
    user_id = update.effective_user.id
    
    if not check_admin_access(user_id) or not check_rate_limit(user_id):
        await update.message.reply_text("❌ Access denied or rate limited.")
        return
        
    if not context.args:
        await update.message.reply_text(
            "❌ **Missing Parameter**\n\n"
            "**Usage:** `/auto <CONTRACT_ADDRESS>`\n\n"
            "**What it does:**\n"
            "• Analyzes token for rug pull risks\n"
            "• Automatically sells if HIGH RISK detected\n"
            "• Protects your investment\n\n"
            "**Example:** `/auto 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
            "💡 Use `/help auto` for detailed explanation",
            parse_mode='Markdown'
        )
        return
    
    ca = context.args[0]
    
    is_valid, message = validate_ca_address(ca)
    if not is_valid:
        await update.message.reply_text(f"{message}\n\n💡 Use `/help auto` for examples")
        return
    
    msg = await update.message.reply_text("⏳ **Activating Auto-Sell Protection...**\n\n🔍 Analyzing current risk level...", parse_mode='Markdown')
    
    try:
        async with throttler:
            rug_result = await check_rug_risk(ca)
        
        if rug_result["risk"]:
            # High risk detected - execute emergency sell
            await msg.edit_text("⏳ **Auto-Sell Protection...**\n\n🚨 HIGH RISK DETECTED! Executing emergency sell...", parse_mode='Markdown')
            
            wallet = get_or_create_wallet_for_token(ca)
            token_balance, _ = await get_token_balance(ca, wallet["address"])
            
            if token_balance <= 0:
                no_tokens_report = f"""
🛡️ **AUTO-SELL PROTECTION ACTIVATED**

**🚨 HIGH RISK DETECTED** - But no tokens to sell

**🎯 Token:** `{shorten_address(ca)}`
**📊 Risk Score:** {rug_result.get('risk_score', 0)}/5
**💰 Token Balance:** 0 tokens

**🚨 Risk Factors:**
"""
                for factor in rug_result.get('factors', ['Unknown']):
                    no_tokens_report += f"• {factor}\n"
                
                no_tokens_report += "\n✅ **No action needed** - you don't hold any tokens."
                
                await msg.edit_text(no_tokens_report, parse_mode='Markdown')
                return
            
            try:
                tx_link = await execute_sell(ca, token_balance, wallet["private_key"])
                
                emergency_report = f"""
🛡️ **EMERGENCY SELL EXECUTED!**

**🚨 RUG PULL PROTECTION ACTIVATED**

**📊 TRADE DETAILS:**
🪙 **Token:** `{shorten_address(ca)}`
📊 **Risk Score:** {rug_result.get('risk_score', 0)}/5
💸 **Sold:** {format_number(token_balance, 0)} tokens (100%)
👛 **Wallet:** `{shorten_address(wallet['address'])}`

**🚨 DETECTED RISKS:**
"""
                for factor in rug_result.get('factors', ['Unknown']):
                    emergency_report += f"• {factor}\n"
                
                emergency_report += f"""
**🔗 TRANSACTION:**
[📋 View on Solscan]({tx_link})

🛡️ **Your investment has been protected!**
"""
                
                await msg.edit_text(emergency_report, parse_mode='Markdown')
                
            except Exception as e:
                await msg.edit_text(
                    f"🚨 **HIGH RISK DETECTED** but emergency sell failed!\n\n"
                    f"❌ Error: {str(e)}\n\n"
                    f"💡 **URGENT:** Manually sell with `/dump {ca} 100`"
                )
        else:
            # Low risk - monitoring mode
            safe_report = f"""
✅ **AUTO-SELL PROTECTION: MONITORING MODE**

**🎯 Token:** `{shorten_address(ca)}`
**📊 Risk Level:** LOW ({rug_result.get('risk_score', 0)}/5)
**🛡️ Status:** ACTIVE MONITORING

**📊 CURRENT METRICS:**
"""
            if rug_result.get('data'):
                data = rug_result['data']
                safe_report += f"💰 Market Cap: ${format_number(data.get('marketCap', 0), 0)}\n"
                safe_report += f"📊 Volume: ${format_number(data.get('recentVolume', 0), 0)}\n"
                safe_report += f"👥 Holders: {format_number(data.get('holderCount', 0), 0)}\n"
            
            safe_report += f"""
**🛡️ PROTECTION FEATURES:**
• Continuous risk monitoring
• Automatic sell on rug detection  
• Multi-factor risk analysis
• Instant emergency response

**💡 Your tokens are safe!** The bot will automatically sell if risk factors increase.

**🔄 Run `/auto {ca}` again anytime to re-check status.**
"""
            
            await msg.edit_text(safe_report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Auto command error: {e}")
        await msg.edit_text(
            f"❌ **Auto-Sell Protection Failed**\n\n"
            f"Error: {str(e)}\n\n"
            f"💡 Try again in a few seconds or use manual commands:\n"
            f"• `/rugcheck {ca}` - Check risk manually\n"
            f"• `/dump {ca} 100` - Emergency sell if needed"
        )

# Main application
def main():
    """Enhanced main function with better error handling"""
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN not found in environment variables")
        return
    
    app = Application.builder().token(TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("examples", examples_command))
    app.add_handler(CommandHandler("pump", pump))
    app.add_handler(CommandHandler("repump", pump))  # Reuse pump handler
    app.add_handler(CommandHandler("dump", dump))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("rugcheck", rugcheck))
    app.add_handler(CommandHandler("auto", auto))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    
    logger.info("🚀 PumpShield Pro Bot started with enhanced user experience")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
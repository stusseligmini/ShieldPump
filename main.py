import asyncio
import os
import random
import json
import base64
import struct
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solana.rpc.api import Client
from solana.rpc.types import MemcmpOpts

# 🔑 Last inn .env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
WALLET_FILE = "wallets.json"

# 🌐 RPC-noder
RPC_NODES = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-api.projectserum.com",
    "https://ssc-dao.genesysgo.net",
]

# 🧩 Program ID-er
PUMP_FUN_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")

# 🧠 Hjelpefunksjoner
def load_wallets():
    if not os.path.exists(WALLET_FILE):
        with open(WALLET_FILE, "w") as f:
            json.dump([], f)
    with open(WALLET_FILE, "r") as f:
        return json.load(f)

def save_wallets(wallets):
    with open(WALLET_FILE, "w") as f:
        json.dump(wallets, f, indent=2)

def get_or_create_wallet_for_token(ca):
    wallets = load_wallets()
    for w in wallets:
        if ca in w["used_for"]:
            return w
    kp = Keypair()
    wallet = {
        "address": str(kp.pubkey()),
        "private_key": kp.to_base58_string(),
        "used_for": [ca]
    }
    wallets.append(wallet)
    save_wallets(wallets)
    return wallet

async def human_delay():
    await asyncio.sleep(random.uniform(0.5, 3.0))

def get_random_amount(base):
    return max(0.001, base + random.uniform(-0.02, 0.02))

def get_random_rpc():
    return random.choice(RPC_NODES)

# 🧨 MEV via Jito
async def send_mev_transaction(signed_tx: VersionedTransaction) -> str:
    url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
    raw_tx = bytes(signed_tx)
    encoded = base64.b64encode(raw_tx).decode('utf-8')
    payload = {"jsonrpc": "2.0", "id": 1, "method": "sendBundle", "params": [{"data": [encoded]}]}
    r = requests.post(url, json=payload)
    result = r.json()
    if "error" in result:
        raise Exception(f"Jito: {result['error']}")
    return result["result"]["bundleId"]

# 💰 Buy instruction
def create_buy_ix(buyer: Pubkey, mint: Pubkey, lamports: int):
    disc = struct.pack("<Q", 16927863322537952870)  # global:buy
    amt = struct.pack("<Q", lamports)
    data = disc + amt
    keys = [
        {"pubkey": buyer, "is_signer": True, "is_writable": True},
        {"pubkey": mint, "is_signer": False, "is_writable": True},
        {"pubkey": SYSTEM_PROGRAM_ID, "is_signer": False, "is_writable": False},
    ]
    return {"program_id": PUMP_FUN_PROGRAM_ID, "keys": keys, "data": data}

# 💸 Sell instruction
def create_sell_ix(seller: Pubkey, mint: Pubkey, token_amount: int):
    disc = struct.pack("<Q", 12502976035594553355)  # global:sell
    amt = struct.pack("<Q", token_amount)
    data = disc + amt
    keys = [
        {"pubkey": seller, "is_signer": True, "is_writable": True},
        {"pubkey": mint, "is_signer": False, "is_writable": True},
        {"pubkey": SYSTEM_PROGRAM_ID, "is_signer": False, "is_writable": False},
    ]
    return {"program_id": PUMP_FUN_PROGRAM_ID, "keys": keys, "data": data}

# 🛠️ Execute buy
async def execute_buy(ca: str, sol_amount: float, pk: str, rpc: str) -> str:
    client = Client(rpc)
    buyer = Keypair.from_base58_string(pk)
    mint = Pubkey.from_string(ca)
    lamports = int(sol_amount * 1_000_000_000)
    ix = create_buy_ix(buyer.pubkey(), mint, lamports)
    bh = client.get_latest_blockhash().value.blockhash
    msg = MessageV0.try_compile(payer=buyer.pubkey(), instructions=[ix], address_lookup_table_accounts=[], recent_blockhash=bh)
    tx = VersionedTransaction(msg, [buyer])
    bid = await send_mev_transaction(tx)
    return f"https://solscan.io/tx/{bid}"

# 🛠️ Execute sell
async def execute_sell(ca: str, token_amount: int, pk: str, rpc: str) -> str:
    client = Client(rpc)
    seller = Keypair.from_base58_string(pk)
    mint = Pubkey.from_string(ca)
    ix = create_sell_ix(seller.pubkey(), mint, token_amount)
    bh = client.get_latest_blockhash().value.blockhash
    msg = MessageV0.try_compile(payer=seller.pubkey(), instructions=[ix], address_lookup_table_accounts=[], recent_blockhash=bh)
    tx = VersionedTransaction(msg, [seller])
    bid = await send_mev_transaction(tx)
    return f"https://solscan.io/tx/{bid}"

# 🔍 Get token balance (EKTE)
async def get_token_balance(ca: str, wallet_addr: str, rpc: str) -> int:
    client = Client(rpc)
    mint = Pubkey.from_string(ca)
    wallet = Pubkey.from_string(wallet_addr)
    
    # Finn ATA (Associated Token Account)
    ata = Pubkey.find_program_address(
        [bytes(wallet), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM_ID
    )[0]

    # Hent konto-data
    account_info = client.get_account_info(ata)
    if not account_info.value:
        return 0

    # Token balance er de første 8 bytes (u64, little-endian)
    data = account_info.value.data
    if len(data) < 64:
        return 0
    balance = int.from_bytes(data[:8], "little")
    return balance

# 🚨 Rug-detection via Pump.fun API
def check_rug_risk(ca: str) -> bool:
    try:
        r = requests.get(f"https://api.pump.fun/coins/{ca}")
        if r.status_code != 200:
            return False
        data = r.json()
        # Sjekk LP locked, owner has admin, recent volume
        lp_locked = data.get("lpLocked", False)
        owner_has_admin = data.get("ownerHasAdmin", False)
        recent_volume = data.get("recentVolume", 0)
        return not (lp_locked and not owner_has_admin and recent_volume > 1000)
    except:
        return False

# 📊 Balance command
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Bruk: /balance <CA>")
        return
    ca = context.args[0]
    wallet = get_or_create_wallet_for_token(ca)
    rpc = get_random_rpc()
    try:
        balance = await get_token_balance(ca, wallet["address"], rpc)
        await update.message.reply_text(f"📊 Balanse for {ca}: {balance / 1_000_000_000:.6f} SOL")
    except Exception as e:
        await update.message.reply_text(f"❌ Feil: {str(e)}")

# 🚀 Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 PumpShield Pro — EKTE HANDLER\n\n"
        "/pump <CA> <SOL> → Kjøp\n"
        "/repump <CA> <SOL> → Kjøp MER\n"
        "/dump <CA> <%> → Selg\n"
        "/loop <CA> buy=X sell=Y delay=Z → Automatisk loop\n"
        "/balance <CA> → Sjekk balanse\n"
        "/auto → Aktiver automatisk selg ved rug"
    )

# 🟢 /pump
async def pump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Bruk: /pump <CA> <SOL>")
        return
    ca = context.args[0]
    base = float(context.args[1])
    msg = await update.message.reply_text("⏳ Kjøper EKTE token...")
    await human_delay()
    amt = get_random_amount(base)
    wallet = get_or_create_wallet_for_token(ca)
    rpc = get_random_rpc()
    try:
        tx_link = await execute_buy(ca, amt, wallet["private_key"], rpc)
        await msg.edit_text(f"✅ Kjøpt {amt:.5f} SOL\nWallet: {wallet['address'][:6]}...\nTX: {tx_link}")
    except Exception as e:
        await msg.edit_text(f"❌ Feil: {str(e)}")

# 🔄 /repump
async def repump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Bruk: /repump <CA> <SOL>")
        return
    ca = context.args[0]
    base = float(context.args[1])
    msg = await update.message.reply_text("⏳ Kjøper MER EKTE token...")
    await human_delay()
    amt = get_random_amount(base)
    wallet = get_or_create_wallet_for_token(ca)
    rpc = get_random_rpc()
    try:
        tx_link = await execute_buy(ca, amt, wallet["private_key"], rpc)
        await msg.edit_text(f"✅ Repumpet {amt:.5f} SOL\nWallet: {wallet['address'][:6]}...\nTX: {tx_link}")
    except Exception as e:
        await msg.edit_text(f"❌ Feil: {str(e)}")

# 📉 /dump
async def dump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Bruk: /dump <CA> <%>")
        return
    ca = context.args[0]
    percent = float(context.args[1])
    msg = await update.message.reply_text("⏳ Selger EKTE token...")
    await human_delay()
    wallet = get_or_create_wallet_for_token(ca)
    rpc = get_random_rpc()
    try:
        tx_link = await execute_sell(ca, percent, wallet["private_key"], rpc)
        await msg.edit_text(f"✅ Solgt {percent}%\nWallet: {wallet['address'][:6]}...\nTX: {tx_link}")
    except Exception as e:
        await msg.edit_text(f"❌ Feil: {str(e)}")

# 🔁 /loop
async def loop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Bruk: /loop <CA> buy=X sell=Y delay=Z")
        return

    ca = context.args[0]
    buy_amt = 0.1
    sell_pct = 50.0
    delay_sec = 30.0

    # Parse args
    for arg in context.args[1:]:
        if arg.startswith("buy="):
            buy_amt = float(arg.split("=")[1])
        elif arg.startswith("sell="):
            sell_pct = float(arg.split("=")[1])
        elif arg.startswith("delay="):
            delay_sec = float(arg.split("=")[1])

    await update.message.reply_text(f"🔁 Starter loop for {ca}\nBuy: {buy_amt} SOL\nSell: {sell_pct}%\nDelay: {delay_sec}s")

    wallet = get_or_create_wallet_for_token(ca)

    for i in range(5):  # 5 runder
        try:
            # Kjøp
            await update.message.reply_text(f"🔁 Runde {i+1}: Kjøper {buy_amt} SOL...")
            amt = get_random_amount(buy_amt)
            tx_link = await execute_buy(ca, amt, wallet["private_key"], get_random_rpc())
            await update.message.reply_text(f"✅ Kjøpt → {tx_link}")

            await asyncio.sleep(delay_sec)

            # Selg
            await update.message.reply_text(f"🔁 Runde {i+1}: Selger {sell_pct}%...")
            tx_link = await execute_sell(ca, sell_pct, wallet["private_key"], get_random_rpc())
            await update.message.reply_text(f"✅ Solgt → {tx_link}")

            await asyncio.sleep(delay_sec)

        except Exception as e:
            await update.message.reply_text(f"❌ Loop-feil: {str(e)}")
            break

    await update.message.reply_text("🏁 Loop ferdig.")

# 🚨 /auto
async def auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ca = context.args[0] if context.args else None
    if not ca:
        await update.message.reply_text("Bruk: /auto <CA> → Aktiver automatisk selg ved rug")
        return
    if check_rug_risk(ca):
        await update.message.reply_text(f"🛡️ Rug-fundert! Selger {ca} nå...")
        wallet = get_or_create_wallet_for_token(ca)
        rpc = get_random_rpc()
        try:
            tx_link = await execute_sell(ca, 100, wallet["private_key"], rpc)
            await update.message.reply_text(f"✅ Selgt → {tx_link}")
        except Exception as e:
            await update.message.reply_text(f"❌ Feil: {str(e)}")
    else:
        await update.message.reply_text("🛡️ Ingen rug-tegn. Fortsetter.")

# 🚀 START
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pump", pump))
    app.add_handler(CommandHandler("repump", repump))
    app.add_handler(CommandHandler("dump", dump))
    app.add_handler(CommandHandler("loop", loop_handler))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("auto", auto))
    print("✅ EKTE Bot kjører...")
    app.run_polling()

if __name__ == "__main__":
    main()
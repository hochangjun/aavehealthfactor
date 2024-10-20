import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from web3 import Web3
import json
from dotenv import load_dotenv
import asyncio

# Load environment variables from .env file
load_dotenv()

# Debug: Print environment variables
print("TELEGRAM_BOT_TOKEN:", os.getenv('TELEGRAM_BOT_TOKEN'))
print("ETHEREUM_NODE_URL:", os.getenv('ETHEREUM_NODE_URL'))
print("CHECK_INTERVAL:", os.getenv('CHECK_INTERVAL'))
print("USER_DATA_FILE:", os.getenv('USER_DATA_FILE'))

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load configuration from environment variables
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ETHEREUM_NODE_URL = os.environ.get('ETHEREUM_NODE_URL')
USER_DATA_FILE = os.environ.get('USER_DATA_FILE', 'aavehealthchatids.json')
CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', 3600))  # Default to 1 hour

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(ETHEREUM_NODE_URL))

# AAVE v3 Pool contract address and ABI
AAVE_V3_POOL_ADDRESS = '0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2'
AAVE_V3_POOL_ABI = json.loads('''
[
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "user",
                "type": "address"
            }
        ],
        "name": "getUserAccountData",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "totalCollateralBase",
                "type": "uint256"
            },
            {
                "internalType": "uint256",
                "name": "totalDebtBase",
                "type": "uint256"
            },
            {
                "internalType": "uint256",
                "name": "availableBorrowsBase",
                "type": "uint256"
            },
            {
                "internalType": "uint256",
                "name": "currentLiquidationThreshold",
                "type": "uint256"
            },
            {
                "internalType": "uint256",
                "name": "ltv",
                "type": "uint256"
            },
            {
                "internalType": "uint256",
                "name": "healthFactor",
                "type": "uint256"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    }
]
''')

# Initialize AAVE v3 Pool contract
aave_contract = w3.eth.contract(address=AAVE_V3_POOL_ADDRESS, abi=AAVE_V3_POOL_ABI)

# Load user data from file
def load_user_data():
    try:
        with open(USER_DATA_FILE, 'r') as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
            else:
                return {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Save user data to file
def save_user_data(data):
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(data, f)

# Global variable to store user data
user_data = load_user_data()

# Function to check health factor
def check_health_factor(address):
    try:
        account_data = aave_contract.functions.getUserAccountData(address).call()
        health_factor = account_data[5] / 1e18
        return health_factor
    except Exception as e:
        logger.error(f"Error checking health factor: {e}")
        return None

# Function to handle the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to the AAVE Health Factor Monitor Bot!\n\n"
        "Here are the available commands:\n"
        "/start - Show this help message\n"
        "/monitor <threshold> <address> - Start monitoring an address\n"
        "/check - Check your current monitoring settings\n"
        "/stop - Stop monitoring\n\n"
        "You can also simply paste an Ethereum address to check its current health factor.\n\n"
        "DISCLAIMER: This bot is not officially affiliated with or endorsed by AAVE. "
        "It is an independent tool created for informational purposes only. "
        "The bot is not guaranteed to be always accurate or available. "
        "Users should not rely solely on this bot for making financial decisions."
    )

# Function to handle /monitor command
async def monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /monitor <threshold> <address>")
        return

    chat_id = str(update.effective_chat.id)  # Convert to string for JSON compatibility
    try:
        threshold = float(context.args[0])
        address = context.args[1]
    except ValueError:
        await update.message.reply_text("Invalid threshold. Please enter a number (e.g., 1.5).")
        return

    if not w3.is_address(address):
        await update.message.reply_text("Invalid Ethereum address. Please try again.")
        return

    if chat_id in user_data:
        user_data[chat_id]['threshold'] = threshold
        user_data[chat_id]['address'] = address
        message = f"Updated monitoring for address {address} with new threshold {threshold}"
    else:
        user_data[chat_id] = {'threshold': threshold, 'address': address}
        message = f"Started monitoring address {address} with threshold {threshold}"

    save_user_data(user_data)
    await update.message.reply_text(message)
    await check_and_notify(context, chat_id)

# Function to handle /check command
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if chat_id in user_data:
        threshold = user_data[chat_id]['threshold']
        address = user_data[chat_id]['address']
        health_factor = check_health_factor(address)
        
        if health_factor is not None:
            await update.message.reply_text(
                f"Currently monitoring address {address}\n"
                f"Threshold: {threshold}\n"
                f"Current health factor: {health_factor}"
            )
        else:
            await update.message.reply_text(
                f"Currently monitoring address {address}\n"
                f"Threshold: {threshold}\n"
                f"Unable to fetch current health factor. Please try again later."
            )
    else:
        await update.message.reply_text("You are not currently monitoring any address.")

# Function to handle /stop command
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if chat_id in user_data:
        del user_data[chat_id]
        save_user_data(user_data)
        await update.message.reply_text("Monitoring stopped.")
    else:
        await update.message.reply_text("You were not monitoring any address.")

# Function to handle direct address input
async def handle_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    address = update.message.text.strip()
    if not w3.is_address(address):
        await update.message.reply_text("Invalid Ethereum address. Please try again.")
        return

    health_factor = check_health_factor(address)
    if health_factor is not None:
        await update.message.reply_text(f"Current health factor for {address}: {health_factor}")
    else:
        await update.message.reply_text("Unable to fetch health factor. Please try again later.")
    
    logger.info(f"Health factor check requested for address: {address}")

# Function to check health factor and notify user
async def check_and_notify(context: ContextTypes.DEFAULT_TYPE, chat_id: str) -> None:
    if chat_id not in user_data:
        return

    address = user_data[chat_id]['address']
    threshold = user_data[chat_id]['threshold']
    health_factor = check_health_factor(address)

    if health_factor is not None:
        if health_factor < threshold:
            await context.bot.send_message(
                chat_id=int(chat_id),  # Convert back to int for sending message
                text=f"Alert: Health factor for {address} is {health_factor}, which is below your threshold of {threshold}!\n"
                     f"Check your position on AAVE: https://app.aave.com/"
            )
    else:
        await context.bot.send_message(
            chat_id=int(chat_id),  # Convert back to int for sending message
            text=f"Unable to fetch health factor for {address}. Will try again in the next check."
        )

# Function to periodically check health factors
async def periodic_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    for chat_id in user_data:
        await check_and_notify(context, chat_id)

def main() -> None:
    if not TOKEN:
        logger.error("No bot token provided. Please set the TELEGRAM_BOT_TOKEN environment variable.")
        return

    if not ETHEREUM_NODE_URL:
        logger.error("No Ethereum node URL provided. Please set the ETHEREUM_NODE_URL environment variable.")
        return

    application = Application.builder().token(TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("monitor", monitor))
    application.add_handler(CommandHandler("check", check))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_address))

    # Set up periodic task
    job_queue = application.job_queue
    job_queue.run_repeating(periodic_check, interval=CHECK_INTERVAL, first=5)

    logger.info("Bot started. Polling for updates...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

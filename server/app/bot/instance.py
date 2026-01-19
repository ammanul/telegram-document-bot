from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from server.app.bot.callbacks.handlers import button_callback
from server.app.bot.commands import admin, owner, user
from server.app.config import TELEGRAM_TOKEN

application = Application.builder().token(TELEGRAM_TOKEN).request(HTTPXRequest(read_timeout=600, write_timeout=600, connect_timeout=600, pool_timeout=60, connection_pool_size=10)).build()

# Owner commands
application.add_handler(CommandHandler("set_owner", owner.set_owner))
application.add_handler(CommandHandler("set_admin", owner.set_admin))
application.add_handler(CommandHandler("list_authorized", owner.list_authorized))
application.add_handler(CommandHandler("requests", owner.requests_command))
application.add_handler(CommandHandler("stats", admin.stats))

# User commands
application.add_handler(CommandHandler("start", user.start))
application.add_handler(CommandHandler("done", user.done_uploading))
application.add_handler(CommandHandler("cancel", user.cancel))
application.add_handler(CommandHandler("help", user.help_command))
application.add_handler(MessageHandler(filters.Document.PDF, user.handle_pdf))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user.handle_text_input))

# Callback handlers
application.add_handler(CallbackQueryHandler(button_callback))
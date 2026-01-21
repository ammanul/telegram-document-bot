from telegram import Update
from telegram.ext import ContextTypes

from server.app.services.auth import is_admin, is_owner


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays simplified statistics about the bot's usage.
    """
    if not is_admin(update.effective_user.id) and not is_owner(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return
    from sqlalchemy import select

    from server.app.services.db import get_session
    from server.app.services.db_models import User

    with get_session() as session:
        users = session.execute(select(User)).scalars().all()

    user_stats = []
    total_processed_count = 0

    for user in users:
        count = user.processed_documents_count or 0
        if count > 0:
            user_stats.append({
                "id": user.telegram_id,
                "username": user.username,
                "count": count,
            })
        total_processed_count += count

    sorted_user_stats = sorted(user_stats, key=lambda x: x["count"], reverse=True)

    message = f"*Bot Usage Statistics*\n\n"
    message += f"*Total Processed Documents*: {total_processed_count}\n\n"

    if sorted_user_stats:
        message += "*Processed Documents Per User:*\n"
        for user_info in sorted_user_stats:
            display_name = (
                f"@{user_info['username']}" if user_info.get("username") else f"ID: {user_info['id']}"
            )
            escaped_display_name = display_name.translate(
                str.maketrans({c: f"\\{c}" for c in "_*[]()~`>#+-=|{}.!"})
            )
            message += f"\\- {escaped_display_name}: {user_info['count']}\n"
    else:
        message += r"No documents have been processed yet\."

    await update.message.reply_text(message, parse_mode="MarkdownV2")

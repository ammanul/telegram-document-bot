from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from server.app.services.auth import is_admin, is_owner, set_user_role
from server.app.services.db import get_session
from server.app.services.db_models import PendingGrant, PendingOwnershipTransfer, PendingRequest, User

from server.app.config import TELEGRAM_OWNER_SECRET 


async def set_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sets the user as the owner if they provide the correct password.
    """
    password = " ".join(context.args)

    if not TELEGRAM_OWNER_SECRET:
        await update.message.reply_text("Owner secret is not configured.")
        return

    # Check if an owner already exists
    from sqlalchemy import select

    with get_session() as session:
        existing_owner = (
            session.execute(select(User).where(User.role == "owner"))
            .scalars()
            .first()
        )
    if existing_owner is not None:
        await update.message.reply_text("An owner already exists.")
        return

    if password == TELEGRAM_OWNER_SECRET:
        set_user_role(update.effective_user.id, "owner", update.effective_user.username)
        await update.message.reply_text("You are now the owner.")
    else:
        await update.message.reply_text("Incorrect password.")


async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sets a user as an admin. Only the owner can do this.
    """
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only the owner can perform this action.")
        return

    if not context.args:
        await update.message.reply_text("Please provide a username to set as admin.")
        return

    username = context.args[0]
    if username.startswith('@'):
        username = username[1:]

    from sqlalchemy import select

    with get_session() as session:
        user = (
            session.execute(select(User).where(User.username == username))
            .scalars()
            .first()
        )

    if user is None:
        await update.message.reply_text(f"User @{username} not found.")
        return

    set_user_role(user.telegram_id, "admin", username)
    await update.message.reply_text(f"User @{username} is now an admin.")


async def _get_user_list_markup(bot, requester_id):
    from sqlalchemy import select

    keyboard = []

    requester_is_owner = is_owner(requester_id)

    with get_session() as session:
        users = session.execute(select(User)).scalars().all()

    for user in users:
        user_id = int(user.telegram_id)
        role = user.role

        try:
            chat = await bot.get_chat(user_id)
            username = chat.username or f"ID: {user_id}"
        except Exception as e:
            print(f"Could not fetch chat for user ID {user_id}: {e}")
            username = f"ID: {user_id}"

        row = [InlineKeyboardButton(f"{username} ({role})", callback_data=f"noop:{user_id}")]

        if requester_is_owner and user_id != requester_id:
            if role == "user":
                row.append(InlineKeyboardButton("To Admin", callback_data=f"promote_to_admin:{user_id}"))
            elif role == "admin":
                row.append(InlineKeyboardButton("To User", callback_data=f"demote_to_user:{user_id}"))
            row.append(InlineKeyboardButton("Revoke", callback_data=f"revoke_access:{user_id}"))
        
        keyboard.append(row)

    if requester_is_owner:
        with get_session() as session:
            pending_grants = session.query(PendingGrant).all()
            pending_transfers = session.query(PendingOwnershipTransfer).all()

        for grant in pending_grants:
            keyboard.append([
                InlineKeyboardButton(f"Pending @{grant.username}", callback_data=f"noop:{grant.username}"),
                InlineKeyboardButton("Cancel", callback_data=f"cancel_grant:{grant.username}"),
            ])

        for transfer in pending_transfers:
            keyboard.append([
                InlineKeyboardButton(f"Pending @{transfer.username}", callback_data=f"noop:{transfer.username}"),
                InlineKeyboardButton("Cancel", callback_data=f"cancel_transfer:{transfer.username}"),
            ])

        keyboard.append([InlineKeyboardButton("Grant new access", callback_data="grant_access:prompt")])
        keyboard.append([InlineKeyboardButton("Transfer ownership", callback_data="transfer_ownership:prompt")])

    return InlineKeyboardMarkup(keyboard)


async def list_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Lists all authorized users and admins with options for the owner.
    """
    if not is_admin(update.effective_user.id) and not is_owner(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    reply_markup = await _get_user_list_markup(context.bot, update.effective_user.id)
    if not reply_markup.inline_keyboard:
        await update.message.reply_text("There are no authorized users.")
        return

    await update.message.reply_text("Authorized Users:", reply_markup=reply_markup)


async def requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays a list of pending access requests.
    """
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only the owner can perform this action.")
        return
    from sqlalchemy import select

    keyboard = []
    with get_session() as session:
        requests = session.execute(select(PendingRequest)).scalars().all()

    for req in requests:
        keyboard.append([
            InlineKeyboardButton(f"@{req.username}", callback_data=f"noop:{req.telegram_user_id}"),
            InlineKeyboardButton("Allow", callback_data=f"allow_request:{req.telegram_user_id}"),
            InlineKeyboardButton("Deny", callback_data=f"deny_request:{req.telegram_user_id}"),
        ])

    if not keyboard:
        await update.message.reply_text("There are no pending access requests.")
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Pending Access Requests:", reply_markup=reply_markup)



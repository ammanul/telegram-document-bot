import asyncio
import logging
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TimedOut
from telegram.ext import ContextTypes

from server.app.bot.callbacks.handlers import process_configured_job
from server.app.config import ID_TYPES, MAX_FILES
from server.app.services.auth import grant_access, is_authorized, is_owner, is_admin
from server.app.services.db import get_session
from server.app.services.db_models import PendingOwnershipTransfer, PendingGrant, PendingRequest

logger = logging.getLogger(__name__)


def _parse_multiplier_input(raw_value: str) -> float | None:
    """Convert user-specified multiplier input into a non-negative float."""
    if raw_value is None:
        return 1.0

    value = raw_value.strip().lower()
    if value in {"", "default", "skip"}:
        return 1.0

    try:
        multiplier = float(value)
    except ValueError:
        return None

    if multiplier < 0.0:
        return None
    return multiplier


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends a welcome message to the user and clears any previous session data.
    """
    user = update.effective_user

    # Check for pending ownership transfers
    if user.username:
        with get_session() as session:
            transfer = session.get(PendingOwnershipTransfer, user.username)
            if transfer:
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "Confirm",
                            callback_data=f"confirm_ownership:{user.id}",
                        ),
                        InlineKeyboardButton(
                            "Deny",
                            callback_data=f"deny_ownership:{user.id}",
                        ),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    "An ownership transfer has been initiated to you. Do you want to accept?",
                    reply_markup=reply_markup,
                )
                return

    # Check for pending grants
    if user.username:
        with get_session() as session:
            grant = session.get(PendingGrant, user.username)
            if grant:
                grant_access(user.id, user.username)
                session.delete(grant)
                session.commit()
                await update.message.reply_text("You have been granted access to the bot.")

    if not is_authorized(user.id):
        keyboard = [[InlineKeyboardButton("Request Access", callback_data="request_access")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("You are not authorized to use this bot.", reply_markup=reply_markup)
        return

    context.user_data.clear()
    await update.message.reply_text(
        f"Welcome, {user.first_name}!\n\n"
        f"I can help you format your ID documents. Just upload up to {MAX_FILES} files at a time. "
        "When you're finished, you can either wait for 30 seconds or simply send /done to continue.\n\n"
        "If you need to begin again, just send /cancel."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /cancel command to clear the current batch and state.
    """
    chat_id = update.effective_chat.id

    # Remove any scheduled configuration job
    if context.user_data.get("config_job_scheduled"):
        scheduled_jobs = context.job_queue.get_jobs_by_name(f"config_job_{chat_id}")
        for job in scheduled_jobs:
            job.schedule_removal()

    # Clear all user data for the session
    context.user_data.clear()

    await delete_upload_message(context, chat_id)
    await delete_config_message(context, chat_id)

    await update.message.reply_text(
        "The current batch has been canceled. You can now start over by sending new files."
    )


async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles PDF uploads, collects them in a batch, and resets a 30-second timeout.
    The timeout is reset on each new file upload, starting from the last file's timestamp.
    """
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("You are not authorized to upload files.")
        return

    doc = update.message.document
    chat_id = update.effective_chat.id
    context.user_data["chat_id"] = chat_id

    if "pending_files" not in context.user_data:
        context.user_data["pending_files"] = []

    if len(context.user_data["pending_files"]) >= MAX_FILES:
        await update.message.reply_text(
            f"You've reached the {MAX_FILES}-file limit for this batch. To proceed with the current files, please send /done, or to start over, send /cancel."
        )
        return

    if not doc or "pdf" not in (doc.mime_type or ""):
        await update.message.reply_text(
            "This file is not valid. Please upload a PDF document."
        )
        return

    # Add a short delay before pulling the file from Telegram to stagger bursts of uploads.
    await asyncio.sleep(1.5)

    # Use the application's HTTPXRequest timeouts (configured globally) and
    # avoid adding shorter per-call timeouts here so large files have more
    # time to transfer.
    file = await doc.get_file()

    context.user_data["pending_files"].append(
        {"file_name": doc.file_name, "file_id": doc.file_id}
    )

    num_files = len(context.user_data["pending_files"])
    message_text = f"Received: {doc.file_name} ({num_files} of {MAX_FILES} files in this batch)"

    await delete_upload_message(context, chat_id)

    message = await update.message.reply_text(message_text)
    context.user_data["upload_message_id"] = message.message_id

    # If a timeout job is already scheduled, remove it to reset the timer.
    if context.user_data.get("config_job_scheduled"):
        scheduled_jobs = context.job_queue.get_jobs_by_name(f"config_job_{chat_id}")
        for job in scheduled_jobs:
            job.schedule_removal()

    # Schedule a new job to run in 30 seconds from now.
    # We store the current time to ensure only the latest job triggers configuration.
    last_upload_timestamp = time.time()
    context.job_queue.run_once(
        ask_for_configuration,
        when=30,
        chat_id=chat_id,
        name=f"config_job_{chat_id}",
        data={"timestamp": last_upload_timestamp},
    )
    context.user_data["config_job_scheduled"] = True
    context.user_data["last_upload_timestamp"] = last_upload_timestamp


async def done_uploading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /done command to manually finish the batch upload process.
    """
    chat_id = update.effective_chat.id

    if context.user_data.get("config_job_scheduled"):
        scheduled_jobs = context.job_queue.get_jobs_by_name(f"config_job_{chat_id}")
        for job in scheduled_jobs:
            job.schedule_removal()
        context.user_data["config_job_scheduled"] = False

    await start_configuration_flow(context, chat_id)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles text input from the user and routes it to the appropriate handler based on user state.
    """
    chat_id = update.effective_chat.id

    if context.user_data.get('awaiting_brightness_input'):
        multiplier = _parse_multiplier_input(update.message.text)
        if multiplier is None:
            await update.message.reply_text(
                "Brightness must be a non-negative number. Please try again (e.g., 1.0)."
            )
            return

        context.user_data['brightness'] = multiplier
        context.user_data.pop('awaiting_brightness_input', None)
        context.user_data['awaiting_saturation_input'] = True
        await update.message.reply_text(
            "Brightness saved. Enter a saturation multiplier (e.g., 1.0) or send 'default' to keep original colors."
        )
        return

    if context.user_data.get('awaiting_saturation_input'):
        multiplier = _parse_multiplier_input(update.message.text)
        if multiplier is None:
            await update.message.reply_text(
                "Saturation must be a non-negative number. Please try again (e.g., 1.0)."
            )
            return

        context.user_data['saturation'] = multiplier
        context.user_data.pop('awaiting_saturation_input', None)
        await update.message.reply_text("Thanks! Starting processing with your adjustments.")
        await process_configured_job(context, update.message, chat_id, update.effective_user)
        return

    if context.user_data.get('awaiting_username_for_grant'):
        if not is_owner(update.effective_user.id):
            await update.message.reply_text("Only the owner can perform this action.")
            return

        username = update.message.text.strip()
        if username.startswith('@'):
            username = username[1:]

        from sqlalchemy import select

        with get_session() as session:
            pending_req = (
                session.execute(
                    select(PendingRequest).where(PendingRequest.username == username)
                )
                .scalars()
                .first()
            )

            if pending_req:
                grant_access(int(pending_req.telegram_user_id), username)
                session.delete(pending_req)
                session.commit()
                context.user_data.pop('awaiting_username_for_grant', None)
                await update.message.reply_text(f"Access granted to @{username}.")
            else:
                if not session.get(PendingGrant, username):
                    session.add(PendingGrant(username=username))
                    session.commit()
                context.user_data.pop('awaiting_username_for_grant', None)
                await update.message.reply_text(f"An invitation has been sent to @{username}. They need to start the bot to claim it.")

    elif context.user_data.get('awaiting_username_for_ownership_transfer'):
        if not is_owner(update.effective_user.id):
            await update.message.reply_text("Only the owner can perform this action.")
            return

        username = update.message.text.strip()
        if username.startswith('@'):
            username = username[1:]

        with get_session() as session:
            transfer = session.get(PendingOwnershipTransfer, username)
            if transfer is None:
                transfer = PendingOwnershipTransfer(
                    username=username,
                    from_user_id=update.effective_user.id,
                )
                session.add(transfer)
            else:
                transfer.from_user_id = update.effective_user.id
            session.commit()
        context.user_data.pop('awaiting_username_for_ownership_transfer', None)

        await update.message.reply_text(f"Ownership transfer initiated to @{username}. They need to start the bot to confirm.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays a list of available commands.
    """
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    is_user_owner = is_owner(user_id)
    is_user_admin = is_admin(user_id)

    message = "*Available Commands*\n\n"

    if is_user_owner:
        message += "*Owner Commands:*\n"
        message += "/set\\_owner password - Sets the first owner of the bot.\n"
        message += "/set\\_admin username - Promotes a user to admin.\n"
        message += "/transfer\\_ownership username - Initiates the ownership transfer process.\n"
        message += "/list\\_authorized - Lists all users and their roles.\n"
        message += "/requests - Lists all pending access requests.\n"
        message += "/stats - Displays statistics about the bot's usage.\n\n"
    elif is_user_admin:
        message += "*Admin Commands:*\n"
        message += "/list\\_authorized - Lists all users and their roles.\n"
        message += "/stats - Displays statistics about the bot's usage.\n\n"

    message += "*User Commands:*\n"
    message += "/start - Starts the bot and checks for authorization.\n"
    message += "/done - Finishes a batch upload.\n"
    message += "/cancel - Cancels the current batch upload.\n"
    message += "/help - Displays this help message.\n"

    await update.message.reply_text(message, parse_mode="Markdown")


async def ask_for_configuration(context: ContextTypes.DEFAULT_TYPE):
    """
    A wrapper function called by the job queue scheduler on timeout.
    It checks if the timeout is based on the last known upload to prevent stale jobs.
    """
    chat_id = context.job.chat_id
    job_timestamp = context.job.data.get("timestamp")
    user_data = context.application.user_data.get(chat_id, {})
    last_upload_timestamp = user_data.get("last_upload_timestamp")

    if job_timestamp and last_upload_timestamp and job_timestamp == last_upload_timestamp:
        await start_configuration_flow(context, chat_id)
    else:
        print(f"Ignoring stale configuration job for chat {chat_id}")


async def start_configuration_flow(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """
    Initiates the configuration process for a batch of files.
    """
    user_data = context.application.user_data.get(chat_id, {})
    pending_files = user_data.get("pending_files", [])

    if not pending_files:
        await context.bot.send_message(
            chat_id=chat_id,
            text="There are no files to process. Please upload your PDF documents first.",
        )
        return

    await delete_upload_message(context, chat_id)

    num_files = len(pending_files)
    config_message = await context.bot.send_message(
        chat_id=chat_id,
        text=f"{num_files} files uploaded."
    )
    user_data["config_message_id"] = config_message.message_id

    keyboard = [
        [InlineKeyboardButton(id_type.capitalize(), callback_data=f"id_type:{id_type}") for id_type in ID_TYPES],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel:cancel_batch")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text="Select the ID type for this batch:",
        reply_markup=reply_markup,
    )

    user_data.pop("config_job_scheduled", None)
    user_data.pop("last_upload_timestamp", None)


async def delete_upload_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """
    Deletes the 'upload status' message if it exists.
    """
    if "upload_message_id" in context.user_data:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=context.user_data["upload_message_id"],
            )
        except Exception as e:
            print(f"Failed to delete message: {e}")
        finally:
            context.user_data.pop("upload_message_id", None)


async def delete_config_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """
    Deletes the 'config' message if it exists.
    """
    if "config_message_id" in context.user_data:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=context.user_data["config_message_id"],
            )
        except Exception as e:
            print(f"Failed to delete message: {e}")
        finally:
            context.user_data.pop("config_message_id", None)

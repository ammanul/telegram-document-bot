import asyncio
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TimedOut
from telegram.ext import ContextTypes

from server.app.bot.commands.owner import _get_user_list_markup
from server.app.services.auth import grant_access, is_admin, is_owner, revoke_access, set_user_role
from server.app.services.pubsub import publish_job
from server.app.services.db import get_session
from server.app.services.db_models import PendingGrant, PendingOwnershipTransfer, PendingRequest, Job, JobFile, User


logger = logging.getLogger(__name__)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Parses the CallbackQuery, guides the user through configuration,
    and dispatches the batch job for processing.
    """
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    await delete_config_message(context, chat_id)

    if query.data == "request_access":
        user = query.from_user
        with get_session() as session:
            existing = (
                session.query(PendingRequest)
                .filter(PendingRequest.telegram_user_id == user.id)
                .first()
            )
            if not existing:
                session.add(
                    PendingRequest(
                        telegram_user_id=user.id,
                        username=user.username or "",
                    )
                )
                session.commit()
        await query.edit_message_text("Your request has been sent to the owner.")
        return

    action, value = query.data.split(":", 1)
    logger.info(f"Button clicked: action={action}, value={value}")

    if action == "noop":
        return

    if action == "request_access":
        user = query.from_user
        with get_session() as session:
            existing = (
                session.query(PendingRequest)
                .filter(PendingRequest.telegram_user_id == user.id)
                .first()
            )
            if not existing:
                session.add(
                    PendingRequest(
                        telegram_user_id=user.id,
                        username=user.username or "",
                    )
                )
                session.commit()
    if action == "allow_request":
        if not is_owner(query.from_user.id):
            await query.answer("Only the owner can perform this action.", show_alert=True)
            return

        user_id_to_allow = int(value)
        username = None
        with get_session() as session:
            pending = (
                session.query(PendingRequest)
                .filter(PendingRequest.telegram_user_id == user_id_to_allow)
                .first()
            )
            if pending:
                username = pending.username
                session.delete(pending)
                session.commit()
        grant_access(user_id_to_allow, username)
        await query.answer(f"User {user_id_to_allow} has been granted access.")
        new_markup = await _get_user_list_markup(context.bot, query.from_user.id)
        if new_markup:
            try:
                await query.edit_message_text("Pending Access Requests:", reply_markup=new_markup)
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating user list: {e}")

    if action == "deny_request":
        if not is_owner(query.from_user.id):
            await query.answer("Only the owner can perform this action.", show_alert=True)
            return

        user_id_to_deny = int(value)
        with get_session() as session:
            pending = (
                session.query(PendingRequest)
                .filter(PendingRequest.telegram_user_id == user_id_to_deny)
                .first()
            )
            if pending:
                session.delete(pending)
                session.commit()
        await query.answer(f"User {user_id_to_deny} has been denied access.")
        new_markup = await _get_user_list_markup(context.bot, query.from_user.id)
        if new_markup:
            try:
                await query.edit_message_text("Pending Access Requests:", reply_markup=new_markup)
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating user list: {e}")

    if action == "cancel_grant":
        if not is_owner(query.from_user.id):
            await query.answer("Only the owner can perform this action.", show_alert=True)
            return

        username_to_cancel = value
        with get_session() as session:
            grant = session.get(PendingGrant, username_to_cancel)
            if grant:
                session.delete(grant)
                session.commit()
        await query.answer(f"Grant for @{username_to_cancel} canceled.")
        # Refresh the list
        new_markup = await _get_user_list_markup(context.bot, query.from_user.id)
        if new_markup:
            try:
                await query.edit_message_text("Authorized Users:", reply_markup=new_markup)
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating user list: {e}")

    if action == "cancel_transfer":
        if not is_owner(query.from_user.id):
            await query.answer("Only the owner can perform this action.", show_alert=True)
            return

        username_to_cancel = value
        with get_session() as session:
            transfer = session.get(PendingOwnershipTransfer, username_to_cancel)
            if transfer:
                session.delete(transfer)
                session.commit()
        new_markup = await _get_user_list_markup(context.bot, query.from_user.id)
        if new_markup:
            try:
                await query.edit_message_text("Authorized Users:", reply_markup=new_markup)
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating user list: {e}")

    if action == "confirm_ownership":
        user_id = int(value)
        with get_session() as session:
            transfer = session.get(PendingOwnershipTransfer, query.from_user.username)
            if transfer:
                from_user_id = transfer.from_user_id
                set_user_role(from_user_id, "admin")
                set_user_role(user_id, "owner", query.from_user.username)
                session.delete(transfer)
                session.commit()
                await query.edit_message_text("Ownership transfer complete. You are now the owner.")
            else:
                await query.edit_message_text("This ownership transfer is no longer valid.")

    if action == "deny_ownership":
        user_id = int(value)
        with get_session() as session:
            transfer = session.get(PendingOwnershipTransfer, query.from_user.username)
            if transfer:
                session.delete(transfer)
                session.commit()
        await query.edit_message_text("You have denied the ownership transfer.")

    if action == "promote_to_admin":
        if not is_owner(query.from_user.id):
            await query.answer("Only the owner can perform this action.", show_alert=True)
            return

        user_id_to_promote = int(value)
        set_user_role(user_id_to_promote, "admin")
        new_markup = await _get_user_list_markup(context.bot, query.from_user.id)
        if new_markup:
            try:
                await query.edit_message_text("Authorized Users:", reply_markup=new_markup)
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating user list: {e}")

    if action == "demote_to_user":
        if not is_owner(query.from_user.id):
            await query.answer("Only the owner can perform this action.", show_alert=True)
            return

        user_id_to_demote = int(value)
        set_user_role(user_id_to_demote, "user")
        await query.answer(f"User demoted to user.")
        # Refresh the list
        new_markup = await _get_user_list_markup(context.bot, query.from_user.id)
        if new_markup:
            try:
                await query.edit_message_text("Authorized Users:", reply_markup=new_markup)
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating user list: {e}")

    if action == "transfer_ownership" and value == "prompt":
        if not is_owner(query.from_user.id):
            await query.answer("Only the owner can perform this action.", show_alert=True)
            return

        context.user_data['awaiting_username_for_ownership_transfer'] = True
        await query.edit_message_text("Please send the username of the user you want to transfer ownership to.")

    if action == "grant_access" and value == "prompt":
        if not is_owner(query.from_user.id):
            await query.answer("Only the owner can perform this action.", show_alert=True)
            return

        context.user_data['awaiting_username_for_grant'] = True
        await query.edit_message_text("Please send the username of the user you want to grant access to.")

    if action == "revoke_access":
        if not is_owner(query.from_user.id):
            await query.answer("Only the owner can perform this action.", show_alert=True)
            return

        user_id_to_revoke = int(value)
        revoke_access(user_id_to_revoke)

        new_markup = await _get_user_list_markup(context.bot, query.from_user.id)
        if new_markup:
            try:
                await query.edit_message_text(
                    "Authorized Users:",
                    reply_markup=new_markup
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating user list: {e}")
        else:
            await query.edit_message_text("All users have been revoked.")

        await query.answer(f"Access revoked.")

    if action == "cancel":
        await delete_upload_message(context, chat_id)
        context.user_data.clear()
        await query.edit_message_text(
            text="Configuration canceled. Feel free to start a new upload."
        )
        logger.info("Batch configuration canceled.")
        return

    context.user_data[action] = value

    if action == "id_type":
        logger.info(f"ID type selected: {value}")
        keyboard = [
            [
                InlineKeyboardButton("PDF", callback_data="format:pdf"),
                InlineKeyboardButton("DOCX", callback_data="format:docx"),
                InlineKeyboardButton("PPT", callback_data="format:pptx"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel:cancel_batch")],
        ]
        await query.edit_message_text(
            "Select the output format:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "format":
        logger.info(f"Output format selected: {value}")
        keyboard = [
            [
                InlineKeyboardButton("Yes", callback_data="grayscale:true"),
                InlineKeyboardButton("No", callback_data="grayscale:false"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel:cancel_batch")],
        ]
        await query.edit_message_text(
            "Apply grayscale to photos?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "grayscale":
        logger.info(f"Grayscale selected: {value}")
        keyboard = [
            [
                InlineKeyboardButton("Yes", callback_data="mirror:true"),
                InlineKeyboardButton("No", callback_data="mirror:false"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel:cancel_batch")],
        ]
        await query.edit_message_text(
            "Mirror the image?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "mirror":
        logger.info(f"Mirror selected: {value}")
        context.user_data.pop("brightness", None)
        context.user_data.pop("saturation", None)
        context.user_data["awaiting_brightness_input"] = True
        context.user_data.pop("awaiting_saturation_input", None)
        await query.edit_message_text(
            text=(
                "Please enter a brightness multiplier (e.g., 1.0). "
                "Send 'default' or 'skip' to keep the original brightness."
            ),
        )
        return


async def process_configured_job(
    context: ContextTypes.DEFAULT_TYPE,
    message,
    chat_id: int,
    user,
):
    """Finalize configuration and publish the processing job."""
    pending_files = context.user_data.get("pending_files", [])
    id_type = context.user_data.get("id_type")
    output_format = context.user_data.get("format")
    grayscale = context.user_data.get("grayscale") == "true"
    mirror = context.user_data.get("mirror") == "true"
    user_id = getattr(user, "id", None)
    username = getattr(user, "username", None)
    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    user_full_name = f"{first_name} {last_name}".strip() or None

    def escape_markdown_v2(text):
        if not text:
            return ""
        escape_chars = "_*[]()~`>#+-=|{}.!"
        return "".join(f"\\{char}" if char in escape_chars else char for char in text)

    try:
        brightness = float(context.user_data.get("brightness", 1.0))
        if brightness < 0.0:
            brightness = 1.0
    except (TypeError, ValueError):
        brightness = 1.0

    try:
        saturation = float(context.user_data.get("saturation", 1.0))
        if saturation < 0.0:
            saturation = 1.0
    except (TypeError, ValueError):
        saturation = 1.0

    if not all([pending_files, id_type, output_format]):
        logger.warning(f"Incomplete configuration: {context.user_data}")
        await message.reply_text(
            "Something went wrong with the configuration. Please start over."
        )
        return

    logger.info(
        "Starting job with %s files. Brightness=%s, Saturation=%s",
        len(pending_files),
        brightness,
        saturation,
    )

    status_message = None
    try:
        status_message = await message.reply_text("Queuing your files for processing...")
    except Exception as exc:
        logger.warning("Failed to send queueing status message: %s", exc)

    try:
        # Create job and job file records in Postgres and attach job_id to the payload.
        import uuid
        from sqlalchemy import select

        job_id = uuid.uuid4()

        with get_session() as session:
            user_obj = (
                session.execute(
                    select(User).where(User.telegram_id == user_id)
                )
                .scalars()
                .first()
            )
            if user_obj is None and user_id is not None:
                user_obj = User(telegram_id=user_id, username=username or None, role="user")
                session.add(user_obj)
                session.flush()

            job = Job(
                id=job_id,
                user_id=user_obj.id if user_obj else None,
                telegram_user_id=user_id,
                chat_id=chat_id,
                status="queued",
                id_type=id_type,
                output_format=output_format,
                grayscale=grayscale,
                mirror=mirror,
                brightness=brightness,
                saturation=saturation,
            )
            session.add(job)
            session.flush()

            for index, f in enumerate(pending_files):
                session.add(
                    JobFile(
                        job_id=job.id,
                        telegram_file_id=f.get("file_id"),
                        file_name=f.get("file_name"),
                        index_in_job=index,
                    )
                )

            session.commit()

        job_data = {
            "job_id": str(job_id),
            "chat_id": chat_id,
            "id_type": id_type,
            "output_format": output_format,
            "grayscale": grayscale,
            "mirror": mirror,
            "brightness": brightness,
            "saturation": saturation,
            "files": pending_files,
            "user_id": user_id,
            "username": username,
            "user_full_name": user_full_name,
        }

        await publish_job(job_data)
        logger.info("Job published to Pub/Sub.")
        if status_message:
            await status_message.edit_text("Processing job...")

    except Exception as e:
        logger.error(f"Failed to queue job: {e}")
        await message.reply_text(
            "Something went wrong while processing your request. Please try again."
        )
    finally:
        context.user_data.clear()


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

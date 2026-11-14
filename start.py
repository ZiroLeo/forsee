
import logging
import re
from html import escape

from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from database import (
    create_or_update_user,
    set_referral,
    get_user,
    is_banned,
    record_user_activity,
    log_event,
)

from rich import premium_emoji, build_rich_message
from keyboards import main_menu_rich_message
from utils import rate_limiter


logger = logging.getLogger(__name__)
router = Router(name="start")


# ============================================================
# REFERRAL VALIDATION
# ============================================================

REFERRAL_PATTERN = re.compile(r"^REF_(\d{5,15})$")


def extract_referrer_id(payload: str, user_id: int):
    """اعتبارسنجی کد رفرال و جلوگیری از رفرال به خود."""

    match = REFERRAL_PATTERN.fullmatch(payload or "")

    if not match:
        return None

    try:
        referrer_id = int(match.group(1))

        if referrer_id == user_id:
            return None

        return referrer_id

    except (ValueError, TypeError):
        return None


# ============================================================
# MAIN MENU
# ============================================================

def create_main_menu_message(first_name: str = None):
    """ساخت پیام خوشامدگویی و منوی اصلی Rich."""

    safe_name = escape(
        (first_name or "دوست عزیز").strip()
    )

    welcome_text = (
        f"{premium_emoji('gram', '●')} "
        f"<b>{safe_name}</b> "
        "به آی‌من نتورک خوش اومدی! "
        f"{premium_emoji('shop', '●')}"
        "\n\n"
        "از منوی زیر می‌تونی خدمات موردنظرت رو انتخاب کنی:"
    )

    return build_rich_message(
        html_text=welcome_text,
        button_rows=main_menu_rich_message()
    )


async def send_main_menu(message: Message):
    """ارسال منوی اصلی به‌صورت پیام جدید."""

    user = message.from_user

    first_name = (
        user.first_name
        if user and user.first_name
        else None
    )

    rich_message = create_main_menu_message(first_name)

    return await message.answer_rich(
        rich_message=rich_message
    )


# ============================================================
# USER REGISTRATION
# ============================================================

def register_user(message: Message):
    """ثبت یا به‌روزرسانی اطلاعات کاربر."""

    user = message.from_user

    if not user:
        return False

    return create_or_update_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name
    )


# ============================================================
# COMMON START PROCESS
# ============================================================

async def process_start(
    message: Message,
    referral_payload: str = None
):
    user = message.from_user

    if not user:
        return

    # بررسی مسدود بودن کاربر
    if is_banned(user.id):
        await message.answer(
            f"{premium_emoji('warning', '!')} "
            "<b>دسترسی شما به ربات مسدود شده است.</b>"
        )
        return

    # محدودیت درخواست
    if not rate_limiter.is_allowed(user.id):
        await message.answer(
            "لطفاً کمی صبر کنید و دوباره تلاش کنید."
        )
        return

    try:
        # ثبت یا به‌روزرسانی کاربر
        is_new = register_user(message)

        # پردازش رفرال فقط برای کاربر جدید
        if is_new and referral_payload:

            referrer_id = extract_referrer_id(
                referral_payload,
                user.id
            )

            if referrer_id:

                try:
                    referrer = get_user(referrer_id)

                    if referrer:
                        registered = set_referral(
                            referrer_id,
                            user.id
                        )

                        if registered:
                            logger.info(
                                "Referral registered: %s -> %s",
                                referrer_id,
                                user.id
                            )

                            log_event(
                                "INFO",
                                "referral_registered",
                                user.id,
                                f"Direct referrer: {referrer_id}"
                            )

                    else:
                        logger.warning(
                            "Referral ignored: referrer %s does not exist.",
                            referrer_id
                        )

                except Exception:
                    logger.exception(
                        "Referral registration failed for user %s",
                        user.id
                    )

        # ثبت فعالیت
        record_user_activity(user.id)

        # ارسال پیام جدید منوی اصلی
        await send_main_menu(message)

        logger.info(
            "Main menu sent to user %s",
            user.id
        )

    except Exception:
        logger.exception(
            "Failed to process start for user %s",
            user.id
        )

        await message.answer(
            "خطا در راه‌اندازی ربات رخ داد. لطفاً دوباره /start را بزنید."
        )


# ============================================================
# /START WITH REFERRAL
# ============================================================

@router.message(CommandStart(deep_link=True))
async def cmd_start_with_referral(
    message: Message,
    command: CommandObject
):
    await process_start(
        message,
        referral_payload=command.args
    )


# ============================================================
# /START WITHOUT REFERRAL
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message):
    await process_start(message)


# ============================================================
# RETURN TO MAIN MENU
# ============================================================

@router.callback_query(F.data == "menu:main")
async def callback_main_menu(callback: CallbackQuery):

    user = callback.from_user

    if not user:
        await callback.answer()
        return

    # بررسی مسدود بودن کاربر
    if is_banned(user.id):
        await callback.answer(
            "دسترسی شما به ربات مسدود شده است.",
            show_alert=True
        )
        return

    if not isinstance(callback.message, Message):
        await callback.answer(
            "امکان نمایش منوی اصلی وجود ندارد.",
            show_alert=True
        )
        return

    try:
        # ثبت فعالیت
        record_user_activity(user.id)

        # ساخت منوی جدید با نام کاربر
        rich_message = create_main_menu_message(
            user.first_name
        )

        # ارسال پیام جدید؛ پیام قبلی دست‌نخورده می‌ماند.
        await callback.message.answer_rich(
            rich_message=rich_message
        )

        await callback.answer()

        logger.info(
            "New main menu message sent to user %s",
            user.id
        )

    except TelegramBadRequest:
        logger.exception(
            "Telegram rejected main menu message for user %s",
            user.id
        )

        await callback.answer(
            "خطا در ارسال منوی اصلی.",
            show_alert=True
        )

    except Exception:
        logger.exception(
            "Failed to send main menu to user %s",
            user.id
        )

        await callback.answer(
            "خطای غیرمنتظره در ارسال منوی اصلی.",
            show_alert=True
        )

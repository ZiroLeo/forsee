
import logging
from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.types import CallbackQuery

from database import get_setting, record_user_activity
from rich import (
    build_rich_message,
    premium_emoji,
    build_button_row,
    build_button,
)
from utils import rate_limiter

logger = logging.getLogger(__name__)
router = Router(name="guide")


# ============================================================
# تنظیمات و ابزارها
# ============================================================

DEFAULT_GUIDE_URL = "https://t.me/YourChannel"


def _get_valid_guide_url() -> str | None:
    """
    دریافت و اعتبارسنجی لینک آموزش از دیتابیس.
    فقط لینک‌های HTTP و HTTPS پذیرفته می‌شوند.
    """

    try:
        url = get_setting(
            "guide_url",
            DEFAULT_GUIDE_URL,
        )

        if not isinstance(url, str):
            return None

        url = url.strip()

        if not url:
            return None

        parsed = urlparse(url)

        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
        ):
            return None

        return url

    except Exception:
        logger.exception("Failed to retrieve guide URL.")
        return None


# ============================================================
# صفحه آموزش
# ============================================================

@router.callback_query(F.data == "menu:guide")
async def show_guide(callback: CallbackQuery):

    user = callback.from_user

    if not user:
        await callback.answer()
        return

    if not rate_limiter.is_allowed(user.id):
        await callback.answer(
            "لطفاً کمی صبر کنید.",
            show_alert=True,
        )
        return

    try:
        record_user_activity(user.id)

        guide_url = _get_valid_guide_url()

        if not guide_url:
            text = (
                f"{premium_emoji('warning', '●')} "
                "<b>آموزش در دسترس نیست</b>\n\n"
                "لینک آموزش هنوز تنظیم نشده است. "
                "لطفاً بعداً دوباره تلاش کنید."
            )

            buttons = [
                build_button_row([
                    build_button(
                        "بازگشت به منوی اصلی",
                        callback_data="menu:main",
                        style="danger",
                        premium_emoji_key="back",
                    ),
                ])
            ]

        else:
            text = (
                f"{premium_emoji('quest', '●')} "
                "<b>آموزش دریافت و نصب اپلیکیشن</b>\n\n"

                "برای استفاده از سرویس آی‌من نتورک، "
                "مراحل دریافت، نصب و راه‌اندازی اپلیکیشن "
                "را در آموزش زیر مشاهده کنید.\n\n"

                "<b>راهنمای شروع:</b>\n"
                "۱. مشاهده آموزش نصب\n"
                "۲. دریافت لینک یا فایل کانفیگ\n"
                "۳. وارد کردن کانفیگ در اپلیکیشن\n"
                "۴. اتصال به سرویس"
            )

            buttons = [
                build_button_row([
                    build_button(
                        "مشاهده آموزش",
                        url=guide_url,
                        style="primary",
                        premium_emoji_key="quest",
                    ),
                ]),
                build_button_row([
                    build_button(
                        "بازگشت به منوی اصلی",
                        callback_data="menu:main",
                        style="danger",
                        premium_emoji_key="back",
                    ),
                ]),
            ]

        rich = build_rich_message(
            text,
            buttons,
        )

        await callback.message.edit_text(
            rich_message=rich,
        )

        await callback.answer()

    except Exception:
        logger.exception(
            "Failed to show guide for user %s",
            user.id,
        )

        await callback.answer(
            "خطا در نمایش صفحه آموزش.",
            show_alert=True,
        )

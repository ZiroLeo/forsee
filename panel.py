
import logging

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command

from config import ADMIN_ID
from database import log_event
from utils import rate_limiter


logger = logging.getLogger(__name__)
router = Router(name="admin_panel")


# ============================================================
# کیبورد اصلی پنل ادمین
# ============================================================

def admin_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 بستن فروش",
                    callback_data="admin:sales:close"
                ),
                InlineKeyboardButton(
                    text="🟢 باز کردن فروش",
                    callback_data="admin:sales:open"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💰 تغییر قیمت",
                    callback_data="admin:prices:menu"
                ),
                InlineKeyboardButton(
                    text="🛍 محصولات",
                    callback_data="admin:products:menu"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎁 کد تخفیف",
                    callback_data="admin:discounts:menu"
                ),
                InlineKeyboardButton(
                    text="🌐 مدیریت سرویس‌ها",
                    callback_data="admin:services:menu"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 مدیریت کاربران",
                    callback_data="admin:users:menu"
                ),
                InlineKeyboardButton(
                    text="📋 لیست کاربران",
                    callback_data="admin:users_list:menu"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📨 ارسال پیام",
                    callback_data="admin:broadcast:menu"
                ),
                InlineKeyboardButton(
                    text="💾 بک‌آپ گرفتن",
                    callback_data="admin:backup:menu"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 آمار",
                    callback_data="admin:stats:menu"
                ),
                InlineKeyboardButton(
                    text="🧪 تست پنل",
                    callback_data="admin:test_panel:menu"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔗 لینک‌ها",
                    callback_data="admin:links:menu"
                ),
                InlineKeyboardButton(
                    text="🧾 ادمین ثبت",
                    callback_data="admin:receipt_admin:menu"
                ),
            ],
        ]
    )


ADMIN_MENU_TEXT = (
    "👋 <b>خوش آمدید | پنل مدیریت</b>\n\n"
    "از طریق دکمه‌های زیر بخش موردنظر خود را انتخاب کنید."
)


# ============================================================
# ابزارهای کمکی
# ============================================================

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


async def safe_edit_admin_menu(callback: CallbackQuery):
    """
    ویرایش پیام فعلی و نمایش منوی اصلی ادمین.
    """

    if not callback.message:
        return False

    try:
        await callback.message.edit_text(
            text=ADMIN_MENU_TEXT,
            reply_markup=admin_main_menu_keyboard()
        )
        return True

    except Exception as error:
        # اگر پیام از قبل همین محتوا را داشته باشد
        if "message is not modified" in str(error).lower():
            return True

        logger.exception(
            "Failed to edit admin menu: %s",
            error
        )

        return False


# ============================================================
# ورود به پنل ادمین با دستور /admin
# ============================================================

@router.message(Command("admin"))
async def cmd_admin(message: Message):

    user = message.from_user

    if not user:
        return

    # بررسی دسترسی
    if not is_admin(user.id):

        log_event(
            "SECURITY",
            "unauthorized_admin_access",
            user.id,
            f"username={user.username}, command=/admin"
        )

        await message.answer(
            "⛔ شما اجازه دسترسی به پنل مدیریت را ندارید."
        )
        return

    # محدودیت درخواست
    if not rate_limiter.is_allowed(user.id):

        await message.answer(
            "⏳ لطفاً چند لحظه صبر کنید و دوباره تلاش کنید."
        )
        return

    try:

        await message.answer(
            text=ADMIN_MENU_TEXT,
            reply_markup=admin_main_menu_keyboard()
        )

        log_event(
            "INFO",
            "admin_panel_opened",
            user.id
        )

    except Exception:

        logger.exception(
            "Failed to open admin panel"
        )

        await message.answer(
            "❌ خطایی هنگام باز کردن پنل مدیریت رخ داد."
        )


# ============================================================
# بازگشت به منوی اصلی پنل ادمین
# ============================================================

@router.callback_query(F.data == "admin:main")
async def callback_admin_main(callback: CallbackQuery):

    user = callback.from_user

    # پاسخ سریع به Callback
    await callback.answer()

    if not user:
        return

    # بررسی دسترسی
    if not is_admin(user.id):

        log_event(
            "SECURITY",
            "unauthorized_admin_callback",
            user.id,
            f"data={callback.data}"
        )

        await callback.answer(
            "⛔ دسترسی غیرمجاز است.",
            show_alert=True
        )
        return

    success = await safe_edit_admin_menu(callback)

    if not success:

        try:
            await callback.message.answer(
                text=ADMIN_MENU_TEXT,
                reply_markup=admin_main_menu_keyboard()
            )

        except Exception:
            logger.exception(
                "Failed to send admin menu fallback"
            )



import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import ADMIN_ID
from database import set_setting, get_setting, log_event
from rich import build_rich_message, premium_emoji
from utils import rate_limiter

logger = logging.getLogger(__name__)
router = Router(name="admin_sales")


@router.callback_query(F.data == "admin:sales:close")
async def close_sales(callback: CallbackQuery):
    user = callback.from_user
    if not user or user.id != ADMIN_ID:
        log_event("SECURITY", "unauthorized_sales_access", user.id if user else 0, "close_sales")
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    set_setting("sales_open", "0")
    log_event("INFO", "sales_closed", user.id)
    text = f"{premium_emoji('false', '❌')} **فروش با موفقیت بسته شد.**"
    await callback.message.edit_text(rich_message=build_rich_message(text))
    await callback.answer()


@router.callback_query(F.data == "admin:sales:open")
async def open_sales(callback: CallbackQuery):
    user = callback.from_user
    if not user or user.id != ADMIN_ID:
        log_event("SECURITY", "unauthorized_sales_access", user.id if user else 0, "open_sales")
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    set_setting("sales_open", "1")
    log_event("INFO", "sales_opened", user.id)
    text = f"{premium_emoji('true', '✅')} **فروش با موفقیت باز شد.**"
    await callback.message.edit_text(rich_message=build_rich_message(text))
    await callback.answer()
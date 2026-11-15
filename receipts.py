import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID, DEFAULT_RECEIPT_ADMIN_ID
from database import get_setting, set_setting, get_user_by_identifier, log_event
from rich import build_rich_message, premium_emoji, build_button_row, build_button

logger = logging.getLogger(__name__)
router = Router(name="admin_receipts")


class ReceiptAdminStates(StatesGroup):
    waiting_user = State()


@router.callback_query(F.data == "admin:receipt_admin:menu")
async def receipt_admin_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    current_admin = get_setting("receipt_admin_id", str(DEFAULT_RECEIPT_ADMIN_ID))
    text = (
        f"{premium_emoji('ask', '👤')} **مدیریت ادمین رسید**\n\n"
        f"ادمین فعلی رسید: `{current_admin}`\n\n"
        f"این شخص می‌تواند رسیدهای پرداخت را تأیید یا رد کند."
    )
    rows = [
        build_button_row([
            build_button("تغییر ادمین رسید", callback_data="admin:receipt_admin:set", style="primary"),
            build_button("حذف (برگشت به ادمین اصلی)", callback_data="admin:receipt_admin:reset", style="danger"),
        ]),
        build_button_row([
            build_button("بازگشت", callback_data="admin:main", style="danger", premium_emoji_key="back"),
        ]),
    ]
    await callback.message.edit_text(rich_message=build_rich_message(text, rows))
    await callback.answer()


@router.callback_query(F.data == "admin:receipt_admin:set")
async def set_receipt_admin_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(ReceiptAdminStates.waiting_user)
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('telegram', '👤')} **آیدی عددی یا یوزرنیم کاربر مورد نظر را وارد کنید:**"
    ))
    await callback.answer()


@router.message(ReceiptAdminStates.waiting_user)
async def set_receipt_admin(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    target = get_user_by_identifier(message.text.strip())
    if not target:
        await message.answer("❌ کاربر یافت نشد (باید قبلاً ربات را استارت کرده باشد).")
        return
    
    set_setting("receipt_admin_id", str(target["telegram_id"]))
    log_event("INFO", "receipt_admin_changed", ADMIN_ID, f"new_admin={target['telegram_id']}")
    await state.clear()
    await message.answer(f"✅ کاربر `{target['telegram_id']}` به عنوان ادمین رسید تنظیم شد.")


@router.callback_query(F.data == "admin:receipt_admin:reset")
async def reset_receipt_admin(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    set_setting("receipt_admin_id", str(DEFAULT_RECEIPT_ADMIN_ID))
    log_event("INFO", "receipt_admin_reset", ADMIN_ID)
    await callback.answer("ادمین رسید به ادمین اصلی برگشت.", show_alert=True)
    # بازگشت به منو
    await receipt_admin_menu(callback)
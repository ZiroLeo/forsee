import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID
from database import get_setting, set_setting, log_event
from rich import build_rich_message, premium_emoji, build_button_row, build_button
from utils import rate_limiter

logger = logging.getLogger(__name__)
router = Router(name="admin_links")


class LinkStates(StatesGroup):
    waiting_support = State()
    waiting_guide = State()


@router.callback_query(F.data == "admin:links:menu")
async def links_menu(callback: CallbackQuery):
    user = callback.from_user
    if not user or user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    support = get_setting("support_url", "تنظیم نشده")
    guide = get_setting("guide_url", "تنظیم نشده")

    text = (
        f"{premium_emoji('world', '🔗')} **مدیریت لینک‌ها**\n\n"
        f"💬 لینک پشتیبانی: {support}\n"
        f"📱 لینک آموزش: {guide}"
    )
    
    rows = [
        build_button_row([
            build_button("تغییر لینک پشتیبانی", callback_data="admin:links:support", style="primary"),
            build_button("تغییر لینک آموزش", callback_data="admin:links:guide", style="primary"),
        ]),
        build_button_row([
            build_button("بازگشت", callback_data="admin:main", style="danger", premium_emoji_key="back"),
        ]),
    ]
    await callback.message.edit_text(rich_message=build_rich_message(text, rows))
    await callback.answer()


@router.callback_query(F.data == "admin:links:support")
async def edit_support(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(LinkStates.waiting_support)
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('ask', '💬')} **لینک جدید پشتیبانی را وارد کنید:**\n(مثال: `https://t.me/SupportID`)"
    ))
    await callback.answer()


@router.message(LinkStates.waiting_support)
async def receive_support(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    url = message.text.strip()
    if not url.startswith("https://t.me/"):
        await message.answer("❌ فقط لینک‌های تلگرام مجاز هستند.")
        return
    set_setting("support_url", url)
    log_event("INFO", "link_updated", ADMIN_ID, "support_url")
    await state.clear()
    await message.answer("✅ لینک پشتیبانی به‌روزرسانی شد.")


@router.callback_query(F.data == "admin:links:guide")
async def edit_guide(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(LinkStates.waiting_guide)
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('quest', '📱')} **لینک جدید آموزش را وارد کنید:**"
    ))
    await callback.answer()


@router.message(LinkStates.waiting_guide)
async def receive_guide(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    url = message.text.strip()
    if not url.startswith("https://t.me/"):
        await message.answer("❌ فقط لینک‌های تلگرام مجاز هستند.")
        return
    set_setting("guide_url", url)
    log_event("INFO", "link_updated", ADMIN_ID, "guide_url")
    await state.clear()
    await message.answer("✅ لینک آموزش به‌روزرسانی شد.")
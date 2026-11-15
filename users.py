import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID
from database import (
    get_user_by_identifier, get_user_subscriptions, ban_user, unban_user,
    get_user_level, log_event
)
from rich import build_rich_message, premium_emoji, build_button_row, build_button
from utils import format_bytes

logger = logging.getLogger(__name__)
router = Router(name="admin_users")


class UserStates(StatesGroup):
    waiting_query = State()


@router.callback_query(F.data == "admin:users:menu")
async def users_menu(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(UserStates.waiting_query)
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('telegram', '👤')} **آیدی عددی یا یوزرنیم کاربر را وارد کنید:**"
    ))
    await callback.answer()


@router.message(UserStates.waiting_query)
async def user_query_received(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    query = (message.text or "").strip()
    user = get_user_by_identifier(query)
    if not user:
        await message.answer("❌ کاربر یافت نشد.")
        return

    await state.update_data(target_id=user["telegram_id"])
    await state.clear()

    level_key, level_name = get_user_level(user.get("total_purchases", 0))
    banned = user.get("is_banned", 0)
    text = (
        f"{premium_emoji('telegram', '👤')} **اطلاعات کاربر**\n\n"
        f"🆔 آیدی: `{user['telegram_id']}`\n"
        f"👤 یوزرنیم: @{user.get('username', 'ندارد')}\n"
        f"💰 موجودی: {user.get('balance', 0):,} تومان\n"
        f"🛒 تعداد خرید: {user.get('total_purchases', 0)}\n"
        f"🏆 سطح: {level_name}\n"
        f"🚫 وضعیت: {'بن' if banned else 'فعال'}"
    )
    rows = [
        build_button_row([
            build_button("مشاهده سرویس‌ها", callback_data=f"admin:users:subs:{user['telegram_id']}", style="primary"),
            build_button("آنبن" if banned else "بن", callback_data=f"admin:users:ban:{user['telegram_id']}", style="danger" if not banned else "success"),
        ]),
        build_button_row([
            build_button("بازگشت", callback_data="admin:users:menu", style="danger", premium_emoji_key="back"),
        ]),
    ]
    await message.answer_rich(rich_message=build_rich_message(text, rows))


@router.callback_query(F.data.startswith("admin:users:ban:"))
async def toggle_ban(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    target_id = int(callback.data.split(":")[3])
    user = get_user_by_identifier(str(target_id))
    if not user:
        await callback.answer("کاربر یافت نشد.", show_alert=True)
        return

    if user.get("is_banned"):
        unban_user(target_id)
        await callback.answer("کاربر آنبن شد.")
    else:
        ban_user(target_id, ADMIN_ID, "بن توسط ادمین")
        await callback.answer("کاربر بن شد.")
    log_event("INFO", "admin_ban_toggle", ADMIN_ID, f"target={target_id}, banned={not user.get('is_banned')}")
    # بازگشت به صفحه کاربر (نیاز به بازسازی)
    await callback.message.edit_text(rich_message=build_rich_message(
        f"✅ وضعیت کاربر `{target_id}` تغییر کرد. برای مشاهده مجدد، دوباره جستجو کنید."
    ))


@router.callback_query(F.data.startswith("admin:users:subs:"))
async def show_user_subs(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    target_id = int(callback.data.split(":")[3])
    subs = get_user_subscriptions(target_id, only_visible=False)[:7]
    if not subs:
        await callback.answer("کاربر سرویسی ندارد.", show_alert=True)
        return

    lines = [f"{premium_emoji('light', '📦')} **سرویس‌های کاربر `{target_id}`:**\n"]
    for s in subs:
        lines.append(f"• `{s['config_name']}` | {s['state']} | {s.get('volume_gb', 0)}G")
    rows = [build_button_row([
        build_button("بازگشت", callback_data=f"admin:users:back:{target_id}", style="danger", premium_emoji_key="back")
    ])]
    await callback.message.edit_text(rich_message=build_rich_message("\n".join(lines), rows))
    await callback.answer()
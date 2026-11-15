import logging
import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID
from database import get_connection, get_user_by_identifier, log_event
from rich import build_rich_message, premium_emoji, build_button_row, build_button

logger = logging.getLogger(__name__)
router = Router(name="admin_broadcast")


class BroadcastStates(StatesGroup):
    waiting_target = State()
    waiting_text = State()
    waiting_forward_link = State()


# ============================================================
# منوی ارسال پیام
# ============================================================

@router.callback_query(F.data == "admin:broadcast:menu")
async def broadcast_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    text = f"{premium_emoji('ask', '📨')} **ارسال پیام**\n\nلطفاً یک گزینه را انتخاب کنید:"
    rows = [
        build_button_row([
            build_button("ارسال به شخص", callback_data="admin:broadcast:single", style="primary"),
            build_button("ارسال به همه", callback_data="admin:broadcast:all", style="primary"),
        ]),
        build_button_row([
            build_button("بازگشت", callback_data="admin:main", style="danger", premium_emoji_key="back"),
        ]),
    ]
    await callback.message.edit_text(rich_message=build_rich_message(text, rows))
    await callback.answer()


# ============================================================
# ارسال به شخص
# ============================================================

@router.callback_query(F.data == "admin:broadcast:single")
async def broadcast_single_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(BroadcastStates.waiting_target)
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('telegram', '👤')} **آیدی عددی یا یوزرنیم کاربر را وارد کنید:**"
    ))
    await callback.answer()


@router.message(BroadcastStates.waiting_target)
async def broadcast_single_target(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    target = get_user_by_identifier(message.text.strip())
    if not target:
        await message.answer("❌ کاربر یافت نشد.")
        return
    await state.update_data(target_id=target["telegram_id"])
    await state.set_state(BroadcastStates.waiting_text)
    await message.answer_rich(rich_message=build_rich_message(
        f"{premium_emoji('ask', '✍️')} **متن پیام را وارد کنید:**"
    ))


@router.message(BroadcastStates.waiting_text)
async def broadcast_single_text(message: Message, state: FSMContext, bot):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    target_id = data.get("target_id")
    text = message.text.strip()
    if not text:
        await message.answer("❌ متن خالی است.")
        return
    try:
        await bot.send_message(target_id, text)
        await message.answer("✅ پیام ارسال شد.")
        log_event("INFO", "broadcast_single", ADMIN_ID, f"target={target_id}")
    except Exception as e:
        logger.exception(f"Broadcast single failed: {e}")
        await message.answer(f"❌ خطا در ارسال: {e}")
    await state.clear()


# ============================================================
# ارسال به همه (انتخاب نوع)
# ============================================================

@router.callback_query(F.data == "admin:broadcast:all")
async def broadcast_all_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    text = f"{premium_emoji('ask', '📢')} **ارسال به همه**\n\nنوع ارسال را انتخاب کنید:"
    rows = [
        build_button_row([
            build_button("ارسال متن عادی", callback_data="admin:broadcast:text", style="primary"),
            build_button("ارسال از طریق لینک", callback_data="admin:broadcast:link", style="primary"),
        ]),
        build_button_row([
            build_button("بازگشت", callback_data="admin:broadcast:menu", style="danger", premium_emoji_key="back"),
        ]),
    ]
    await callback.message.edit_text(rich_message=build_rich_message(text, rows))
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast:text")
async def broadcast_text_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(BroadcastStates.waiting_text)
    await state.update_data(broadcast_mode="text")
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('ask', '✍️')} **متن پیام را وارد کنید:**"
    ))
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast:link")
async def broadcast_link_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(BroadcastStates.waiting_forward_link)
    await state.update_data(broadcast_mode="link")
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('world', '🔗')} **لینک پیام کانال را وارد کنید:**\n(مثال: `https://t.me/channel/123`)"
    ))
    await callback.answer()


# ============================================================
# دریافت متن/لینک و ارسال به همه
# ============================================================

@router.message(BroadcastStates.waiting_text)
async def broadcast_all_text(message: Message, state: FSMContext, bot):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    if data.get("broadcast_mode") != "text":
        # برای ارسال به شخص
        return
    text = message.text.strip()
    if not text:
        await message.answer("❌ متن خالی است.")
        return
    await _send_to_all(bot, message, text=text)
    await state.clear()


@router.message(BroadcastStates.waiting_forward_link)
async def broadcast_all_link(message: Message, state: FSMContext, bot):
    if message.from_user.id != ADMIN_ID:
        return
    link = message.text.strip()
    if not link.startswith("https://t.me/"):
        await message.answer("❌ لینک نامعتبر.")
        return

    # استخراج chat_id و message_id از لینک
    # فرمت: https://t.me/channel/123  یا  https://t.me/c/123456/123
    try:
        parts = link.replace("https://t.me/", "").split("/")
        if parts[0] == "c":
            chat_id = int(f"-100{parts[1]}")
            msg_id = int(parts[2])
        else:
            chat_id = f"@{parts[0]}"
            msg_id = int(parts[1])
    except (IndexError, ValueError):
        await message.answer("❌ فرمت لینک نامعتبر.")
        return

    await _send_to_all(bot, message, forward_from=(chat_id, msg_id))
    await state.clear()


async def _send_to_all(bot, admin_message: Message, text=None, forward_from=None):
    """ارسال پیام به همه کاربران با تأخیر و گزارش تعداد موفق/ناموفق."""
    with get_connection() as conn:
        rows = conn.execute("SELECT telegram_id FROM users").fetchall()
        user_ids = [r["telegram_id"] for r in rows]

    ok, fail = 0, 0
    for uid in user_ids:
        try:
            if forward_from:
                await bot.forward_message(uid, from_chat_id=forward_from[0], message_id=forward_from[1])
            else:
                await bot.send_message(uid, text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)  # جلوگیری از بلاک شدن

    log_event("INFO", "broadcast_all", ADMIN_ID, f"ok={ok}, fail={fail}")
    await admin_message.answer(f"✅ ارسال به همه انجام شد.\nموفق: {ok}\nناموفق: {fail}")
import logging
import time
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID
from database import (
    get_connection, get_subscription, update_subscription_volume,
    update_subscription_state, hard_delete_subscription, log_event
)
from paxiva import PaxivaClient, PaxivaError
from rich import build_rich_message, premium_emoji, build_button_row, build_button
from utils import validate_config_name, format_bytes, format_days_remaining

logger = logging.getLogger(__name__)
router = Router(name="admin_services")


class ServiceStates(StatesGroup):
    waiting_query = State()
    waiting_volume = State()
    waiting_days = State()


@router.callback_query(F.data == "admin:services:menu")
async def services_menu(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(ServiceStates.waiting_query)
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('world', '🌍')} **نام کانفیگ را وارد کنید:**\n(مثال: `iMan-35`)"
    ))
    await callback.answer()


@router.message(ServiceStates.waiting_query)
async def service_query_received(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    query = (message.text or "").strip()
    if not validate_config_name(query):
        await message.answer("❌ فرمت نامعتبر. مثال: `iMan-35`")
        return

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE config_name = ? COLLATE NOCASE", (query,)).fetchone()
        sub = dict(row) if row else None

    if not sub:
        await message.answer("❌ سرویس یافت نشد.")
        await state.clear()
        return

    await state.update_data(sub_id=sub["id"])
    await state.set_state(None)

    state_fa = {"active": "فعال", "expired": "منقضی", "depleted": "حجم تمام", "deleted": "حذف شده"}.get(sub["state"], sub["state"])
    volume_gb = sub.get("volume_gb", 0)
    text = (
        f"{premium_emoji('telegram', '📋')} **جزئیات سرویس `{sub['config_name']}`**\n\n"
        f"👤 مالک: `{sub['telegram_id']}`\n"
        f"وضعیت: {state_fa}\n"
        f"📦 حجم: {volume_gb if volume_gb > 0 else 'بی‌نهایت'} گیگ\n"
        f"📊 مصرف: {format_bytes(sub.get('used_bytes', 0))}\n"
        f"📅 انقضا: {format_days_remaining(sub.get('expires_at'))}\n"
        f"👥 دستگاه: {sub.get('devices', 2)}"
    )
    rows = [
        build_button_row([
            build_button("ویرایش حجم", callback_data="admin:services:edit_volume", style="primary"),
            build_button("ویرایش روز", callback_data="admin:services:edit_days", style="primary"),
        ]),
        build_button_row([
            build_button("حذف", callback_data=f"admin:services:delete:{sub['id']}", style="danger", premium_emoji_key="false"),
            build_button("بازگشت", callback_data="admin:services:menu", style="danger", premium_emoji_key="back"),
        ]),
    ]
    await message.answer_rich(rich_message=build_rich_message(text, rows))


@router.callback_query(F.data == "admin:services:edit_volume")
async def edit_volume_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(ServiceStates.waiting_volume)
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('light', '📦')} **حجم جدید را به گیگابایت وارد کنید:**"
    ))
    await callback.answer()


@router.message(ServiceStates.waiting_volume)
async def edit_volume_received(message: Message, state: FSMContext, paxiva: PaxivaClient):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        new_vol = float(message.text.strip())
        if new_vol < 0 or new_vol > 10000:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ عدد نامعتبر.")
        return

    data = await state.get_data()
    sub = get_subscription(data.get("sub_id"))
    if not sub:
        await message.answer("سرویس یافت نشد.")
        await state.clear()
        return

    try:
        await paxiva.update_client_volume(sub["paxiva_client_id"], new_vol)
        update_subscription_volume(sub["id"], new_vol)
        log_event("INFO", "admin_edit_volume", message.from_user.id, f"sub_id={sub['id']}, new_vol={new_vol}")
        await message.answer(f"✅ حجم سرویس به {new_vol} گیگ تغییر کرد.")
    except PaxivaError as e:
        await message.answer(f"❌ خطا در پنل: {e.message}")
    await state.clear()


@router.callback_query(F.data == "admin:services:edit_days")
async def edit_days_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(ServiceStates.waiting_days)
    await callback.message.edit_text(rich_message=build_rich_message(
        f"{premium_emoji('light', '📅')} **تعداد روز جدید را وارد کنید:**"
    ))
    await callback.answer()


@router.message(ServiceStates.waiting_days)
async def edit_days_received(message: Message, state: FSMContext, paxiva: PaxivaClient):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        days = int(message.text.strip())
        if days < 0 or days > 3650:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ عدد نامعتبر (۰ تا ۳۶۵۰).")
        return

    data = await state.get_data()
    sub = get_subscription(data.get("sub_id"))
    if not sub:
        await message.answer("سرویس یافت نشد.")
        await state.clear()
        return

    try:
        await paxiva.renew_volume_client(sub["paxiva_client_id"], days, f"admin-edit-{sub['id']}")
        new_expires = int(time.time()) + (days * 86400)
        update_subscription_state(sub["id"], "active", new_expires, None)
        log_event("INFO", "admin_edit_days", message.from_user.id, f"sub_id={sub['id']}, days={days}")
        await message.answer(f"✅ مدت سرویس به {days} روز تغییر کرد.")
    except PaxivaError as e:
        await message.answer(f"❌ خطا در پنل: {e.message}")
    await state.clear()


@router.callback_query(F.data.startswith("admin:services:delete:"))
async def delete_service(callback: CallbackQuery, paxiva: PaxivaClient):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    sub_id = int(callback.data.split(":")[3])
    sub = get_subscription(sub_id)
    if not sub:
        await callback.answer("سرویس یافت نشد.", show_alert=True)
        return

    try:
        if sub.get("paxiva_client_id"):
            await paxiva.delete_client(sub["paxiva_client_id"], purge=True)
        hard_delete_subscription(sub_id)
        log_event("INFO", "admin_service_deleted", callback.from_user.id, f"sub_id={sub_id}")
        await callback.message.edit_text(rich_message=build_rich_message(
            f"{premium_emoji('true', '✅')} سرویس `{sub['config_name']}` حذف شد."
        ))
    except PaxivaError as e:
        await callback.message.edit_text(rich_message=build_rich_message(
            f"{premium_emoji('false', '❌')} خطا در حذف از پنل: {e.message}"
        ))
    await callback.answer()
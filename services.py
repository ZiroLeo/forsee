import logging
import re
import time
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database import (
    get_connection, get_subscription, get_subscription_by_config_name,
    update_subscription_volume, update_subscription_state,
    hard_delete_subscription, get_user, log_event,
)
from paxiva import PaxivaClient, PaxivaError
from utils import validate_config_name, format_bytes, format_days_remaining

from .admin_ui import (
    btn, menu, page, toast, em, esc, money, LINE, protect, ask, refresh_panel,
    reset_flow, parse_int, fmt_date, bar, BLUE, GREEN, RED,
)

logger = logging.getLogger(__name__)
router = Router(name="admin_services")
protect(router)

GIB = 1024 ** 3
STATE_FA = {
    "active": "فعال ✅", "expired": "منقضی ⌛", "depleted": "حجم تمام شده 📉",
    "deleted": "حذف شده 🗑", "paused": "متوقف ⏸", "disabled": "غیرفعال ⛔",
}


class ServiceStates(StatesGroup):
    waiting_query = State()
    waiting_volume = State()
    waiting_days = State()


# ============================================================
# جستجو (نام کانفیگ یا لینک ساب)
# ============================================================

def _find_by_link(text: str) -> Optional[dict]:
    text = text.strip()
    token = text.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE link = ?", (text,)).fetchone()
        if not row and len(token) >= 8 and re.fullmatch(r"[A-Za-z0-9_\-]+", token):
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE link LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 1",
                (f"%/{token.replace('_', chr(92) + '_')}%",),
            ).fetchone()
        return dict(row) if row else None


def find_subscription(query: str) -> Optional[dict]:
    query = (query or "").strip()
    if not query:
        return None
    if validate_config_name(query):
        return get_subscription_by_config_name(query)
    if query.lower().startswith(("http://", "https://")):
        return _find_by_link(query)
    return None


# ============================================================
# صفحهٔ جزئیات
# ============================================================

async def _live(paxiva: PaxivaClient, sub: dict) -> tuple[Optional[dict], bool]:
    if not sub.get("paxiva_client_id"):
        return None, False
    try:
        return await paxiva.get_client(int(sub["paxiva_client_id"])), True
    except PaxivaError as error:
        logger.warning("panel lookup failed for sub %s: %s", sub["id"], getattr(error, "message", error))
    except Exception:
        logger.exception("panel lookup crashed for sub %s", sub["id"])
    return None, False


async def render_service(sub_id: int, paxiva: PaxivaClient):
    sub = get_subscription(sub_id)
    if not sub:
        return None

    remote, is_live = await _live(paxiva, sub)
    src = remote or {}

    used = int(src.get("used_bytes") if src.get("used_bytes") is not None else (sub.get("used_bytes") or 0))
    volume_gb = float(src.get("volume_gb") if src.get("volume_gb") is not None else (sub.get("volume_gb") or 0))
    expires_at = src.get("expires_at") if remote is not None else sub.get("expires_at")
    state_key = src.get("state") or sub.get("state") or "active"

    # همگام‌سازی دیتابیس با پنل (فقط وقتی پاسخ زنده داریم)
    if remote is not None:
        try:
            update_subscription_state(sub["id"], state_key, expires_at, used)
        except Exception:
            logger.exception("sync failed for sub %s", sub["id"])

    if volume_gb > 0:
        total = int(volume_gb * GIB)
        percent = min(100.0, used * 100 / total) if total else 0
        usage = (
            f"{bar(percent)} <b>{percent:.0f}%</b>\n"
            f"مصرف: <b>{format_bytes(used)}</b> از <b>{volume_gb:g} گیگ</b>\n"
            f"باقی‌مانده: <b>{format_bytes(max(0, total - used))}</b>"
        )
    else:
        usage = f"مصرف: <b>{format_bytes(used)}</b> (حجم نامحدود)"

    owner = get_user(sub["telegram_id"]) or {}
    owner_name = f"@{owner['username']}" if owner.get("username") else (owner.get("first_name") or "—")
    kind_fa = "نامحدود" if sub.get("kind") == "unl" else "حجمی"
    expiry = "بدون محدودیت زمانی" if not expires_at else f"{format_days_remaining(expires_at)}  ({fmt_date(expires_at)})"
    link = src.get("link") or sub.get("link")
    live_note = "" if is_live else f"\n{em('warning', '⚠️')} <i>اتصال به پنل برقرار نشد؛ اطلاعات از دیتابیس است.</i>"

    text = (
        f"{em('world', '🌍')} <b>سرویس</b> <code>{esc(sub['config_name'])}</code>\n{LINE}\n"
        f"👤 مالک: <code>{sub['telegram_id']}</code> ({esc(owner_name)})\n"
        f"📌 وضعیت: <b>{STATE_FA.get(state_key, esc(state_key))}</b>\n"
        f"🧩 نوع: <b>{kind_fa}</b>   👥 دستگاه: <b>{int(sub.get('devices') or 0)}</b>\n"
        f"⏳ انقضا: <b>{expiry}</b>\n"
        f"{LINE}\n{usage}\n{LINE}\n"
        f"💰 قیمت خرید: <b>{money(sub.get('price_toman') or 0)}</b> تومان / <b>{money(sub.get('price_stars') or 0)}</b> ⭐\n"
        f"📅 ساخته‌شده: {fmt_date(sub.get('created_at'))}"
        f"{live_note}"
    )
    if link:
        text += f"\n\n🔗 <code>{esc(link)}</code>"

    markup = menu(
        [
            btn("بروزرسانی", f"admin:services:open:{sub_id}", emoji="light"),
            btn("پروفایل مالک", f"admin:users:view:{sub['telegram_id']}", style=GREEN, emoji="telegram"),
            btn("افزودن روز", f"admin:services:days:{sub_id}", emoji="blue_dot"),
            btn("ویرایش حجم", f"admin:services:volume:{sub_id}", style=GREEN, emoji="safe"),
            btn("ریست مصرف", f"admin:services:reset:{sub_id}", emoji="dice"),
            btn("حذف سرویس", f"admin:services:delask:{sub_id}", style=RED, emoji="warning"),
        ],
        back="admin:services:menu",
    )
    return text, markup


@router.callback_query(F.data == "admin:services:menu")
async def services_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await ask(
        callback, state, ServiceStates.waiting_query,
        f"{em('world', '🌍')} <b>مدیریت سرویس‌ها</b>\n{LINE}\n"
        "نام کانفیگ یا لینک ساب را بفرست.\n\n"
        "مثال‌ها:\n<code>iMan-35</code>\n<code>https://panel.example.com/s/9f2c4e1a…</code>",
        "admin:main",
    )


@router.message(ServiceStates.waiting_query, F.text)
async def query_received(message: Message, state: FSMContext, bot: Bot, paxiva: PaxivaClient):
    sub = find_subscription(message.text)
    if not sub:
        try:
            await message.delete()
        except Exception:
            pass
        await refresh_panel(
            bot, state, message,
            f"{em('warning', '⚠️')} <b>سرویسی پیدا نشد.</b>\nنام کانفیگ (مثل <code>iMan-35</code>) "
            "یا لینک کامل ساب را دوباره بفرست.",
            menu([], back="admin:main", back_text="انصراف"),
            delete_source=False,
        )
        return
    await reset_flow(state)
    view = await render_service(sub["id"], paxiva)
    await refresh_panel(bot, state, message, *view)


@router.callback_query(F.data.startswith("admin:services:open:"))
async def open_service(callback: CallbackQuery, state: FSMContext, paxiva: PaxivaClient):
    await state.clear()
    await callback.answer()
    view = await render_service(int(callback.data.split(":")[3]), paxiva)
    if not view:
        await toast(callback, "سرویس یافت نشد.", True)
        return
    await page(callback, *view, answer=False)


# ============================================================
# ریست مصرف
# ============================================================

@router.callback_query(F.data.startswith("admin:services:reset:"))
async def reset_usage(callback: CallbackQuery, paxiva: PaxivaClient):
    sub_id = int(callback.data.split(":")[3])
    sub = get_subscription(sub_id)
    if not sub or not sub.get("paxiva_client_id"):
        await toast(callback, "سرویس یافت نشد.", True)
        return
    try:
        await paxiva.reset_client_traffic(int(sub["paxiva_client_id"]))
        update_subscription_state(sub_id, sub.get("state") or "active", None, 0)
        log_event("INFO", "admin_reset_usage", callback.from_user.id, f"sub_id={sub_id}")
        await toast(callback, "مصرف صفر شد.")
    except PaxivaError as error:
        await toast(callback, f"خطا در پنل: {error.message}", True)
        return
    await page(callback, *(await render_service(sub_id, paxiva)), answer=False)


# ============================================================
# افزودن روز / ویرایش حجم
# ============================================================

@router.callback_query(F.data.startswith("admin:services:days:"))
async def days_ask(callback: CallbackQuery, state: FSMContext):
    sub_id = int(callback.data.split(":")[3])
    await ask(
        callback, state, ServiceStates.waiting_days,
        f"{em('light', '📅')} <b>افزودن روز</b>\n{LINE}\n"
        "تعداد روزی که به اعتبار سرویس <b>اضافه</b> شود را بفرست (۱ تا ۳۶۵۰).",
        f"admin:services:open:{sub_id}", sub_id=sub_id,
    )


@router.message(ServiceStates.waiting_days, F.text)
async def days_received(message: Message, state: FSMContext, bot: Bot, paxiva: PaxivaClient):
    days = parse_int(message.text, 1, 3650)
    if days is None:
        try:
            await message.delete()
        except Exception:
            pass
        return
    data = await state.get_data()
    sub = get_subscription(data.get("sub_id"))
    if not sub or not sub.get("paxiva_client_id"):
        await reset_flow(state)
        await refresh_panel(bot, state, message, "❌ سرویس یافت نشد.", menu([], back="admin:services:menu"))
        return
    try:
        await paxiva.renew_volume_client(int(sub["paxiva_client_id"]), days, f"admin-days-{sub['id']}-{int(time.time())}")
        log_event("INFO", "admin_add_days", message.from_user.id, f"sub_id={sub['id']}, days={days}")
        notice = f"{em('true', '✅')} <b>{days} روز به سرویس اضافه شد.</b>\n\n"
    except PaxivaError as error:
        notice = f"{em('false', '❌')} <b>خطا در پنل:</b> {esc(error.message)}\n\n"
    await reset_flow(state)
    view = await render_service(sub["id"], paxiva)
    await refresh_panel(bot, state, message, notice + view[0], view[1])


@router.callback_query(F.data.startswith("admin:services:volume:"))
async def volume_ask(callback: CallbackQuery, state: FSMContext):
    sub_id = int(callback.data.split(":")[3])
    await ask(
        callback, state, ServiceStates.waiting_volume,
        f"{em('safe', '📦')} <b>ویرایش حجم</b>\n{LINE}\n"
        "حجم جدید را به گیگابایت بفرست (۰ تا ۱۰۰۰۰).",
        f"admin:services:open:{sub_id}", sub_id=sub_id,
    )


@router.message(ServiceStates.waiting_volume, F.text)
async def volume_received(message: Message, state: FSMContext, bot: Bot, paxiva: PaxivaClient):
    try:
        volume = float(message.text.strip().replace(",", "."))
        if volume < 0 or volume > 10000:
            raise ValueError
    except (ValueError, AttributeError):
        try:
            await message.delete()
        except Exception:
            pass
        return
    data = await state.get_data()
    sub = get_subscription(data.get("sub_id"))
    if not sub or not sub.get("paxiva_client_id"):
        await reset_flow(state)
        await refresh_panel(bot, state, message, "❌ سرویس یافت نشد.", menu([], back="admin:services:menu"))
        return
    try:
        await paxiva.update_client_volume(int(sub["paxiva_client_id"]), volume)
        update_subscription_volume(sub["id"], volume)
        log_event("INFO", "admin_edit_volume", message.from_user.id, f"sub_id={sub['id']}, new_vol={volume}")
        notice = f"{em('true', '✅')} <b>حجم سرویس به {volume:g} گیگ تغییر کرد.</b>\n\n"
    except PaxivaError as error:
        notice = f"{em('false', '❌')} <b>خطا در پنل:</b> {esc(error.message)}\n\n"
    await reset_flow(state)
    view = await render_service(sub["id"], paxiva)
    await refresh_panel(bot, state, message, notice + view[0], view[1])


# ============================================================
# حذف سرویس (با تأیید)
# ============================================================

@router.callback_query(F.data.startswith("admin:services:delask:"))
async def delete_ask(callback: CallbackQuery):
    sub_id = int(callback.data.split(":")[3])
    sub = get_subscription(sub_id)
    if not sub:
        await toast(callback, "سرویس یافت نشد.", True)
        return
    await page(
        callback,
        f"{em('warning', '⚠️')} <b>سرویس <code>{esc(sub['config_name'])}</code> حذف شود؟</b>\n{LINE}\n"
        "سرویس از پنل و دیتابیس پاک می‌شود و قابل بازگشت نیست.",
        menu(
            [
                btn("بله، حذف کن", f"admin:services:delete:{sub_id}", style=RED, emoji="false"),
                btn("نه، انصراف", f"admin:services:open:{sub_id}", style=GREEN, emoji="true"),
            ],
            back=None,
        ),
    )


@router.callback_query(F.data.startswith("admin:services:delete:"))
async def delete_service(callback: CallbackQuery, paxiva: PaxivaClient):
    sub_id = int(callback.data.split(":")[3])
    sub = get_subscription(sub_id)
    if not sub:
        await toast(callback, "سرویس یافت نشد.", True)
        return
    try:
        if sub.get("paxiva_client_id"):
            await paxiva.delete_client(int(sub["paxiva_client_id"]), purge=True)
    except PaxivaError as error:
        if getattr(error, "status_code", None) != 404:
            await page(
                callback,
                f"{em('false', '❌')} <b>حذف از پنل ناموفق بود:</b> {esc(error.message)}\nسرویس در دیتابیس باقی ماند.",
                menu([], back=f"admin:services:open:{sub_id}"),
            )
            return
    hard_delete_subscription(sub_id)
    log_event("INFO", "admin_service_deleted", callback.from_user.id, f"sub_id={sub_id}; name={sub['config_name']}")
    await page(
        callback,
        f"{em('true', '✅')} <b>سرویس <code>{esc(sub['config_name'])}</code> حذف شد.</b>",
        menu([btn("جستجوی سرویس دیگر", "admin:services:menu", style=GREEN, emoji="world")]),
    )

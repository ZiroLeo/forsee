import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from config import ADMIN_ID
from database import (
    list_users_page, get_user_level, get_user_registration_date,
    is_banned, ban_user, unban_user, log_admin_action, log_event,
)

from .admin_ui import (
    btn, page, toast, em, esc, money, LINE, protect, BLUE, GREEN, RED,
)

logger = logging.getLogger(__name__)
router = Router(name="admin_users_list")
protect(router)

PAGE_SIZE = 5
LEVEL_ICON = {"new": "🌱", "prime": "🥈", "royal": "👑", "diamond": "💎", "legendary": "🏆"}


def _total_pages(total: int) -> int:
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


def _render(page_no: int):
    users, total = list_users_page(page_no, PAGE_SIZE)
    pages = _total_pages(total)

    # اگر صفحه خارج از محدوده شد، به آخرین صفحه برگرد
    if not users and page_no > 1:
        return _render(pages)

    lines = [f"{em('blue_heart', '📋')} <b>لیست کاربران</b> — صفحه {page_no} از {pages}  ({total} کاربر)", LINE]
    rows = []

    if not users:
        lines.append("هنوز کاربری ثبت نشده است.")

    for u in users:
        tid = u["telegram_id"]
        banned = is_banned(tid)
        level_key, level_name = get_user_level(int(u.get("total_purchases") or 0))
        username = f"@{esc(u['username'])}" if u.get("username") else "بدون یوزرنیم"
        name = esc(u.get("first_name") or "—")
        status = f"{em('false', '🚫')} مسدود" if banned else f"{em('true', '✅')} فعال"
        lines.append(
            f"👤 <code>{tid}</code> | {username} | {name}\n"
            f"     📅 عضویت: {get_user_registration_date(tid)}\n"
            f"     📦 سرویس: <b>{u['sub_count']}</b> | 🛒 خرید: <b>{int(u.get('total_purchases') or 0)}</b> | "
            f"{LEVEL_ICON.get(level_key, '⭐')} {esc(level_name)}\n"
            f"     💰 {money(u.get('balance') or 0)} تومان | {status}"
        )
        lines.append(LINE)

        ban_button = (
            btn("رفع مسدودی", f"admin:users_list:unban:{tid}:{page_no}", style=GREEN, emoji="true")
            if banned
            else btn("مسدود کردن", f"admin:users_list:ban:{tid}:{page_no}", style=RED, emoji="false")
        )
        rows.append([btn(f"پروفایل {tid}", f"admin:users:view:{tid}", style=BLUE, emoji="telegram"), ban_button])

    nav = []
    if page_no > 1:
        nav.append(btn("◀️ قبلی", f"admin:users_list:page:{page_no - 1}", style=BLUE))
    if page_no < pages:
        nav.append(btn("بعدی ▶️", f"admin:users_list:page:{page_no + 1}", style=GREEN))
    if nav:
        rows.append(nav)
    rows.append([btn("بازگشت", "admin:main", style=RED, emoji="back")])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _page_from(data: str, index: int) -> int:
    try:
        return max(1, int(data.split(":")[index]))
    except (IndexError, ValueError):
        return 1


@router.callback_query(F.data == "admin:users_list:menu")
async def users_list_menu(callback: CallbackQuery):
    text, markup = _render(1)
    await page(callback, text, markup)


@router.callback_query(F.data.startswith("admin:users_list:page:"))
async def users_list_page(callback: CallbackQuery):
    text, markup = _render(_page_from(callback.data, 3))
    await page(callback, text, markup)


@router.callback_query(F.data.startswith("admin:users_list:ban:"))
async def users_list_ban(callback: CallbackQuery):
    parts = callback.data.split(":")
    target, page_no = int(parts[3]), _page_from(callback.data, 4)
    if target == ADMIN_ID:
        await toast(callback, "مسدود کردن ادمین اصلی ممکن نیست.", True)
        return
    ban_user(target, callback.from_user.id, "مسدود توسط ادمین")
    log_admin_action(callback.from_user.id, "user_ban", str(target), "from users_list")
    log_event("INFO", "admin_user_banned", callback.from_user.id, f"target={target}")
    await toast(callback, "کاربر مسدود شد.")
    text, markup = _render(page_no)
    await page(callback, text, markup, answer=False)


@router.callback_query(F.data.startswith("admin:users_list:unban:"))
async def users_list_unban(callback: CallbackQuery):
    parts = callback.data.split(":")
    target, page_no = int(parts[3]), _page_from(callback.data, 4)
    unban_user(target, callback.from_user.id)
    log_admin_action(callback.from_user.id, "user_unban", str(target), "from users_list")
    log_event("INFO", "admin_user_unbanned", callback.from_user.id, f"target={target}")
    await toast(callback, "مسدودی برداشته شد.")
    text, markup = _render(page_no)
    await page(callback, text, markup, answer=False)

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import ADMIN_ID
from database import get_connection, get_user_level, log_event
from rich import build_rich_message, premium_emoji, build_button_row, build_button
from utils import rate_limiter

logger = logging.getLogger(__name__)
router = Router(name="admin_users_list")

PAGE_SIZE = 5


def _fetch_users_page(page: int):
    """دریافت یک صفحه از کاربران (۵ تایی) به همراه تعداد کانفیگ."""
    offset = (page - 1) * PAGE_SIZE
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT 
                u.telegram_id, u.username, u.first_name, u.balance, u.total_purchases,
                (SELECT COUNT(*) FROM subscriptions s WHERE s.telegram_id = u.telegram_id) AS sub_count
            FROM users u
            ORDER BY u.total_purchases DESC, u.telegram_id ASC
            LIMIT ? OFFSET ?
            """,
            (PAGE_SIZE, offset)
        ).fetchall()
        users = [dict(r) for r in rows]
        total = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    return users, int(total)


@router.callback_query(F.data.startswith("admin:users_list:page:"))
async def show_users_page(callback: CallbackQuery):
    user = callback.from_user
    if not user or user.id != ADMIN_ID:
        log_event("SECURITY", "unauthorized_users_list", user.id if user else 0)
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    page = int(callback.data.split(":")[3])
    if page < 1:
        page = 1
    users, total = _fetch_users_page(page)

    if not users:
        await callback.answer("لیست خالی است.", show_alert=True)
        return

    lines = [f"{premium_emoji('light', '📋')} **لیست کاربران (صفحه {page}):**\n"]
    for u in users:
        level_key, level_name = get_user_level(u.get("total_purchases", 0))
        name = u.get("first_name") or u.get("username") or "نامشخص"
        lines.append(
            f"• `{u['telegram_id']}` | {name}\n"
            f"   💰 {u['balance']:,} تومان | 📦 {u['sub_count']} سرویس | 🏆 {level_name}"
        )

    text = "\n".join(lines)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    nav_row = []
    if page > 1:
        nav_row.append(build_button("◀️ قبلی", callback_data=f"admin:users_list:page:{page-1}", style="primary"))
    if page < total_pages:
        nav_row.append(build_button("بعدی ▶️", callback_data=f"admin:users_list:page:{page+1}", style="primary"))

    rows = []
    if nav_row:
        rows.append(build_button_row(nav_row))
    rows.append(build_button_row([
        build_button("بازگشت", callback_data="admin:main", style="danger", premium_emoji_key="back")
    ]))

    try:
        await callback.message.edit_text(rich_message=build_rich_message(text, rows))
    except Exception as e:
        logger.exception(f"Failed to show users page: {e}")
    await callback.answer()


@router.callback_query(F.data == "admin:users_list:menu")
async def users_list_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    # نمایش صفحه اول
    callback.data = "admin:users_list:page:1"
    await show_users_page(callback)
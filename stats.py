import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import ADMIN_ID
from database import get_admin_stats, get_connection, log_event
from rich import build_rich_message, premium_emoji
from utils import rate_limiter

logger = logging.getLogger(__name__)
router = Router(name="admin_stats")


@router.callback_query(F.data == "admin:stats:menu")
async def show_stats(callback: CallbackQuery):
    user = callback.from_user
    if not user or user.id != ADMIN_ID:
        log_event("SECURITY", "unauthorized_stats", user.id if user else 0)
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    stats = get_admin_stats()
    
    # پیدا کردن پرفروش‌ترین سرویس
    with get_connection() as conn:
        top_service = conn.execute(
            "SELECT volume_gb, COUNT(*) as c FROM subscriptions GROUP BY volume_gb ORDER BY c DESC LIMIT 1"
        ).fetchone()
    
    top_str = "نامشخص"
    if top_service:
        top_str = f"{top_service['volume_gb']} گیگ ({top_service['c']} فروش)"

    text = (
        f"{premium_emoji('diamond', '📊')} **آمار کلی ربات**\n\n"
        f"👥 کل کاربران: {stats['total_users']:,}\n"
        f"🚫 کاربران بن‌شده: {stats['banned_users']:,}\n"
        f"🛒 کل خریدها: {stats['total_purchases']:,}\n"
        f"💰 کل موجودی کاربران: {stats['total_balance']:,} تومان\n"
        f"💵 کل درآمد (تومان): {stats['total_revenue_toman']:,} تومان\n"
        f"⭐ کل Stars دریافتی: {stats['total_stars']:,}\n\n"
        f"🏆 پرفروش‌ترین سرویس: {top_str}"
    )
    
    await callback.message.edit_text(rich_message=build_rich_message(text))
    await callback.answer()
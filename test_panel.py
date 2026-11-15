import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import ADMIN_ID
from paxiva import PaxivaClient, PaxivaError
from rich import build_rich_message, premium_emoji
from utils import rate_limiter

logger = logging.getLogger(__name__)
router = Router(name="admin_test_panel")


@router.callback_query(F.data == "admin:test_panel:menu")
async def test_panel(callback: CallbackQuery, paxiva: PaxivaClient):
    user = callback.from_user
    if not user or user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    try:
        await callback.answer("در حال تست اتصال...", show_alert=False)
        me = await paxiva.get_me()
        
        # استخراج اطلاعات مفید از پاسخ
        credits = me.get("credits", 0)
        pool = me.get("pool", {})
        pool_gb = pool.get("gb", 0) if pool else 0
        counts = me.get("counts", {})
        clients = counts.get("clients", 0)

        text = (
            f"{premium_emoji('true', '✅')} **اتصال به پنل موفق بود!**\n\n"
            f"🆔 شناسه حساب: `{me.get('id', '?')}`\n"
            f"🏢 برند: {me.get('brand', '?')}\n"
            f"💰 اعتبار (Credits): {credits}\n"
            f"📦 موجودی حجمی (Pool): {pool_gb} GB\n"
            f"👥 تعداد کاربران پنل: {clients}"
        )
        await callback.message.edit_text(rich_message=build_rich_message(text))
        
    except PaxivaError as e:
        logger.error(f"Panel test failed: {e}")
        await callback.message.edit_text(rich_message=build_rich_message(
            f"{premium_emoji('false', '❌')} **خطا در اتصال به پنل:**\n\n"
            f"کد خطا: {e.error_code}\n"
            f"پیام: {e.message}"
        ))
    except Exception as e:
        logger.exception(f"Panel test unexpected error: {e}")
        await callback.message.edit_text(rich_message=build_rich_message(
            f"{premium_emoji('warning', '⚠️')} **خطای غیرمنتظره در تست پنل.**"
        ))
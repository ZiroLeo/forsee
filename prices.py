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
router = Router(name="admin_prices")


class PriceStates(StatesGroup):
    waiting_value = State()


# ============================================================
# منوی تغییر قیمت
# ============================================================

@router.callback_query(F.data == "admin:prices:menu")
async def prices_menu(callback: CallbackQuery):
    user = callback.from_user
    if not user or user.id != ADMIN_ID:
        log_event("SECURITY", "unauthorized_prices_access", user.id if user else 0)
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    # نمایش قیمت‌های فعلی
    text = (
        f"{premium_emoji('light', '💰')} **مدیریت قیمت‌ها**\n\n"
        f"قیمت‌های فعلی (تومان / Stars):\n"
        f"• هر گیگ: {get_setting('price_per_gb', '5000')} / {get_setting('stars_per_gb', '2')}\n"
        f"• هر ماه اضافه: {get_setting('per_month_price', '30000')} / {get_setting('per_month_stars', '10')}\n"
        f"• هر یوزر اضافه: {get_setting('per_device_price', '15000')} / {get_setting('per_device_stars', '5')}\n"
        f"• نامحدود ۱۵۰G: {get_setting('unlimited_150_price', '120000')} / {get_setting('unlimited_150_stars', '80')}\n"
        f"• نامحدود بی‌نهایت: {get_setting('unlimited_inf_price', '350000')} / {get_setting('unlimited_inf_stars', '110')}\n\n"
        f"برای تغییر، روی دکمه مربوطه بزنید:"
    )
    rows = [
        build_button_row([
            build_button("هر گیگ", callback_data="admin:prices:edit:per_gb", style="primary"),
        ]),
        build_button_row([
            build_button("هر ماه اضافه", callback_data="admin:prices:edit:per_month", style="primary"),
        ]),
        build_button_row([
            build_button("هر یوزر اضافه", callback_data="admin:prices:edit:per_device", style="primary"),
        ]),
        build_button_row([
            build_button("نامحدود ۱۵۰G", callback_data="admin:prices:edit:unlimited_150", style="primary"),
        ]),
        build_button_row([
            build_button("نامحدود بی‌نهایت", callback_data="admin:prices:edit:unlimited_inf", style="primary"),
        ]),
        build_button_row([
            build_button("بازگشت", callback_data="admin:main", style="danger", premium_emoji_key="back"),
        ]),
    ]
    await callback.message.edit_text(rich_message=build_rich_message(text, rows))
    await callback.answer()


# ============================================================
# انتخاب آیتم → دریافت مقدار جدید
# ============================================================

@router.callback_query(F.data.startswith("admin:prices:edit:"))
async def edit_price_item(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    if not user or user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    item = callback.data.split(":")[3]
    await state.update_data(price_item=item)
    await state.set_state(PriceStates.waiting_value)

    labels = {
        "per_gb": "هر گیگ",
        "per_month": "هر ماه اضافه",
        "per_device": "هر یوزر اضافه",
        "unlimited_150": "نامحدود ۱۵۰G",
        "unlimited_inf": "نامحدود بی‌نهایت",
    }
    label = labels.get(item, item)

    text = (
        f"{premium_emoji('light', '💰')} **تغییر قیمت: {label}**\n\n"
        f"لطفاً مقدار جدید را به صورت **تومان و Stars** با فرمت `تومان/استارز` وارد کنید.\n"
        f"مثال: `6000/3`"
    )
    await callback.message.edit_text(rich_message=build_rich_message(text))
    await callback.answer()


@router.message(PriceStates.waiting_value)
async def receive_price_value(message: Message, state: FSMContext):
    user = message.from_user
    if not user or user.id != ADMIN_ID:
        return

    text = (message.text or "").strip()
    if "/" not in text:
        await message.answer("❌ فرمت نامعتبر. لطفاً به صورت `تومان/استارز` وارد کنید. مثال: `6000/3`")
        return

    parts = text.split("/", 1)
    try:
        toman = int(parts[0].strip())
        stars = int(parts[1].strip())
    except (ValueError, TypeError):
        await message.answer("❌ مقادیر باید عدد صحیح باشند.")
        return

    if toman <= 0 or stars <= 0 or toman > 100_000_000 or stars > 1_000_000:
        await message.answer("❌ مقادیر خارج از محدوده مجاز هستند.")
        return

    data = await state.get_data()
    item = data.get("price_item")

    # نگاشت به کلیدهای settings
    mapping = {
        "per_gb": ("price_per_gb", "stars_per_gb"),
        "per_month": ("per_month_price", "per_month_stars"),
        "per_device": ("per_device_price", "per_device_stars"),
        "unlimited_150": ("unlimited_150_price", "unlimited_150_stars"),
        "unlimited_inf": ("unlimited_inf_price", "unlimited_inf_stars"),
    }
    keys = mapping.get(item)
    if not keys:
        await message.answer("❌ آیتم نامعتبر.")
        await state.clear()
        return

    set_setting(keys[0], str(toman))
    set_setting(keys[1], str(stars))
    log_event("INFO", "price_updated", user.id, f"{item}: {toman}/{stars}")

    await state.clear()
    await message.answer(
        f"{premium_emoji('true', '✅')} **قیمت {item} با موفقیت به {toman:,} تومان / {stars} Stars تغییر کرد.**"
    )
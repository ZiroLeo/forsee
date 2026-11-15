import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID, DEFAULT_PRICES_TOMAN, DEFAULT_PRICES_STARS, MAX_MONTHS
from database import (
    create_product, list_products, get_connection, set_setting, get_setting, log_event
)
from rich import build_rich_message, premium_emoji, build_button_row, build_button
from utils import rate_limiter, calculate_price_toman, calculate_price_stars

logger = logging.getLogger(__name__)
router = Router(name="admin_products")


class ProductStates(StatesGroup):
    waiting_kind = State()
    waiting_volume = State()
    waiting_months = State()
    waiting_manual_price = State()


# ============================================================
# منوی محصولات
# ============================================================

@router.callback_query(F.data == "admin:products:menu")
async def products_menu(callback: CallbackQuery):
    user = callback.from_user
    if not user or user.id != ADMIN_ID:
        log_event("SECURITY", "unauthorized_products_access", user.id if user else 0)
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    products = list_products(active_only=False)
    lines = [f"{premium_emoji('shop', '🛒')} **مدیریت محصولات**\n"]
    if not products:
        lines.append("هیچ محصولی ثبت نشده است.")
    else:
        for p in products:
            kind_fa = "حجمی" if p["kind"] == "vol" else "نامحدود"
            vol = p["volume_gb"] if p["volume_gb"] > 0 else "بی‌نهایت"
            lines.append(
                f"• `{p['id']}` | {kind_fa} | {vol}G | {p['days']} روز | "
                f"{p['price_toman']:,} تومان / {p['price_stars']} ⭐"
            )

    text = "\n".join(lines)
    rows = [
        build_button_row([
            build_button("افزودن محصول", callback_data="admin:products:add", style="success", premium_emoji_key="gift"),
            build_button("ویرایش قیمت", callback_data="admin:products:edit_price", style="primary", premium_emoji_key="light"),
        ]),
        build_button_row([
            build_button("بازگشت", callback_data="admin:main", style="danger", premium_emoji_key="back"),
        ]),
    ]
    await callback.message.edit_text(rich_message=build_rich_message(text, rows))
    await callback.answer()


# ============================================================
# افزودن محصول جدید
# ============================================================

@router.callback_query(F.data == "admin:products:add")
async def add_product_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    await state.set_state(ProductStates.waiting_kind)
    text = f"{premium_emoji('shop', '🛒')} **نوع محصول را انتخاب کنید:**"
    rows = [
        build_button_row([
            build_button("حجمی", callback_data="admin:products:kind:vol", style="primary"),
            build_button("نامحدود", callback_data="admin:products:kind:unl", style="primary"),
        ]),
    ]
    await callback.message.edit_text(rich_message=build_rich_message(text, rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:products:kind:"))
async def product_kind_selected(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split(":")[3]
    await state.update_data(kind=kind)
    await state.set_state(ProductStates.waiting_volume)
    text = f"{premium_emoji('light', '📦')} **حجم محصول را به گیگابایت وارد کنید:**\n(برای بی‌نهایت عدد 0)"
    await callback.message.edit_text(rich_message=build_rich_message(text))
    await callback.answer()


@router.message(ProductStates.waiting_volume)
async def product_volume_received(message: Message, state: FSMContext):
    try:
        volume = float(message.text.strip())
        if volume < 0 or volume > 10000:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ حجم نامعتبر. عددی بین ۰ تا ۱۰۰۰۰ وارد کنید.")
        return

    await state.update_data(volume_gb=volume)
    await state.set_state(ProductStates.waiting_months)
    text = f"{premium_emoji('light', '📅')} **مدت محصول را به ماه وارد کنید:**\n(حداکثر {MAX_MONTHS} ماه)"
    await message.answer_rich(rich_message=build_rich_message(text))


@router.message(ProductStates.waiting_months)
async def product_months_received(message: Message, state: FSMContext):
    try:
        months = int(message.text.strip())
        if months < 1 or months > MAX_MONTHS:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(f"❌ مدت نامعتبر. عددی بین ۱ تا {MAX_MONTHS} وارد کنید.")
        return

    data = await state.get_data()
    kind = data["kind"]
    volume = data["volume_gb"]
    days = months * 30

    # محاسبه قیمت پیش‌فرض
    is_unl = (volume == 0 or kind == "unl")
    price_toman = calculate_price_toman(volume, days, 2, is_unl)
    price_stars = calculate_price_stars(volume, days, 2, is_unl)

    await state.update_data(days=days, price_toman=price_toman, price_stars=price_stars)

    text = (
        f"{premium_emoji('true', '✅')} **خلاصه محصول:**\n\n"
        f"نوع: {'نامحدود' if is_unl else 'حجمی'}\n"
        f"حجم: {volume if volume > 0 else 'بی‌نهایت'} گیگ\n"
        f"مدت: {months} ماه ({days} روز)\n"
        f"قیمت پیش‌فرض: {price_toman:,} تومان / {price_stars} ⭐\n\n"
        f"آیا این قیمت را تأیید می‌کنید؟"
    )
    rows = [
        build_button_row([
            build_button("تأیید و افزودن", callback_data="admin:products:confirm", style="success", premium_emoji_key="true"),
            build_button("تغییر قیمت", callback_data="admin:products:change_price", style="primary", premium_emoji_key="light"),
        ]),
    ]
    await message.answer_rich(rich_message=build_rich_message(text, rows))


@router.callback_query(F.data == "admin:products:change_price")
async def product_change_price(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProductStates.waiting_manual_price)
    text = f"{premium_emoji('light', '💰')} **قیمت دلخواه را به صورت `تومان/استارز` وارد کنید.**\nمثال: `150000/50`"
    await callback.message.edit_text(rich_message=build_rich_message(text))
    await callback.answer()


@router.message(ProductStates.waiting_manual_price)
async def product_manual_price_received(message: Message, state: FSMContext):
    text = message.text.strip()
    if "/" not in text:
        await message.answer("❌ فرمت نامعتبر. مثال: `150000/50`")
        return
    try:
        toman, stars = map(int, text.split("/", 1))
    except (ValueError, TypeError):
        await message.answer("❌ مقادیر باید عدد باشند.")
        return
    if toman <= 0 or stars <= 0:
        await message.answer("❌ مقادیر باید مثبت باشند.")
        return

    await state.update_data(price_toman=toman, price_stars=stars)
    # بازگشت به مرحله تأیید (بدون تغییر بقیه)
    data = await state.get_data()
    await state.set_state(None)
    text = (
        f"{premium_emoji('true', '✅')} **قیمت جدید ثبت شد.**\n\n"
        f"قیمت: {toman:,} تومان / {stars} ⭐\n\n"
        f"برای افزودن، روی دکمه زیر بزنید."
    )
    rows = [build_button_row([
        build_button("تأیید و افزودن", callback_data="admin:products:confirm", style="success", premium_emoji_key="true"),
    ])]
    await message.answer_rich(rich_message=build_rich_message(text, rows))


@router.callback_query(F.data == "admin:products:confirm")
async def product_confirm(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    data = await state.get_data()
    try:
        product_id = create_product(
            kind=data["kind"],
            volume_gb=data["volume_gb"],
            days=data["days"],
            price_toman=data["price_toman"],
            price_stars=data["price_stars"]
        )
    except Exception as e:
        logger.exception(f"Product creation failed: {e}")
        await callback.answer("خطا در ساخت محصول.", show_alert=True)
        return

    log_event("INFO", "product_created", callback.from_user.id, f"product_id={product_id}")
    await state.clear()
    text = f"{premium_emoji('true', '✅')} **محصول با شناسه `{product_id}` با موفقیت اضافه شد.**"
    await callback.message.edit_text(rich_message=build_rich_message(text))
    await callback.answer()


# ============================================================
# ویرایش قیمت محصول موجود
# ============================================================

@router.callback_query(F.data == "admin:products:edit_price")
async def edit_product_price_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    text = f"{premium_emoji('light', '💰')} **شناسه محصولی که می‌خواهید قیمتش را تغییر دهید وارد کنید:**"
    await state.set_state(ProductStates.waiting_manual_price)  # استفاده موقت از این state برای دریافت ID
    await state.update_data(editing_product_id=True)
    await callback.message.edit_text(rich_message=build_rich_message(text))
    await callback.answer()
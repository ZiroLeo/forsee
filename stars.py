import logging
import uuid
from aiogram import Router, F
from aiogram.types import (
    Message, PreCheckoutQuery, LabeledPrice, CallbackQuery
)

from config import ADMIN_ID
from database import (
    get_user, create_stars_invoice, get_stars_invoice, update_stars_invoice_status,
    register_stars_charge, update_stars_charge_status, create_subscription,
    reserve_config_number, release_config_number, increment_total_purchases,
    add_referral_commission, log_event, get_balance
)
from paxiva import PaxivaClient, PaxivaError
from rich import build_rich_message, premium_emoji
from utils import generate_idempotency_key

logger = logging.getLogger(__name__)
router = Router(name="stars_payment")


# ============================================================
# شروع پرداخت با Stars (از handlers/buy.py صدا زده می‌شود)
# ============================================================

@router.callback_query(F.data == "buy:pay:stars")
async def pay_with_stars(callback: CallbackQuery, state, bot):
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    # خواندن اطلاعات سفارش از state
    data = await state.get_data()
    volume_gb = data.get("volume_gb", 0)
    days = data.get("days", 30)
    devices = data.get("devices", 2)
    price_stars = data.get("price_stars", 0)

    if price_stars <= 0:
        await callback.answer("خطا در محاسبه قیمت.", show_alert=True)
        return

    # تولید payload یکتا و ذخیره فاکتور در دیتابیس
    payload = f"stars-{user.id}-{uuid.uuid4().hex[:12]}"
    inv_id = create_stars_invoice(
        payload=payload,
        telegram_id=user.id,
        volume_gb=volume_gb,
        days=days,
        devices=devices,
        amount_stars=price_stars
    )
    if not inv_id:
        await callback.answer("خطا در ایجاد فاکتور.", show_alert=True)
        return

    # ارسال فاکتور Stars
    try:
        await bot.send_invoice(
            chat_id=user.id,
            title=f"خرید کانفیگ {volume_gb if volume_gb > 0 else 'بی‌نهایت'} گیگ",
            description=f"مدت: {days} روز | دستگاه: {devices}",
            payload=payload,
            provider_token="",  # برای Stars خالی است
            currency="XTR",
            prices=[LabeledPrice(label="کانفیگ", amount=price_stars)],
            start_parameter="buy_stars"
        )
        await callback.answer("فاکتور ارسال شد. لطفاً پرداخت کنید.")
    except Exception as e:
        logger.exception(f"Failed to send stars invoice: {e}")
        await callback.answer("خطا در ارسال فاکتور.", show_alert=True)


# ============================================================
# pre_checkout_query (تأیید قبل از پرداخت)
# ============================================================

@router.pre_checkout_query()
async def pre_checkout(pre_checkout: PreCheckoutQuery):
    payload = pre_checkout.invoice_payload
    inv = get_stars_invoice(payload)

    if not inv or inv["status"] != "pending":
        await pre_checkout.answer(ok=False, error_message="فاکتور نامعتبر یا منقضی شده است.")
        return

    if inv["amount_stars"] != pre_checkout.total_amount:
        await pre_checkout.answer(ok=False, error_message="مبلغ فاکتور با انتظار مطابقت ندارد.")
        log_event("SECURITY", "stars_amount_mismatch", inv["telegram_id"], f"payload={payload}")
        return

    await pre_checkout.answer(ok=True)


# ============================================================
# successful_payment (پس از پرداخت موفق)
# ============================================================

@router.message(F.successful_payment)
async def successful_payment(message: Message, paxiva: PaxivaClient, bot):
    payment = message.successful_payment
    payload = payment.invoice_payload
    charge_id = payment.telegram_payment_charge_id
    user_id = message.from_user.id

    # ۱. ضد تکرار: INSERT OR IGNORE در stars_charges
    is_new = register_stars_charge(
        charge_id=charge_id,
        telegram_id=user_id,
        payload=payload,
        amount_stars=payment.total_amount
    )
    if not is_new:
        logger.warning(f"Duplicate stars charge: {charge_id}")
        return

    # ۲. خواندن فاکتور
    inv = get_stars_invoice(payload)
    if not inv or inv["status"] != "pending":
        logger.error(f"Invalid stars invoice: {payload}")
        await _refund(bot, user_id, charge_id, message)
        return

    update_stars_invoice_status(payload, "paid")

    # ۳. ساخت کانفیگ
    config_number = reserve_config_number(is_test=False)
    config_name = f"iMan-{config_number}"
    idem_key = generate_idempotency_key(f"stars-{user_id}-{config_number}")

    try:
        client_data = await paxiva.create_client(
            name=config_name,
            volume_gb=inv["volume_gb"],
            days=inv["days"],
            devices=inv["devices"],
            idempotency_key=idem_key
        )
        paxiva_id = client_data.get("id")
        link = client_data.get("link", "")

        sub_id = create_subscription(
            telegram_id=user_id,
            config_number=config_number,
            config_name=config_name,
            kind="vol",
            volume_gb=inv["volume_gb"],
            days=inv["days"],
            devices=inv["devices"],
            price_toman=0,
            price_stars=inv["amount_stars"],
            paxiva_client_id=paxiva_id,
            link=link
        )

        increment_total_purchases(user_id)
        add_referral_commission(user_id, 0, sub_id, "stars_purchase")  # پورسانت Stars جداگانه محاسبه نمی‌شود
        update_stars_invoice_status(payload, "delivered")
        update_stars_charge_status(charge_id, "delivered")

        success_text = (
            f"{premium_emoji('true', '✅')} **پرداخت با Stars با موفقیت انجام شد!**\n\n"
            f"🔹 کانفیگ: `{config_name}`\n"
            f"📦 حجم: {inv['volume_gb'] if inv['volume_gb'] > 0 else 'بی‌نهایت'} گیگ\n"
            f"📅 مدت: {inv['days']} روز\n"
            f"🔗 لینک:\n`{link}`"
        )
        await message.answer_rich(rich_message=build_rich_message(success_text))
        log_event("INFO", "stars_purchase_success", user_id, f"sub_id={sub_id}, stars={inv['amount_stars']}")

    except PaxivaError as e:
        logger.error(f"PAXIVA error after stars payment: {e}")
        release_config_number(config_number, is_test=False)
        update_stars_invoice_status(payload, "refunded")
        await _refund(bot, user_id, charge_id, message)
        log_event("ERROR", "stars_paxiva_failed", user_id, f"payload={payload}: {e.message}")

    except Exception as e:
        logger.exception(f"Unexpected error after stars payment: {e}")
        release_config_number(config_number, is_test=False)
        update_stars_invoice_status(payload, "refunded")
        await _refund(bot, user_id, charge_id, message)
        log_event("ERROR", "stars_unexpected", user_id, f"payload={payload}: {str(e)}")


# ============================================================
# Refund
# ============================================================

async def _refund(bot, user_id: int, charge_id: str, message: Message = None):
    try:
        ok = await bot.refund_star_payment(
            user_id=user_id,
            telegram_payment_charge_id=charge_id
        )
        if ok:
            update_stars_charge_status(charge_id, "refunded")
            if message:
                await message.answer(
                    "⚠️ ساخت کانفیگ انجام نشد. مبلغ Stars شما بازگشت داده شد."
                )
            log_event("INFO", "stars_refund_ok", user_id, f"charge={charge_id}")
        else:
            logger.error(f"Refund failed for {user_id} charge={charge_id}")
            if message:
                await message.answer(
                    "⚠️ ساخت کانفیگ انجام نشد و بازگشت مبلغ با خطا مواجه شد. لطفاً با پشتیبانی تماس بگیرید."
                )
            log_event("ERROR", "stars_refund_failed", user_id, f"charge={charge_id}")
    except Exception as e:
        logger.exception(f"Refund exception: {e}")
        log_event("ERROR", "stars_refund_exception", user_id, f"charge={charge_id}: {str(e)}")
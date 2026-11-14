import asyncio
import html
import logging
from typing import Any, Optional

from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import (
    DEFAULT_PRICES_TOMAN,
    DEFAULT_PRICES_STARS,
    MAX_DEVICES_DEFAULT,
    MAX_MONTHS,
    PREMIUM_EMOJIS,
    PREMIUM_EMOJI_ENABLED,
)

from database import (
    add_balance,
    add_referral_commission,
    consume_discount_code,
    create_subscription,
    deduct_balance,
    get_balance,
    get_discount_code,
    get_setting,
    hard_delete_subscription,
    increment_total_purchases,
    log_event,
)

from paxiva import PaxivaClient, PaxivaError

from services.counter import (
    release_reserved_number,
    reserve_new_config_number,
)

from rich import premium_emoji

from utils import (
    calculate_price_stars,
    calculate_price_toman,
    generate_idempotency_key,
    rate_limiter,
    validate_discount_code,
)


logger = logging.getLogger(__name__)
router = Router(name="buy")


# ============================================================
# CONSTANTS
# ============================================================

VOLUME_OPTIONS = {
    "10": 10,
    "20": 20,
    "30": 30,
    "50": 50,
    "100": 100,
    "200": 200,
    "500": 500,
}

UNLIMITED_OPTIONS = {
    "unl150": 150,
    "unl_inf": 0,
}

MAX_DEVICES = 10

SERVICE_VOLUME = "vol"
SERVICE_UNLIMITED = "unl"


# جلوگیری از دوبار خرید هم‌زمان در یک پردازش
_user_purchase_locks: dict[int, asyncio.Lock] = {}


class BuyStates(StatesGroup):
    waiting_discount_code = State()


# ============================================================
# LOCK
# ============================================================

def _user_lock(user_id: int) -> asyncio.Lock:
    lock = _user_purchase_locks.get(user_id)

    if lock is None:
        lock = asyncio.Lock()
        _user_purchase_locks[user_id] = lock

    return lock


# ============================================================
# LOGGING
# ============================================================

def _safe_log(
    level: str,
    event: str,
    user_id: int,
    detail: str = "",
) -> None:
    try:
        log_event(
            level,
            event,
            user_id,
            detail[:1000],
        )
    except Exception:
        logger.exception(
            "Could not write event log: %s",
            event,
        )


# ============================================================
# PREMIUM EMOJI / INLINE BUTTONS
# ============================================================

def _emoji_id(key: str) -> Optional[str]:
    if not PREMIUM_EMOJI_ENABLED:
        return None

    emoji_id = PREMIUM_EMOJIS.get(key)

    if not emoji_id:
        logger.warning(
            "Premium emoji is missing: %s",
            key,
        )
        return None

    return str(emoji_id)


def _button(
    text: str,
    callback_data: str,
    *,
    style: str = "primary",
    emoji_key: Optional[str] = None,
) -> InlineKeyboardButton:

    if len(callback_data.encode("utf-8")) > 64:
        raise ValueError("Callback data exceeds Telegram limit.")

    kwargs = {
        "text": text,
        "callback_data": callback_data,
        "style": style,
    }

    emoji_id = _emoji_id(emoji_key) if emoji_key else None

    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id

    return InlineKeyboardButton(**kwargs)


def _keyboard(
    rows: list[list[InlineKeyboardButton]],
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        inline_keyboard=rows,
    )


# ============================================================
# BUY KEYBOARDS
# ============================================================

def buy_type_selection_keyboard() -> InlineKeyboardMarkup:

    return _keyboard([
        [
            _button(
                "سرویس حجمی",
                "buy:type:vol",
                style="primary",
                emoji_key="shop",
            ),
            _button(
                "سرویس نامحدود",
                "buy:type:unl",
                style="primary",
                emoji_key="world",
            ),
        ],
        [
            _button(
                "بازگشت به منوی اصلی",
                "menu:main",
                style="danger",
                emoji_key="back",
            ),
        ],
    ])


def buy_volume_selection_keyboard(
    service_type: str,
) -> InlineKeyboardMarkup:

    rows = []

    if service_type == SERVICE_VOLUME:

        rows.extend([
            [
                _button("۱۰ گیگ", "buy:vol:10"),
                _button("۲۰ گیگ", "buy:vol:20"),
            ],
            [
                _button("۳۰ گیگ", "buy:vol:30"),
                _button("۵۰ گیگ", "buy:vol:50"),
            ],
            [
                _button("۱۰۰ گیگ", "buy:vol:100"),
                _button("۲۰۰ گیگ", "buy:vol:200"),
            ],
            [
                _button("۵۰۰ گیگ", "buy:vol:500"),
            ],
        ])

    elif service_type == SERVICE_UNLIMITED:

        rows.extend([
            [
                _button(
                    "نامحدود منصفانه (۱۵۰ گیگ)",
                    "buy:vol:unl150",
                    style="success",
                    emoji_key="world",
                ),
            ],
            [
                _button(
                    "نامحدود بی‌نهایت",
                    "buy:vol:unl_inf",
                    style="success",
                    emoji_key="diamond",
                ),
            ],
        ])

    else:
        raise ValueError("Invalid service type.")

    rows.append([
        _button(
            "بازگشت",
            "buy:main",
            style="danger",
            emoji_key="back",
        ),
    ])

    return _keyboard(rows)


def buy_time_selection_keyboard(
    current_months: int,
) -> InlineKeyboardMarkup:

    return _keyboard([
        [
            _button(
                "-",
                "buy:time:dec",
                style="danger",
            ),
            _button(
                f"{current_months} ماه",
                "buy:time:noop",
                style="primary",
            ),
            _button(
                "+",
                "buy:time:inc",
                style="success",
            ),
        ],
        [
            _button(
                "تأیید و ادامه",
                "buy:time:confirm",
                style="success",
                emoji_key="true",
            ),
        ],
        [
            _button(
                "بازگشت",
                "buy:vol",
                style="danger",
                emoji_key="back",
            ),
        ],
    ])


def buy_device_selection_keyboard(
    current_devices: int,
) -> InlineKeyboardMarkup:

    return _keyboard([
        [
            _button(
                "-",
                "buy:dev:dec",
                style="danger",
            ),
            _button(
                f"{current_devices} دستگاه",
                "buy:dev:noop",
            ),
            _button(
                "+",
                "buy:dev:inc",
                style="success",
            ),
        ],
        [
            _button(
                "تأیید و ادامه",
                "buy:dev:confirm",
                style="success",
                emoji_key="true",
            ),
        ],
        [
            _button(
                "بازگشت",
                "buy:time",
                style="danger",
                emoji_key="back",
            ),
        ],
    ])


def buy_discount_keyboard() -> InlineKeyboardMarkup:

    return _keyboard([
        [
            _button(
                "وارد کردن کد تخفیف",
                "buy:discount:enter",
                style="primary",
                emoji_key="gift",
            ),
        ],
        [
            _button(
                "بدون کد تخفیف ادامه می‌دهم",
                "buy:discount:skip",
                style="success",
            ),
        ],
        [
            _button(
                "بازگشت",
                "buy:dev",
                style="danger",
                emoji_key="back",
            ),
        ],
    ])


def buy_payment_keyboard(
    price_toman: int,
    price_stars: int,
) -> InlineKeyboardMarkup:

    return _keyboard([
        [
            _button(
                f"پرداخت با کیف پول | {price_toman:,} تومان",
                "buy:pay:wallet",
                style="success",
                emoji_key="wallet",
            ),
        ],
        [
            _button(
                f"پرداخت با Stars | {price_stars}",
                "buy:pay:stars",
                style="primary",
                emoji_key="stars",
            ),
        ],
        [
            _button(
                "بازگشت",
                "buy:discount",
                style="danger",
                emoji_key="back",
            ),
        ],
    ])


# ============================================================
# MESSAGE HELPERS
# ============================================================

async def _edit_or_answer(
    message: Optional[Message],
    text: str,
    reply_markup=None,
) -> None:

    if not message:
        return

    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
        )

    except TelegramBadRequest as exc:

        if "message is not modified" in str(exc).lower():
            return

        try:
            await message.answer(
                text,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception(
                "Could not send fallback message."
            )

    except Exception:

        logger.exception(
            "Could not edit purchase message."
        )

        try:
            await message.answer(
                text,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception(
                "Could not send fallback message."
            )


def _safe_text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _is_valid_panel_link(link: Any) -> bool:
    if not isinstance(link, str):
        return False

    link = link.strip()

    if not link or len(link) > 4000:
        return False

    parsed = urlparse(link)

    return (
        parsed.scheme in {"https", "http"}
        and bool(parsed.netloc)
    )


# ============================================================
# SERVICE VALIDATION
# ============================================================

def _valid_purchase_data(
    data: dict[str, Any],
) -> bool:

    try:
        volume = float(data["volume_gb"])
        days = int(data["days"])
        devices = int(data["devices"])
        volume_key = str(data["volume_key"])
        service_type = str(data["service_type"])

    except (KeyError, TypeError, ValueError):
        return False

    if not 1 <= devices <= MAX_DEVICES:
        return False

    if service_type == SERVICE_VOLUME:

        if volume_key not in VOLUME_OPTIONS:
            return False

        if volume != VOLUME_OPTIONS[volume_key]:
            return False

        if not 30 <= days <= MAX_MONTHS * 30:
            return False

        if days % 30 != 0:
            return False

        return True

    if service_type == SERVICE_UNLIMITED:

        if volume_key not in UNLIMITED_OPTIONS:
            return False

        if volume != UNLIMITED_OPTIONS[volume_key]:
            return False

        if volume_key == "unl_inf":
            return days == 0

        if volume_key == "unl150":
            return (
                30 <= days <= MAX_MONTHS * 30
                and days % 30 == 0
            )

    return False


# ============================================================
# PRICE CALCULATION
# ============================================================

def _unlimited_price(
    prices: dict,
    candidates: tuple[str, ...],
) -> int:

    for key in candidates:

        value = prices.get(key)

        if value is None:
            continue

        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue

        if amount > 0:
            return amount

    raise ValueError(
        "Unlimited service price is not configured."
    )


def _calculate_prices(
    volume_gb: float,
    days: int,
    devices: int,
    volume_key: str,
) -> tuple[int, int]:

    if volume_key == "unl_inf":

        toman = _unlimited_price(
            DEFAULT_PRICES_TOMAN,
            (
                "unlimited_inf",
                "unlimited_infinite",
                "unlimited",
                "unl_inf",
            ),
        )

        stars = _unlimited_price(
            DEFAULT_PRICES_STARS,
            (
                "unlimited_inf",
                "unlimited_infinite",
                "unlimited",
                "unl_inf",
            ),
        )

        extra_devices = max(
            0,
            devices - MAX_DEVICES_DEFAULT,
        )

        toman += extra_devices * int(
            DEFAULT_PRICES_TOMAN.get(
                "per_device",
                15000,
            )
        )

        stars += extra_devices * int(
            DEFAULT_PRICES_STARS.get(
                "per_device",
                5,
            )
        )

        return toman, stars

    # حجمی و نامحدود منصفانه ۱۵۰ گیگ
    # طبق مدل قیمت‌گذاری فعلی، قیمت بر اساس حجم محاسبه می‌شود.

    return (
        calculate_price_toman(
            volume_gb,
            days,
            devices,
            is_unlimited=False,
        ),
        calculate_price_stars(
            volume_gb,
            days,
            devices,
            is_unlimited=False,
        ),
    )


def _get_current_discount(
    data: dict,
) -> tuple[int, Optional[int]]:

    discount_id = data.get("discount_id")

    if discount_id is None:
        return 0, None

    try:
        discount_id = int(discount_id)
        code = get_discount_code(
            str(data.get("discount_code", ""))
        )

        if not code:
            return 0, None

        if int(code["id"]) != discount_id:
            return 0, None

        if not code.get("is_active"):
            return 0, None

        if int(code["used_count"]) >= int(code["max_uses"]):
            return 0, None

        percent = int(code["percent"])

        if not 0 <= percent <= 100:
            return 0, None

        return percent, discount_id

    except Exception:
        logger.exception(
            "Could not validate discount code."
        )
        return 0, None


def _build_order_prices(
    data: dict,
) -> tuple[int, int, int, Optional[int]]:

    if not _valid_purchase_data(data):
        raise ValueError("Invalid purchase data.")

    volume = float(data["volume_gb"])
    days = int(data["days"])
    devices = int(data["devices"])
    volume_key = str(data["volume_key"])

    toman, stars = _calculate_prices(
        volume,
        days,
        devices,
        volume_key,
    )

    discount_percent, discount_id = _get_current_discount(data)

    toman = toman * (100 - discount_percent) // 100
    stars = stars * (100 - discount_percent) // 100

    if toman < 0 or stars < 0:
        raise ValueError("Invalid calculated price.")

    return (
        toman,
        stars,
        discount_percent,
        discount_id,
    )


# ============================================================
# DEVICE SELECTION
# ============================================================

async def _show_device_selection(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    data = await state.get_data()

    devices = int(
        data.get(
            "devices",
            MAX_DEVICES_DEFAULT,
        )
    )

    extra_devices = max(
        0,
        devices - MAX_DEVICES_DEFAULT,
    )

    extra_price = (
        extra_devices
        * int(DEFAULT_PRICES_TOMAN.get("per_device", 15000))
    )

    text = (
        f"{premium_emoji('telegram', '●')} "
        "<b>تعداد دستگاه‌های مجاز</b>\n\n"
        f"دستگاه انتخاب‌شده: <b>{devices}</b>\n"
        f"دستگاه رایگان: <b>{MAX_DEVICES_DEFAULT}</b>\n"
        f"هزینه دستگاه اضافه: <b>{extra_price:,} تومان</b>\n\n"
        "تعداد دستگاه‌های موردنیاز را انتخاب کن."
    )

    await _edit_or_answer(
        callback.message,
        text,
        buy_device_selection_keyboard(devices),
    )


# ============================================================
# INVOICE
# ============================================================

async def _show_invoice(
    event: CallbackQuery | Message,
    state: FSMContext,
    *,
    from_callback: bool,
) -> None:

    data = await state.get_data()

    if not _valid_purchase_data(data):

        await state.clear()

        text = (
            f"{premium_emoji('warning', '●')} "
            "<b>اطلاعات سفارش معتبر نیست.</b>\n\n"
            "لطفاً خرید را از ابتدا شروع کن."
        )

        if from_callback:
            await _edit_or_answer(
                event.message,
                text,
            )
        else:
            await event.answer(text)

        return

    try:
        toman, stars, discount_percent, discount_id = (
            _build_order_prices(data)
        )

    except ValueError:

        logger.exception(
            "Could not calculate purchase invoice."
        )

        text = (
            f"{premium_emoji('warning', '●')} "
            "<b>قیمت این سرویس به‌درستی تنظیم نشده است.</b>\n\n"
            "لطفاً با پشتیبانی تماس بگیر."
        )

        if from_callback:
            await _edit_or_answer(
                event.message,
                text,
            )
        else:
            await event.answer(text)

        return

    await state.update_data(
        price_toman=toman,
        price_stars=stars,
        discount_id=discount_id,
        discount_percent=discount_percent,
    )

    volume_key = str(data["volume_key"])
    volume = float(data["volume_gb"])
    days = int(data["days"])
    devices = int(data["devices"])

    if volume_key == "unl_inf":
        service_name = "نامحدود بی‌نهایت"
        duration = "بدون انقضا"

    elif volume_key == "unl150":
        service_name = "نامحدود منصفانه (۱۵۰ گیگ)"
        duration = f"{days} روز"

    else:
        service_name = f"سرویس حجمی {int(volume)} گیگ"
        duration = f"{days} روز"

    text = (
        f"{premium_emoji('true', '●')} "
        "<b>فاکتور نهایی سفارش</b>\n\n"
        f"<b>نوع سرویس:</b> {service_name}\n"
        f"<b>مدت:</b> {duration}\n"
        f"<b>تعداد دستگاه:</b> {devices}\n"
        f"<b>مبلغ قابل پرداخت:</b> {toman:,} تومان\n"
        f"<b>مبلغ Stars:</b> {stars}\n"
    )

    if discount_percent:
        text += (
            f"<b>تخفیف اعمال‌شده:</b> "
            f"{discount_percent}%\n"
        )

    text += "\nروش پرداخت را انتخاب کن."

    if from_callback:

        await _edit_or_answer(
            event.message,
            text,
            buy_payment_keyboard(toman, stars),
        )

    else:

        await event.answer(
            text,
            reply_markup=buy_payment_keyboard(
                toman,
                stars,
            ),
        )


# ============================================================
# PAXIVA CLEANUP
# ============================================================

async def _delete_remote_client(
    paxiva: PaxivaClient,
    client_id: int,
) -> bool:

    if not client_id:
        return False

    try:
        await paxiva.delete_client(
            client_id,
            purge=True,
        )
        return True

    except Exception:

        logger.exception(
            "Could not delete remote client %s",
            client_id,
        )

        return False


# ============================================================
# PURCHASE PROVISIONING
# ============================================================

async def _provision_purchase(
    *,
    user_id: int,
    data: dict[str, Any],
    paxiva: PaxivaClient,
    payment_type: str,
) -> tuple[str, str]:

    """
    خروجی:
        success  -> خرید موفق
        failed   -> شکست قطعی و جبران‌شده
        pending  -> وضعیت مبهم؛ نیازمند بررسی و عدم تکرار خرید
    """

    if payment_type != "wallet":
        return (
            "failed",
            "این روش پرداخت هنوز فعال نشده است.",
        )

    if not _valid_purchase_data(data):
        return (
            "failed",
            "اطلاعات سفارش معتبر نیست.",
        )

    try:
        price_toman, _, _, discount_id = (
            _build_order_prices(data)
        )
    except Exception:
        logger.exception("Purchase price validation failed.")
        return (
            "failed",
            "محاسبه مبلغ سفارش ناموفق بود.",
        )

    volume = float(data["volume_gb"])
    days = int(data["days"])
    devices = int(data["devices"])
    volume_key = str(data["volume_key"])

    kind = (
        "unl"
        if volume_key in UNLIMITED_OPTIONS
        else "vol"
    )

    number: Optional[int] = None
    config_name: Optional[str] = None
    client_id: Optional[int] = None
    subscription_id: Optional[int] = None

    debited = False
    create_request_started = False
    create_response_received = False
    remote_deleted = False
    local_deleted = True

    # --------------------------------------------------------
    # کسر موجودی اتمیک
    # --------------------------------------------------------

    if price_toman > 0:

        try:
            debited = deduct_balance(
                user_id,
                price_toman,
                "purchase",
                f"خرید سرویس {volume:g}GB / {days} روز",
            )

        except Exception:

            logger.exception(
                "Wallet deduction failed for user %s",
                user_id,
            )

            return (
                "failed",
                "کسر موجودی انجام نشد. لطفاً دوباره تلاش کن.",
            )

        if not debited:
            return (
                "failed",
                "موجودی کافی نیست یا کسر موجودی انجام نشد.",
            )

    # --------------------------------------------------------
    # ساخت سرویس
    # --------------------------------------------------------

    try:

        number = reserve_new_config_number(
            is_test=False,
        )

        if not number:
            raise RuntimeError(
                "Could not reserve config number."
            )

        config_name = f"iMan-{number}"

        idempotency_key = generate_idempotency_key(
            f"buy-{user_id}-{number}"
        )

        # از این لحظه ممکن است درخواست به پنل رسیده باشد.
        create_request_started = True

        client_data = await paxiva.create_client(
            name=config_name,
            volume_gb=volume,
            days=days,
            devices=devices,
            idempotency_key=idempotency_key,
            kind=kind,
        )

        create_response_received = True

        if not isinstance(client_data, dict):
            raise RuntimeError(
                "Invalid PAXIVA response."
            )

        try:
            client_id = int(client_data["id"])
        except (KeyError, TypeError, ValueError):
            raise RuntimeError(
                "PAXIVA response has no valid client ID."
            )

        link = client_data.get("link")

        if not _is_valid_panel_link(link):
            raise RuntimeError(
                "PAXIVA returned an invalid subscription link."
            )

        # ----------------------------------------------------
        # ثبت اشتراک در دیتابیس
        # ----------------------------------------------------

        subscription_id = create_subscription(
            telegram_id=user_id,
            config_number=number,
            config_name=config_name,
            kind=kind,
            volume_gb=volume,
            days=days,
            devices=devices,
            price_toman=price_toman,
            price_stars=0,
            paxiva_client_id=client_id,
            link=link,
        )

        if not subscription_id:
            raise RuntimeError(
                "Could not save subscription in database."
            )

        # ----------------------------------------------------
        # مصرف کد تخفیف
        # ----------------------------------------------------

        if discount_id is not None:

            if not consume_discount_code(
                int(discount_id),
                user_id,
            ):
                raise RuntimeError(
                    "Discount code could not be consumed."
                )

        # ----------------------------------------------------
        # ثبت آمار و پورسانت
        # ----------------------------------------------------

        try:
            increment_total_purchases(user_id)
        except Exception:
            logger.exception(
                "Could not increment purchase count."
            )

        try:
            add_referral_commission(
                user_id,
                price_toman,
                int(subscription_id),
                "purchase",
            )
        except Exception:
            logger.exception(
                "Referral commission failed for subscription %s",
                subscription_id,
            )

        _safe_log(
            "INFO",
            "purchase_success",
            user_id,
            (
                f"subscription_id={subscription_id}; "
                f"config={config_name}; "
                f"kind={kind}"
            ),
        )

        return (
            "success",
            f"{config_name}\n{link}",
        )

    except Exception as exc:

        logger.exception(
            "Purchase provisioning failed for user %s",
            user_id,
        )

        # ----------------------------------------------------
        # حالت مبهم: درخواست ارسال شده اما پاسخ دریافت نشده
        # ----------------------------------------------------

        if create_request_started and not create_response_received:

            _safe_log(
                "CRITICAL",
                "purchase_ambiguous",
                user_id,
                (
                    f"config={config_name}; "
                    f"number={number}; "
                    "PAXIVA response not received. "
                    "Manual reconciliation required."
                ),
            )

            # شماره و مبلغ را نگه می‌داریم.
            # آزاد کردن آن‌ها ممکن است باعث ساخت کانفیگ تکراری شود.

            return (
                "pending",
                (
                    "وضعیت ساخت سرویس از پنل مشخص نشد؛ "
                    "ممکن است کانفیگ ساخته شده باشد. "
                    "برای جلوگیری از خرید تکراری، سفارش متوقف شد. "
                    "لطفاً با پشتیبانی تماس بگیر."
                ),
            )

        # ----------------------------------------------------
        # اگر سرویس در پنل ساخته شده، ابتدا حذف آن را امتحان می‌کنیم
        # ----------------------------------------------------

        if client_id is not None:

            remote_deleted = await _delete_remote_client(
                paxiva,
                client_id,
            )

            if not remote_deleted:

                _safe_log(
                    "CRITICAL",
                    "purchase_orphan_client",
                    user_id,
                    (
                        f"config={config_name}; "
                        f"client_id={client_id}; "
                        "Remote deletion failed."
                    ),
                )

                # سرویس ممکن است فعال باشد؛ وجه را خودکار برنمی‌گردانیم.
                return (
                    "pending",
                    (
                        "ساخت سرویس با مشکل مواجه شد و حذف آن از پنل "
                        "تأیید نشد. وضعیت سفارش برای بررسی پشتیبانی "
                        "نگه داشته شد."
                    ),
                )

        # ----------------------------------------------------
        # حذف رکورد محلی در صورت ساخته‌شدن
        # ----------------------------------------------------

        if subscription_id is not None:

            try:
                local_deleted = hard_delete_subscription(
                    int(subscription_id)
                )
            except Exception:
                local_deleted = False
                logger.exception(
                    "Could not rollback local subscription."
                )

            if not local_deleted:

                _safe_log(
                    "CRITICAL",
                    "purchase_local_rollback_failed",
                    user_id,
                    f"subscription_id={subscription_id}",
                )

                return (
                    "pending",
                    (
                        "وضعیت ثبت سفارش در دیتابیس مشخص نیست. "
                        "لطفاً برای بررسی با پشتیبانی تماس بگیر."
                    ),
                )

        # ----------------------------------------------------
        # آزادسازی شماره فقط در صورت اطمینان از عدم وجود سرویس
        # ----------------------------------------------------

        if number is not None:

            try:
                release_reserved_number(
                    number,
                    is_test=False,
                )
            except Exception:

                logger.exception(
                    "Could not release config number %s",
                    number,
                )

        # ----------------------------------------------------
        # بازگشت وجه
        # ----------------------------------------------------

        if debited and price_toman > 0:

            try:

                refunded = add_balance(
                    user_id,
                    price_toman,
                    "refund",
                    f"بازگشت وجه سفارش ناموفق {config_name or ''}",
                )

                if not refunded:

                    _safe_log(
                        "CRITICAL",
                        "purchase_refund_failed",
                        user_id,
                        (
                            f"amount={price_toman}; "
                            f"config={config_name}"
                        ),
                    )

                    return (
                        "pending",
                        (
                            "خرید ناموفق بود اما بازگشت وجه "
                            "تأیید نشد. لطفاً فوراً با پشتیبانی تماس بگیر."
                        ),
                    )

            except Exception:

                logger.exception(
                    "Refund failed for user %s",
                    user_id,
                )

                return (
                    "pending",
                    (
                        "خرید ناموفق بود اما بازگشت وجه "
                        "تأیید نشد. لطفاً فوراً با پشتیبانی تماس بگیر."
                    ),
                )

        _safe_log(
            "ERROR",
            "purchase_failed",
            user_id,
            (
                f"config={config_name}; "
                f"error={type(exc).__name__}"
            ),
        )

        if isinstance(exc, PaxivaError):
            return (
                "failed",
                "پنل نتوانست سرویس را ایجاد کند. در صورت کسر وجه، بازگشت وجه انجام شده است.",
            )

        return (
            "failed",
            "ساخت سرویس کامل نشد. در صورت کسر وجه، بازگشت وجه انجام شده است.",
        )


# ============================================================
# START BUY
# ============================================================

@router.callback_query(F.data == "menu:buy")
async def start_buy(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    user = callback.from_user

    if not user:
        return

    if not rate_limiter.is_allowed(user.id):

        await _edit_or_answer(
            callback.message,
            "لطفاً کمی صبر کن و دوباره تلاش کن.",
        )
        return

    if get_setting("sales_open", "1") == "0":

        text = (
            f"{premium_emoji('warning', '●')} "
            "<b>فروش موقتاً بسته است.</b>\n\n"
            "لطفاً اطلاعیه‌های کانال را دنبال کن."
        )

        await _edit_or_answer(
            callback.message,
            text,
        )
        return

    await state.clear()

    text = (
        f"{premium_emoji('shop', '●')} "
        "<b>خرید سرویس</b>\n\n"
        "نوع سرویس موردنظرت را انتخاب کن."
    )

    await _edit_or_answer(
        callback.message,
        text,
        buy_type_selection_keyboard(),
    )


# ============================================================
# SELECT SERVICE TYPE
# ============================================================

@router.callback_query(F.data == "buy:type:vol")
async def select_volume_type(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()
    await state.clear()

    await state.update_data(
        service_type=SERVICE_VOLUME,
    )

    text = (
        f"{premium_emoji('shop', '●')} "
        "<b>انتخاب سرویس حجمی</b>\n\n"
        "حجم موردنظرت را انتخاب کن."
    )

    await _edit_or_answer(
        callback.message,
        text,
        buy_volume_selection_keyboard(
            SERVICE_VOLUME,
        ),
    )


@router.callback_query(F.data == "buy:type:unl")
async def select_unlimited_type(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()
    await state.clear()

    await state.update_data(
        service_type=SERVICE_UNLIMITED,
    )

    text = (
        f"{premium_emoji('world', '●')} "
        "<b>انتخاب سرویس نامحدود</b>\n\n"
        "یکی از طرح‌های زیر را انتخاب کن:\n\n"
        "۱. نامحدود منصفانه با سقف ۱۵۰ گیگ\n"
        "۲. نامحدود بی‌نهایت و بدون انقضا"
    )

    await _edit_or_answer(
        callback.message,
        text,
        buy_volume_selection_keyboard(
            SERVICE_UNLIMITED,
        ),
    )


# ============================================================
# BACK TO SERVICE TYPE
# ============================================================

@router.callback_query(F.data == "buy:main")
async def back_to_buy_main(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()
    await state.clear()

    text = (
        f"{premium_emoji('shop', '●')} "
        "<b>نوع سرویس را انتخاب کن.</b>"
    )

    await _edit_or_answer(
        callback.message,
        text,
        buy_type_selection_keyboard(),
    )


# ============================================================
# SELECT VOLUME
# ============================================================

@router.callback_query(F.data.startswith("buy:vol:"))
async def select_volume(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    data = await state.get_data()

    service_type = data.get("service_type")

    volume_key = callback.data.rsplit(":", 1)[-1]

    # اعتبارسنجی نوع سرویس در سمت سرور
    if service_type == SERVICE_VOLUME:

        if volume_key not in VOLUME_OPTIONS:

            await _edit_or_answer(
                callback.message,
                "این گزینه برای سرویس حجمی معتبر نیست.",
            )
            return

        volume = VOLUME_OPTIONS[volume_key]

    elif service_type == SERVICE_UNLIMITED:

        if volume_key not in UNLIMITED_OPTIONS:

            await _edit_or_answer(
                callback.message,
                "این گزینه برای سرویس نامحدود معتبر نیست.",
            )
            return

        volume = UNLIMITED_OPTIONS[volume_key]

    else:

        await _edit_or_answer(
            callback.message,
            "ابتدا نوع سرویس را انتخاب کن.",
            buy_type_selection_keyboard(),
        )
        return

    await state.update_data(
        volume_gb=volume,
        volume_key=volume_key,
        devices=MAX_DEVICES_DEFAULT,
        discount_id=None,
        discount_code=None,
        discount_percent=0,
    )

    # نامحدود بی‌نهایت: بدون انتخاب مدت
    if volume_key == "unl_inf":

        await state.update_data(
            months=1,
            days=0,
        )

        await _show_device_selection(
            callback,
            state,
        )
        return

    # سایر سرویس‌ها: انتخاب مدت
    months = 1

    await state.update_data(
        months=months,
        days=30,
    )

    if volume_key == "unl150":
        service_name = "نامحدود منصفانه (۱۵۰ گیگ)"
    else:
        service_name = f"{volume} گیگ حجمی"

    text = (
        f"{premium_emoji('light', '●')} "
        "<b>انتخاب مدت سرویس</b>\n\n"
        f"سرویس انتخابی: <b>{service_name}</b>\n"
        f"هر ماه اضافه: <b>{int(DEFAULT_PRICES_TOMAN.get('per_month', 30000)):,} تومان</b>\n\n"
        "مدت موردنظرت را انتخاب کن."
    )

    await _edit_or_answer(
        callback.message,
        text,
        buy_time_selection_keyboard(months),
    )


# ============================================================
# BACK TO VOLUME SELECTION
# ============================================================

@router.callback_query(F.data == "buy:vol")
async def back_to_volume_selection(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    data = await state.get_data()
    service_type = data.get("service_type")

    if service_type not in {
        SERVICE_VOLUME,
        SERVICE_UNLIMITED,
    }:

        await _edit_or_answer(
            callback.message,
            "ابتدا نوع سرویس را انتخاب کن.",
            buy_type_selection_keyboard(),
        )
        return

    text = (
        "<b>انتخاب سرویس</b>\n\n"
        "حجم موردنظرت را انتخاب کن."
    )

    await _edit_or_answer(
        callback.message,
        text,
        buy_volume_selection_keyboard(service_type),
    )


# ============================================================
# TIME SELECTION
# ============================================================

@router.callback_query(F.data.startswith("buy:time:"))
async def adjust_time(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    action = callback.data.split(":")[2]

    data = await state.get_data()

    if not _valid_purchase_data({
        **data,
        "days": data.get("days", 30),
    }) and data.get("volume_key") == "unl_inf":

        await _edit_or_answer(
            callback.message,
            "این مرحله برای سرویس انتخابی معتبر نیست.",
        )
        return

    if data.get("volume_key") == "unl_inf":

        await _edit_or_answer(
            callback.message,
            "سرویس بی‌نهایت نیازی به انتخاب مدت ندارد.",
        )
        return

    if "volume_gb" not in data:

        await _edit_or_answer(
            callback.message,
            "ابتدا حجم سرویس را انتخاب کن.",
        )
        return

    try:
        months = int(data.get("months", 1))
    except (TypeError, ValueError):
        months = 1

    months = max(1, min(MAX_MONTHS, months))

    if action == "inc":

        months = min(
            MAX_MONTHS,
            months + 1,
        )

    elif action == "dec":

        months = max(
            1,
            months - 1,
        )

    elif action == "noop":
        return

    elif action == "confirm":

        await state.update_data(
            months=months,
            days=months * 30,
        )

        await _show_device_selection(
            callback,
            state,
        )
        return

    else:
        return

    await state.update_data(
        months=months,
        days=months * 30,
    )

    volume = int(data["volume_gb"])

    if data.get("volume_key") == "unl150":
        service_name = "نامحدود منصفانه (۱۵۰ گیگ)"
    else:
        service_name = f"{volume} گیگ حجمی"

    text = (
        f"{premium_emoji('light', '●')} "
        "<b>انتخاب مدت سرویس</b>\n\n"
        f"سرویس انتخابی: <b>{service_name}</b>\n"
        f"مدت: <b>{months} ماه</b>\n\n"
        "مدت موردنظرت را انتخاب کن."
    )

    await _edit_or_answer(
        callback.message,
        text,
        buy_time_selection_keyboard(months),
    )


# ============================================================
# BACK TO TIME
# ============================================================

@router.callback_query(F.data == "buy:time")
async def back_to_time_selection(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    data = await state.get_data()

    if data.get("volume_key") == "unl_inf":

        await _show_device_selection(
            callback,
            state,
        )
        return

    months = int(data.get("months", 1))

    text = (
        "<b>انتخاب مدت سرویس</b>\n\n"
        f"مدت فعلی: <b>{months} ماه</b>"
    )

    await _edit_or_answer(
        callback.message,
        text,
        buy_time_selection_keyboard(months),
    )


# ============================================================
# DEVICE SELECTION
# ============================================================

@router.callback_query(F.data.startswith("buy:dev:"))
async def adjust_devices(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    action = callback.data.split(":")[2]

    data = await state.get_data()

    if "volume_key" not in data:

        await _edit_or_answer(
            callback.message,
            "ابتدا نوع و حجم سرویس را انتخاب کن.",
        )
        return

    try:
        devices = int(
            data.get(
                "devices",
                MAX_DEVICES_DEFAULT,
            )
        )
    except (TypeError, ValueError):
        devices = MAX_DEVICES_DEFAULT

    devices = max(
        1,
        min(MAX_DEVICES, devices),
    )

    if action == "inc":

        devices = min(
            MAX_DEVICES,
            devices + 1,
        )

    elif action == "dec":

        devices = max(
            1,
            devices - 1,
        )

    elif action == "noop":
        return

    elif action == "confirm":

        await state.update_data(
            devices=devices,
        )

        text = (
            f"{premium_emoji('gift', '●')} "
            "<b>کد تخفیف داری؟</b>\n\n"
            "اگر کد تخفیف داری وارد کن؛ در غیر این صورت ادامه بده."
        )

        await _edit_or_answer(
            callback.message,
            text,
            buy_discount_keyboard(),
        )
        return

    else:
        return

    await state.update_data(
        devices=devices,
    )

    await _show_device_selection(
        callback,
        state,
    )


# ============================================================
# BACK TO DEVICE SELECTION
# ============================================================

@router.callback_query(F.data == "buy:dev")
async def back_to_device_selection(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    data = await state.get_data()

    if not data.get("volume_key"):

        await _edit_or_answer(
            callback.message,
            "ابتدا سرویس را انتخاب کن.",
            buy_type_selection_keyboard(),
        )
        return

    await _show_device_selection(
        callback,
        state,
    )


# ============================================================
# DISCOUNT CODE
# ============================================================

@router.callback_query(F.data == "buy:discount:enter")
async def enter_discount_code(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    data = await state.get_data()

    if not _valid_purchase_data(data):

        await _edit_or_answer(
            callback.message,
            "اطلاعات سفارش معتبر نیست. خرید را از ابتدا شروع کن.",
        )
        await state.clear()
        return

    await state.set_state(
        BuyStates.waiting_discount_code,
    )

    text = (
        f"{premium_emoji('gift', '●')} "
        "<b>کد تخفیف</b>\n\n"
        "کد تخفیف را ارسال کن.\n"
        "برای لغو این مرحله دستور /cancel را بفرست."
    )

    await _edit_or_answer(
        callback.message,
        text,
    )


@router.message(BuyStates.waiting_discount_code)
async def process_discount_code(
    message: Message,
    state: FSMContext,
):

    user = message.from_user

    if not user:
        return

    if not rate_limiter.is_allowed(user.id):

        await message.answer(
            "لطفاً کمی صبر کن و دوباره تلاش کن."
        )
        return

    raw = (message.text or "").strip()
    code_text = raw.upper()

    if not validate_discount_code(code_text):

        await message.answer(
            "فرمت کد تخفیف معتبر نیست.\n"
            "فقط حروف انگلیسی، عدد، خط تیره و زیرخط مجاز است."
        )
        return

    try:
        code = get_discount_code(code_text)
    except Exception:

        logger.exception(
            "Discount lookup failed."
        )

        await message.answer(
            "بررسی کد تخفیف با مشکل مواجه شد. دوباره تلاش کن."
        )
        return

    if (
        not code
        or not code.get("is_active")
        or int(code.get("used_count", 0))
        >= int(code.get("max_uses", 0))
    ):

        await message.answer(
            "این کد تخفیف نامعتبر، غیرفعال یا تکمیل‌شده است."
        )
        return

    await state.update_data(
        discount_code=code_text,
        discount_id=int(code["id"]),
        discount_percent=int(code["percent"]),
    )

    await state.set_state(None)

    await _show_invoice(
        message,
        state,
        from_callback=False,
    )


@router.callback_query(F.data == "buy:discount:skip")
async def skip_discount(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    await state.update_data(
        discount_code=None,
        discount_id=None,
        discount_percent=0,
    )

    await _show_invoice(
        callback,
        state,
        from_callback=True,
    )


# ============================================================
# BACK TO DISCOUNT
# ============================================================

@router.callback_query(F.data == "buy:discount")
async def back_to_discount(
    callback: CallbackQuery,
    state: FSMContext,
):

    await callback.answer()

    await _edit_or_answer(
        callback.message,
        (
            f"{premium_emoji('gift', '●')} "
            "<b>کد تخفیف داری؟</b>\n\n"
            "کد تخفیف را وارد کن یا بدون آن ادامه بده."
        ),
        buy_discount_keyboard(),
    )


# ============================================================
# WALLET PAYMENT
# ============================================================

@router.callback_query(F.data == "buy:pay:wallet")
async def pay_with_wallet(
    callback: CallbackQuery,
    state: FSMContext,
    paxiva: PaxivaClient,
):

    await callback.answer()

    user = callback.from_user

    if not user:
        return

    lock = _user_lock(user.id)

    if lock.locked():

        await _edit_or_answer(
            callback.message,
            "سفارش قبلی شما در حال پردازش است. لطفاً صبر کن.",
        )
        return

    async with lock:

        data = await state.get_data()

        # سفارش مبهم نباید دوباره اجرا شود.
        if data.get("purchase_pending"):

            await _edit_or_answer(
                callback.message,
                (
                    "<b>این سفارش در انتظار بررسی است.</b>\n\n"
                    "برای جلوگیری از ساخت کانفیگ تکراری، "
                    "امکان پرداخت مجدد وجود ندارد. با پشتیبانی تماس بگیر."
                ),
            )
            return

        if not _valid_purchase_data(data):

            await _edit_or_answer(
                callback.message,
                "اطلاعات سفارش منقضی یا نامعتبر است. خرید را از ابتدا انجام بده.",
            )

            await state.clear()
            return

        # قیمت را مجدداً سمت سرور محاسبه می‌کنیم.
        try:

            price, _, _, _ = _build_order_prices(data)

        except Exception:

            logger.exception(
                "Could not recalculate order price."
            )

            await _edit_or_answer(
                callback.message,
                "محاسبه مبلغ سفارش ناموفق بود. دوباره فاکتور بگیر.",
            )
            return

        # بررسی موجودی فقط برای نمایش؛ کسر واقعی اتمیک است.
        try:
            balance = get_balance(user.id)
        except Exception:

            logger.exception(
                "Could not read user balance."
            )

            await _edit_or_answer(
                callback.message,
                "دریافت موجودی کیف پول ناموفق بود. دوباره تلاش کن.",
            )
            return

        if balance < price:

            await _edit_or_answer(
                callback.message,
                (
                    "<b>موجودی کیف پول کافی نیست.</b>\n\n"
                    f"موجودی فعلی: <b>{int(balance):,} تومان</b>\n"
                    f"مبلغ سفارش: <b>{price:,} تومان</b>"
                ),
            )
            return

        await _edit_or_answer(
            callback.message,
            (
                f"{premium_emoji('light', '●')} "
                "<b>در حال ثبت سفارش...</b>\n\n"
                "لطفاً تا پایان عملیات دکمه‌ای نزن."
            ),
        )

        status, result = await _provision_purchase(
            user_id=user.id,
            data=data,
            paxiva=paxiva,
            payment_type="wallet",
        )

        if status == "success":

            config_name, link = result.split("\n", 1)

            text = (
                f"{premium_emoji('true', '●')} "
                "<b>خرید با موفقیت انجام شد.</b>\n\n"
                f"<b>نام کانفیگ:</b>\n"
                f"<code>{_safe_text(config_name)}</code>\n\n"
                f"<b>لینک اشتراک:</b>\n"
                f"<code>{_safe_text(link)}</code>\n\n"
                f"{premium_emoji('safe', '●')} "
                "لینک اشتراک خود را در اختیار دیگران قرار نده."
            )

            await _edit_or_answer(
                callback.message,
                text,
            )

            await state.clear()
            return

        if status == "pending":

            await state.update_data(
                purchase_pending=True,
            )

            await _edit_or_answer(
                callback.message,
                (
                    f"{premium_emoji('warning', '●')} "
                    "<b>سفارش نیازمند بررسی است.</b>\n\n"
                    f"{_safe_text(result)}"
                ),
            )
            return

        await _edit_or_answer(
            callback.message,
            (
                f"{premium_emoji('warning', '●')} "
                f"{_safe_text(result)}"
            ),
        )


# ============================================================
# STARS PAYMENT
# ============================================================

@router.callback_query(F.data == "buy:pay:stars")
async def stars_payment_not_enabled(
    callback: CallbackQuery,
):

    await callback.answer(
        "پرداخت با Stars هنوز پیاده‌سازی و ایمن‌سازی نشده است. از کیف پول استفاده کن.",
        show_alert=True,
    )


# ============================================================
# CANCEL
# ============================================================

@router.message(F.text == "/cancel")
async def cancel_buy(
    message: Message,
    state: FSMContext,
):

    current = await state.get_state()

    if current == BuyStates.waiting_discount_code.state:

        await state.set_state(None)

        await message.answer(
            "ورود کد تخفیف لغو شد. برای ادامه خرید از منوی خرید وارد شو."
        )
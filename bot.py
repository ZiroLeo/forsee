import asyncio
import html
import json
import logging
from typing import Any, Optional
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    DEFAULT_PRICES_TOMAN, DEFAULT_PRICES_STARS, MAX_DEVICES_DEFAULT,
    MAX_MONTHS, PREMIUM_EMOJIS, PREMIUM_EMOJI_ENABLED,
)
from database import (
    add_balance, add_referral_commission, consume_discount_code,
    create_subscription, deduct_balance, get_balance, get_discount_code,
    get_setting, hard_delete_subscription, increment_total_purchases, log_event,
)
from paxiva import PaxivaClient, PaxivaError
from services.counter import make_config_name, release_reserved_number, reserve_new_config_number
from rich import premium_emoji
import ui
from utils import (
    calculate_price_stars, calculate_price_toman, generate_idempotency_key,
    rate_limiter, validate_discount_code,
)

logger = logging.getLogger(__name__)
router = Router(name="buy")

VOLUME_OPTIONS = {"10": 10, "20": 20, "30": 30, "50": 50, "100": 100, "200": 200, "500": 500}
UNLIMITED_OPTIONS = {"unl150": 150, "unl_inf": 0}
SERVICE_VOLUME = "vol"
SERVICE_UNLIMITED = "unl"
MAX_DEVICES = 10

_user_purchase_locks: dict[int, asyncio.Lock] = {}
_pending_purchase_users: set[int] = set()


class BuyStates(StatesGroup):
    waiting_discount_code = State()


def _user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_purchase_locks:
        _user_purchase_locks[user_id] = asyncio.Lock()
    return _user_purchase_locks[user_id]


def _pending_setting_key(user_id: int) -> str:
    return f"purchase_pending:{int(user_id)}"


def _persist_pending_purchase(user_id: int, order_key: str, status: str) -> None:
    # از جدول settings موجود استفاده می‌کنیم تا در صورت restart هم
    # سفارش مبهم باعث خرید یا کسر وجه تکراری نشود؛ نیازی به تغییر DB نیست.
    payload = {"order_key": order_key, "status": status}
    set_setting(_pending_setting_key(user_id), json.dumps(payload, ensure_ascii=False))


def _clear_pending_purchase(user_id: int) -> None:
    set_setting(_pending_setting_key(user_id), "")
    _pending_purchase_users.discard(user_id)


def _safe_text(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _safe_log(level: str, event: str, user_id: int, detail: str = "") -> None:
    try:
        log_event(level, event, user_id, detail[:1000])
    except Exception:
        logger.exception("Could not write purchase event log: %s", event)


def _emoji_id(key: Optional[str]) -> Optional[str]:
    if not PREMIUM_EMOJI_ENABLED or not key:
        return None
    value = PREMIUM_EMOJIS.get(key)
    return str(value).strip() if value else None


def _button(text: str, callback_data: str, emoji_key: Optional[str] = None) -> InlineKeyboardButton:
    if not text or not callback_data:
        raise ValueError("Button text and callback_data are required")
    if len(callback_data.encode("utf-8")) > 64:
        raise ValueError("Callback data exceeds Telegram's 64-byte limit")
    kwargs: dict[str, Any] = {"text": text, "callback_data": callback_data, "style": "primary"}
    emoji_id = _emoji_id(emoji_key)
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    return InlineKeyboardButton(**kwargs)


def _keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _valid_subscription_link(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _valid_config_uri(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > 3900:
        return False
    return urlparse(value.strip()).scheme.lower() in {
        "vless", "vmess", "trojan", "ss", "ssr", "tuic", "hysteria",
        "hysteria2", "wireguard", "http", "https",
    }


# message_id همان پیامی که صفحه‌ی خرید در آن نمایش داده می‌شود در state ذخیره و ویرایش می‌شود.
async def _edit_purchase(
    *, bot, state: FSMContext, text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    source_message: Optional[Message] = None,
) -> bool:
    data = await state.get_data()
    chat_id, message_id = data.get("purchase_chat_id"), data.get("purchase_message_id")
    if not chat_id or not message_id:
        logger.error("Purchase message identifiers are missing")
        return False
    if source_message and (
        source_message.chat.id != int(chat_id) or source_message.message_id != int(message_id)
    ):
        logger.warning("Ignored stale purchase message callback: %s", source_message.message_id)
        return False
    try:
        await bot.edit_message_text(
            chat_id=int(chat_id), message_id=int(message_id),
            text=text, reply_markup=reply_markup,
        )
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return True
        logger.exception("Could not edit active purchase message")
        return False
    except Exception:
        logger.exception("Unexpected purchase message edit error")
        return False


async def _current_purchase(callback: CallbackQuery, state: FSMContext) -> bool:
    data = await state.get_data()
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer("پیام خرید در دسترس نیست.", show_alert=True)
        return False
    if data.get("purchase_chat_id") != message.chat.id or data.get("purchase_message_id") != message.message_id:
        await callback.answer("این دکمه مربوط به یک خرید قدیمی است. از منوی خرید دوباره وارد شو.", show_alert=True)
        return False
    return True


async def _edit_callback(callback: CallbackQuery, state: FSMContext, text: str, markup=None) -> bool:
    if not await _current_purchase(callback, state):
        return False
    return await _edit_purchase(
        bot=callback.bot, state=state, text=text, reply_markup=markup,
        source_message=callback.message if isinstance(callback.message, Message) else None,
    )


async def _edit_user_message(message: Message, state: FSMContext, text: str, markup=None) -> bool:
    return await _edit_purchase(bot=message.bot, state=state, text=text, reply_markup=markup)


# ----------------------------- Keyboards -----------------------------

def buy_type_selection_keyboard() -> InlineKeyboardMarkup:
    return _keyboard([
        [_button("سرویس حجمی", "buy:type:vol", "shop"), _button("سرویس نامحدود", "buy:type:unl", "world")],
        [_button("بازگشت به منوی اصلی", "menu:main", "telegram")],
    ])


def buy_volume_selection_keyboard(service_type: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if service_type == SERVICE_VOLUME:
        opts = [("۱۰ گیگ", "10"), ("۲۰ گیگ", "20"), ("۳۰ گیگ", "30"), ("۵۰ گیگ", "50"),
                ("۱۰۰ گیگ", "100"), ("۲۰۰ گیگ", "200"), ("۵۰۰ گیگ", "500")]
        for i in range(0, len(opts), 2):
            rows.append([_button(label, f"buy:vol:{key}", "blue_dot") for label, key in opts[i:i + 2]])
    elif service_type == SERVICE_UNLIMITED:
        rows.extend([
            [_button("نامحدود منصفانه (۱۵۰ گیگ)", "buy:vol:unl150", "world")],
            [_button("نامحدود بی‌نهایت", "buy:vol:unl_inf", "diamond")],
        ])
    else:
        raise ValueError("Invalid service type")
    rows.append([_button("بازگشت", "buy:main", "shop")])
    return _keyboard(rows)


def buy_time_selection_keyboard(months: int) -> InlineKeyboardMarkup:
    return _keyboard([
        [_button("−", "buy:time:dec", "blue_dot"), _button(f"{months} ماه", "buy:time:noop", "light"),
         _button("+", "buy:time:inc", "blue_dot")],
        [_button("تأیید و ادامه", "buy:time:confirm", "true")],
        [_button("بازگشت", "buy:vol", "shop")],
    ])


def buy_device_selection_keyboard(devices: int) -> InlineKeyboardMarkup:
    return _keyboard([
        [_button("−", "buy:dev:dec", "blue_dot"), _button(f"{devices} دستگاه", "buy:dev:noop", "telegram"),
         _button("+", "buy:dev:inc", "blue_dot")],
        [_button("تأیید و ادامه", "buy:dev:confirm", "true")],
        [_button("بازگشت", "buy:time", "shop")],
    ])


def buy_discount_keyboard() -> InlineKeyboardMarkup:
    return _keyboard([
        [_button("وارد کردن کد تخفیف", "buy:discount:enter", "gift")],
        [_button("بدون کد تخفیف ادامه می‌دهم", "buy:discount:skip", "true")],
        [_button("بازگشت", "buy:dev", "shop")],
    ])


def buy_payment_keyboard(price: int) -> InlineKeyboardMarkup:
    return _keyboard([
        [_button(f"پرداخت با کیف پول | {price:,} تومان", "buy:pay:wallet", "wallet")],
        [_button("بازگشت", "buy:discount", "shop")],
    ])


def purchase_success_keyboard(client_id: int) -> InlineKeyboardMarkup:
    return _keyboard([
        [_button("دریافت کامل کانفیگ‌ها", f"buy:configs:{client_id}", "world")],
        [_button("بازگشت به منوی اصلی", "menu:main", "telegram")],
    ])


def purchase_retry_keyboard(price: int) -> InlineKeyboardMarkup:
    return _keyboard([
        [_button(f"تلاش دوباره برای پرداخت | {price:,} تومان", "buy:pay:wallet", "wallet")],
        [_button("بازگشت به فاکتور", "buy:discount", "shop")],
    ])


# ----------------------------- Pricing -----------------------------

def _valid_purchase_data(data: dict[str, Any]) -> bool:
    try:
        volume, days, devices = float(data["volume_gb"]), int(data["days"]), int(data["devices"])
        key, service_type = str(data["volume_key"]), str(data["service_type"])
    except (KeyError, TypeError, ValueError):
        return False
    if not 1 <= devices <= MAX_DEVICES:
        return False
    if service_type == SERVICE_VOLUME:
        return key in VOLUME_OPTIONS and volume == VOLUME_OPTIONS[key] and 30 <= days <= MAX_MONTHS * 30 and days % 30 == 0
    if service_type == SERVICE_UNLIMITED:
        if key not in UNLIMITED_OPTIONS or volume != UNLIMITED_OPTIONS[key]:
            return False
        if key == "unl_inf":
            return days == 0
        return key == "unl150" and 30 <= days <= MAX_MONTHS * 30 and days % 30 == 0
    return False


def _discount_for_order(data: dict[str, Any]) -> tuple[int, Optional[int]]:
    if not data.get("discount_id") or not data.get("discount_code"):
        return 0, None
    try:
        code = get_discount_code(str(data["discount_code"]))
        if not code or int(code.get("id", 0)) != int(data["discount_id"]):
            return 0, None
        if not code.get("is_active") or int(code.get("used_count", 0)) >= int(code.get("max_uses", 0)):
            return 0, None
        percent = int(code.get("percent", 0))
        return (percent, int(data["discount_id"])) if 1 <= percent <= 100 else (0, None)
    except Exception:
        logger.exception("Could not revalidate discount")
        return 0, None


def _calculate_prices(volume: float, days: int, devices: int, key: str) -> tuple[int, int]:
    if key in {"unl_inf", "unl150"}:
        toman_key = "unlimited_inf" if key == "unl_inf" else "unlimited_150"
        stars_key = toman_key
        toman_base = int(DEFAULT_PRICES_TOMAN.get(toman_key, 0))
        stars_base = int(DEFAULT_PRICES_STARS.get(stars_key, 0))
        if toman_base <= 0 or stars_base < 0:
            raise ValueError("Unlimited price is not configured")
        return (
            calculate_price_toman(volume, days, devices, is_unlimited=True, unlimited_price=toman_base),
            calculate_price_stars(volume, days, devices, is_unlimited=True, unlimited_stars=stars_base),
        )
    return (
        calculate_price_toman(volume, days, devices, is_unlimited=False),
        calculate_price_stars(volume, days, devices, is_unlimited=False),
    )


def _build_order_prices(data: dict[str, Any]) -> tuple[int, int, int, Optional[int]]:
    if not _valid_purchase_data(data):
        raise ValueError("Invalid purchase data")
    toman, stars = _calculate_prices(float(data["volume_gb"]), int(data["days"]), int(data["devices"]), str(data["volume_key"]))
    discount_percent, discount_id = _discount_for_order(data)
    toman = toman * (100 - discount_percent) // 100
    stars = stars * (100 - discount_percent) // 100
    if toman <= 0:
        raise ValueError("Purchase price must be greater than zero")
    return toman, stars, discount_percent, discount_id


def _service_title(data: dict[str, Any]) -> str:
    key = data.get("volume_key")
    if key == "unl150":
        return "نامحدود منصفانه با سقف ۱۵۰ گیگ"
    if key == "unl_inf":
        return "نامحدود بی‌نهایت"
    return f"{int(float(data.get('volume_gb', 0)))} گیگ حجمی"


# ----------------------------- Render steps -----------------------------
async def _show_volume_step(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    title = "حجمی" if data.get("service_type") == SERVICE_VOLUME else "نامحدود"
    await _edit_callback(callback, state,
        f"{premium_emoji('shop', '●')} <b>انتخاب پلن {title}</b>\n\nپلن موردنظرت را انتخاب کن.",
        buy_volume_selection_keyboard(data.get("service_type")))


async def _show_time_step(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    months = max(1, min(MAX_MONTHS, int(data.get("months", 1))))
    text = (f"{premium_emoji('light', '●')} <b>انتخاب مدت سرویس</b>\n\n"
            f"سرویس انتخابی: <b>{_safe_text(_service_title(data))}</b>\n"
            f"مدت فعلی: <b>{months} ماه</b>\n"
            f"هزینه هر ماه اضافه: <b>{int(DEFAULT_PRICES_TOMAN.get('per_month', 30000)):,} تومان</b>\n\n"
            "مدت موردنظرت را انتخاب کن.")
    await _edit_callback(callback, state, text, buy_time_selection_keyboard(months))


async def _show_device_step(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    devices = max(1, min(MAX_DEVICES, int(data.get("devices", MAX_DEVICES_DEFAULT))))
    extra = max(0, devices - MAX_DEVICES_DEFAULT) * int(DEFAULT_PRICES_TOMAN.get("per_device", 15000))
    text = (f"{premium_emoji('telegram', '●')} <b>تعداد دستگاه‌های مجاز</b>\n\n"
            f"سرویس: <b>{_safe_text(_service_title(data))}</b>\n"
            f"تعداد دستگاه: <b>{devices}</b>\n"
            f"دستگاه رایگان: <b>{MAX_DEVICES_DEFAULT}</b>\n"
            f"هزینه دستگاه اضافه: <b>{extra:,} تومان</b>\n\n"
            "تعداد دستگاه‌های موردنیازت را انتخاب کن.")
    await _edit_callback(callback, state, text, buy_device_selection_keyboard(devices))


async def _show_discount_step(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not _valid_purchase_data(data):
        await _edit_callback(callback, state, "اطلاعات سفارش معتبر نیست. از ابتدا شروع کن.", buy_type_selection_keyboard())
        return
    await _edit_callback(callback, state,
        f"{premium_emoji('gift', '●')} <b>کد تخفیف داری؟</b>\n\nاگر کد تخفیف داری وارد کن؛ در غیر این صورت ادامه بده.",
        buy_discount_keyboard())


async def _show_invoice(*, bot, state: FSMContext, source_message: Optional[Message] = None) -> None:
    data = await state.get_data()
    if not _valid_purchase_data(data):
        await _edit_purchase(bot=bot, state=state,
            text=f"{premium_emoji('warning', '●')} <b>اطلاعات سفارش معتبر نیست.</b>\nخرید را از ابتدا شروع کن.",
            reply_markup=buy_type_selection_keyboard(), source_message=source_message)
        return
    try:
        price, _stars, discount, _discount_id = _build_order_prices(data)
    except Exception:
        logger.exception("Could not calculate purchase invoice")
        await _edit_purchase(bot=bot, state=state,
            text=f"{premium_emoji('warning', '●')} <b>محاسبه قیمت ناموفق بود.</b> با پشتیبانی تماس بگیر.",
            reply_markup=buy_discount_keyboard(), source_message=source_message)
        return
    try:
        balance = get_balance(int(data["user_id"]))
    except Exception:
        logger.exception("Could not read balance")
        balance = 0
    discount_line = f"<b>تخفیف:</b> {discount}%\n" if discount else ""
    days = int(data["days"])
    duration = "بدون انقضا" if days == 0 else f"{days // 30} ماه"
    text = (f"{premium_emoji('wallet', '●')} <b>فاکتور نهایی خرید</b>\n\n"
            f"<b>نوع سرویس:</b> {_safe_text(_service_title(data))}\n"
            f"<b>مدت:</b> {duration}\n"
            f"<b>دستگاه‌ها:</b> {int(data['devices'])}\n{discount_line}"
            "━━━━━━━━━━━━━━\n"
            f"<b>مبلغ قابل پرداخت:</b> <b>{price:,} تومان</b>\n"
            f"<b>موجودی کیف پول:</b> {int(balance):,} تومان\n\n"
            "برای نهایی‌کردن سفارش، پرداخت از کیف پول را انتخاب کن.")
    await _edit_purchase(bot=bot, state=state, text=text,
        reply_markup=buy_payment_keyboard(price), source_message=source_message)


# ----------------------------- PAXIVA + wallet -----------------------------
async def _delete_remote(paxiva: PaxivaClient, client_id: int) -> bool:
    try:
        await paxiva.delete_client(client_id, purge=True)
        return True
    except Exception:
        logger.exception("Could not delete remote client %s", client_id)
        return False


def _refund(user_id: int, amount: int, order_key: str, description: str) -> bool:
    if amount <= 0:
        return True
    try:
        return bool(add_balance(user_id, amount, "refund", description, reference_id=f"refund:{order_key}"))
    except Exception:
        logger.exception("Refund failed for user %s", user_id)
        return False


async def _provision_purchase(*, user_id: int, data: dict[str, Any], paxiva: PaxivaClient) -> tuple[str, Any]:
    if not _valid_purchase_data(data):
        return "failed", "اطلاعات سفارش معتبر نیست."
    try:
        price, _stars, _discount_percent, discount_id = _build_order_prices(data)
    except Exception:
        logger.exception("Final purchase price validation failed")
        return "failed", "محاسبه مبلغ سفارش ناموفق بود."

    order_key = str(data.get("idempotency_key") or "")
    if not order_key:
        return "failed", "شناسه سفارش معتبر نیست. خرید را از ابتدا شروع کن."

    volume, days, devices = float(data["volume_gb"]), int(data["days"]), int(data["devices"])
    key = str(data["volume_key"])
    kind = SERVICE_UNLIMITED if key in UNLIMITED_OPTIONS else SERVICE_VOLUME
    number = config_name = client_id = subscription_id = None
    debited = False
    create_started = False
    create_response_received = False

    try:
        debited = deduct_balance(user_id, price, "purchase",
            f"خرید سرویس {volume:g}GB / {days} روز", reference_id=order_key)
    except Exception:
        logger.exception("Wallet deduction failed")
        return "failed", "کسر موجودی انجام نشد. دوباره تلاش کن."
    if not debited:
        return "failed", "موجودی کیف پول کافی نیست یا کسر موجودی انجام نشد."

    try:
        number = reserve_new_config_number(is_test=False)
        if not number:
            raise RuntimeError("Could not reserve config number")
        config_name = make_config_name(number, is_test=False)
        create_started = True
        client_data = await paxiva.create_client(
            name=config_name, volume_gb=volume, days=days, devices=devices,
            idempotency_key=order_key, kind=kind,
        )
        create_response_received = True
        if not isinstance(client_data, dict):
            raise RuntimeError("Invalid PAXIVA response")
        try:
            client_id = int(client_data.get("id"))
        except (TypeError, ValueError):
            client_id = None
        if not client_id:
            _safe_log("CRITICAL", "purchase_missing_client_id", user_id, f"order={order_key}; config={config_name}")
            return "pending", "پاسخ پنل شناسه سرویس نداشت. برای جلوگیری از ساخت تکراری، سفارش نیازمند بررسی پشتیبانی است."

        link = client_data.get("link")
        if not _valid_subscription_link(link):
            try:
                details = await paxiva.get_client(client_id)
                if isinstance(details, dict):
                    link = details.get("link") or details.get("subscription_link")
            except Exception:
                logger.exception("Could not get client subscription link")
        if not _valid_subscription_link(link):
            raise RuntimeError("PAXIVA returned invalid subscription link")

        subscription_id = create_subscription(
            telegram_id=user_id, config_number=number, config_name=config_name,
            kind=kind, volume_gb=volume, days=days, devices=devices,
            price_toman=price, price_stars=0, paxiva_client_id=client_id, link=str(link),
        )
        if not subscription_id:
            raise RuntimeError("Could not save subscription")

        if discount_id is not None and not consume_discount_code(int(discount_id), user_id):
            raise RuntimeError("Discount code became unavailable or was already used")

        try:
            increment_total_purchases(user_id)
        except Exception:
            logger.exception("Could not increment purchase count")
        try:
            add_referral_commission(user_id, price, int(subscription_id), "purchase")
        except Exception:
            logger.exception("Referral commission failed")

        _safe_log("INFO", "purchase_success", user_id,
            f"order={order_key}; subscription={subscription_id}; client={client_id}; config={config_name}")
        return "success", {
            "config_name": config_name, "link": str(link), "client_id": client_id,
            "subscription_id": int(subscription_id), "price_toman": price,
        }

    except Exception as exc:
        logger.exception("Purchase provisioning failed for user %s", user_id)
        definitive_rejection = isinstance(exc, PaxivaError) and 400 <= int(getattr(exc, "status_code", 500)) < 500
        if create_started and not create_response_received and not definitive_rejection:
            _safe_log("CRITICAL", "purchase_ambiguous", user_id, f"order={order_key}; config={config_name}; no panel response")
            return "pending", ("ارتباط با پنل هنگام ساخت سرویس قطع شد و نتیجه قطعی نیست. ممکن است سرویس ساخته شده باشد؛ "
                                "برای جلوگیری از خرید تکراری، بازپرداخت خودکار انجام نمی‌شود. با پشتیبانی تماس بگیر.")

        if client_id is not None and not await _delete_remote(paxiva, client_id):
            _safe_log("CRITICAL", "purchase_orphan_client", user_id, f"order={order_key}; client={client_id}")
            return "pending", "سرویس در پنل ساخته شده اما حذف آن تأیید نشد؛ سفارش نیازمند بررسی پشتیبانی است."

        if subscription_id is not None:
            try:
                if not hard_delete_subscription(int(subscription_id)):
                    return "pending", "سرویس حذف شد اما پاک‌سازی دیتابیس تأیید نشد. با پشتیبانی تماس بگیر."
            except Exception:
                logger.exception("Local subscription rollback failed")
                return "pending", "پاک‌سازی سفارش کامل نشد و نیازمند بررسی پشتیبانی است."

        if number is not None:
            release_reserved_number(int(number), is_test=False)

        if debited and not _refund(user_id, price, order_key, f"بازگشت وجه سفارش {config_name or order_key}"):
            _safe_log("CRITICAL", "purchase_refund_failed", user_id, f"order={order_key}; amount={price}")
            return "pending", "خرید ناموفق بود اما بازگشت وجه تأیید نشد. فوراً با پشتیبانی تماس بگیر."

        _safe_log("ERROR", "purchase_failed", user_id, f"order={order_key}; error={type(exc).__name__}")
        if isinstance(exc, PaxivaError):
            return "failed", "پنل ساخت سرویس را رد کرد؛ مبلغ به کیف پولت بازگشت داده شد."
        return "failed", "ساخت سرویس کامل نشد؛ مبلغ به کیف پولت بازگشت داده شد."


# ----------------------------- Start / service selection -----------------------------
@router.callback_query(F.data == "menu:buy")
async def start_buy(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user = callback.from_user
    if not user:
        return
    if not rate_limiter.is_allowed(user.id):
        await callback.message.answer("لطفاً کمی صبر کن و دوباره تلاش کن.")
        return
    persisted_pending = get_setting(_pending_setting_key(user.id), "")
    if user.id in _pending_purchase_users or persisted_pending:
        await callback.message.answer(
            f"{premium_emoji('warning', '●')} <b>یک سفارش قبلی شما نیازمند بررسی است.</b>\n\n"
            "برای جلوگیری از خرید تکراری، تا تعیین وضعیت سفارش قبلی امکان خرید جدید وجود ندارد. با پشتیبانی تماس بگیر."
        )
        return
    if get_setting("sales_open", "1") == "0":
        await callback.message.answer(
            f"{premium_emoji('warning', '●')} <b>فروش موقتاً بسته است.</b>\n\nلطفاً اطلاعیه‌های کانال را دنبال کن."
        )
        return

    await state.clear()
    text = f"{premium_emoji('shop', '●')} <b>خرید سرویس آی‌من نتورک</b>\n\nنوع سرویس موردنظرت را انتخاب کن."
    # همان پیام اصلی به صفحه‌ی خرید ویرایش می‌شود (شناسه‌اش در state ثبت می‌شود).
    purchase_message = await ui.show(callback, text, buy_type_selection_keyboard())
    if purchase_message is None:
        return
    await state.update_data(
        user_id=user.id, purchase_chat_id=purchase_message.chat.id,
        purchase_message_id=purchase_message.message_id,
        idempotency_key=generate_idempotency_key(f"buy-{user.id}"),
        purchase_processing=False, purchase_pending=False,
    )


@router.callback_query(F.data == "buy:type:vol")
async def select_volume_type(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    await state.update_data(service_type=SERVICE_VOLUME, volume_gb=None, volume_key=None,
        days=None, months=1, devices=MAX_DEVICES_DEFAULT, discount_id=None,
        discount_code=None, discount_percent=0, purchase_processing=False, purchase_pending=False)
    await _edit_callback(callback, state,
        f"{premium_emoji('shop', '●')} <b>انتخاب سرویس حجمی</b>\n\nحجم موردنظرت را انتخاب کن.",
        buy_volume_selection_keyboard(SERVICE_VOLUME))


@router.callback_query(F.data == "buy:type:unl")
async def select_unlimited_type(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    await state.update_data(service_type=SERVICE_UNLIMITED, volume_gb=None, volume_key=None,
        days=None, months=1, devices=MAX_DEVICES_DEFAULT, discount_id=None,
        discount_code=None, discount_percent=0, purchase_processing=False, purchase_pending=False)
    await _edit_callback(callback, state,
        f"{premium_emoji('world', '●')} <b>انتخاب سرویس نامحدود</b>\n\n"
        "۱. نامحدود منصفانه با سقف ۱۵۰ گیگ\n۲. نامحدود بی‌نهایت و بدون انقضا",
        buy_volume_selection_keyboard(SERVICE_UNLIMITED))


@router.callback_query(F.data == "buy:main")
async def back_to_buy_main(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    await state.update_data(service_type=None, volume_gb=None, volume_key=None, days=None,
        months=1, devices=MAX_DEVICES_DEFAULT, discount_id=None, discount_code=None, discount_percent=0)
    await _edit_callback(callback, state,
        f"{premium_emoji('shop', '●')} <b>نوع سرویس را انتخاب کن.</b>",
        buy_type_selection_keyboard())


@router.callback_query(F.data.startswith("buy:vol:"))
async def select_volume(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    data = await state.get_data()
    service_type = data.get("service_type")
    key = callback.data.rsplit(":", 1)[-1]
    if service_type == SERVICE_VOLUME and key in VOLUME_OPTIONS:
        volume = VOLUME_OPTIONS[key]
    elif service_type == SERVICE_UNLIMITED and key in UNLIMITED_OPTIONS:
        volume = UNLIMITED_OPTIONS[key]
    else:
        await _edit_callback(callback, state,
            f"{premium_emoji('warning', '●')} <b>این پلن برای نوع سرویس انتخاب‌شده معتبر نیست.</b>",
            buy_type_selection_keyboard())
        return
    await state.update_data(volume_gb=volume, volume_key=key, devices=MAX_DEVICES_DEFAULT,
        discount_id=None, discount_code=None, discount_percent=0)
    if key == "unl_inf":
        await state.update_data(months=1, days=0)
        await _show_device_step(callback, state)
    else:
        await state.update_data(months=1, days=30)
        await _show_time_step(callback, state)


@router.callback_query(F.data == "buy:vol")
async def back_to_volume(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    data = await state.get_data()
    service_type = data.get("service_type")
    if service_type not in {SERVICE_VOLUME, SERVICE_UNLIMITED}:
        await _edit_callback(callback, state, "ابتدا نوع سرویس را انتخاب کن.", buy_type_selection_keyboard())
        return
    await _show_volume_step(callback, state)


@router.callback_query(F.data.startswith("buy:time:"))
async def adjust_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    data = await state.get_data()
    if data.get("volume_key") == "unl_inf":
        await _show_device_step(callback, state)
        return
    if data.get("volume_key") not in VOLUME_OPTIONS and data.get("volume_key") != "unl150":
        await _edit_callback(callback, state, "ابتدا پلن سرویس را انتخاب کن.", buy_type_selection_keyboard())
        return
    action = callback.data.split(":")[2]
    months = max(1, min(MAX_MONTHS, int(data.get("months", 1))))
    if action == "inc":
        months = min(MAX_MONTHS, months + 1)
    elif action == "dec":
        months = max(1, months - 1)
    elif action == "noop":
        return
    elif action == "confirm":
        await state.update_data(months=months, days=months * 30)
        await _show_device_step(callback, state)
        return
    else:
        return
    await state.update_data(months=months, days=months * 30)
    await _show_time_step(callback, state)


@router.callback_query(F.data == "buy:time")
async def back_to_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    data = await state.get_data()
    if data.get("volume_key") == "unl_inf":
        await _show_device_step(callback, state)
    elif data.get("volume_key"):
        await _show_time_step(callback, state)
    else:
        await _edit_callback(callback, state, "ابتدا سرویس را انتخاب کن.", buy_type_selection_keyboard())


@router.callback_query(F.data.startswith("buy:dev:"))
async def adjust_devices(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    data = await state.get_data()
    if not data.get("volume_key"):
        await _edit_callback(callback, state, "ابتدا نوع و پلن سرویس را انتخاب کن.", buy_type_selection_keyboard())
        return
    action = callback.data.split(":")[2]
    devices = max(1, min(MAX_DEVICES, int(data.get("devices", MAX_DEVICES_DEFAULT))))
    if action == "inc":
        devices = min(MAX_DEVICES, devices + 1)
    elif action == "dec":
        devices = max(1, devices - 1)
    elif action == "noop":
        return
    elif action == "confirm":
        await state.update_data(devices=devices)
        await _show_discount_step(callback, state)
        return
    else:
        return
    await state.update_data(devices=devices)
    await _show_device_step(callback, state)


@router.callback_query(F.data == "buy:dev")
async def back_to_devices(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    data = await state.get_data()
    if not data.get("volume_key"):
        await _edit_callback(callback, state, "ابتدا سرویس را انتخاب کن.", buy_type_selection_keyboard())
    else:
        await _show_device_step(callback, state)


@router.callback_query(F.data == "buy:discount:enter")
async def enter_discount(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    if not _valid_purchase_data(await state.get_data()):
        await _edit_callback(callback, state, "اطلاعات سفارش معتبر نیست. از ابتدا شروع کن.", buy_type_selection_keyboard())
        return
    await state.set_state(BuyStates.waiting_discount_code)
    await _edit_callback(callback, state,
        f"{premium_emoji('gift', '●')} <b>وارد کردن کد تخفیف</b>\n\nکد تخفیف را در یک پیام ارسال کن.\nبرای لغو /cancel را بفرست.",
        _keyboard([[_button("بازگشت", "buy:discount", "shop")]]))


@router.message(BuyStates.waiting_discount_code, F.text != "/cancel")
async def process_discount_code(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return
    data = await state.get_data()
    if int(data.get("user_id", 0)) != user.id:
        return
    if not rate_limiter.is_allowed(user.id):
        await _edit_user_message(message, state, "لطفاً کمی صبر کن و دوباره تلاش کن.",
            _keyboard([[_button("بازگشت", "buy:discount", "shop")]]))
        return
    code_text = (message.text or "").strip().upper()
    if not validate_discount_code(code_text):
        await _edit_user_message(message, state,
            f"{premium_emoji('warning', '●')} <b>فرمت کد تخفیف معتبر نیست.</b>\nفقط حروف انگلیسی، عدد، خط تیره و زیرخط مجاز است.",
            _keyboard([[_button("بازگشت", "buy:discount", "shop")]]))
        return
    try:
        code = get_discount_code(code_text)
    except Exception:
        logger.exception("Discount lookup failed")
        await _edit_user_message(message, state, "بررسی کد تخفیف ناموفق بود. دوباره تلاش کن.")
        return
    if not code or not code.get("is_active") or int(code.get("used_count", 0)) >= int(code.get("max_uses", 0)):
        await _edit_user_message(message, state,
            f"{premium_emoji('warning', '●')} <b>کد تخفیف نامعتبر، غیرفعال یا تکمیل‌شده است.</b> دوباره ارسال کن.",
            _keyboard([[_button("بازگشت", "buy:discount", "shop")]]))
        return
    await state.update_data(discount_code=code_text, discount_id=int(code["id"]), discount_percent=int(code["percent"]))
    await state.set_state(None)
    await _show_invoice(bot=message.bot, state=state)


@router.callback_query(F.data == "buy:discount:skip")
async def skip_discount(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    await state.update_data(discount_code=None, discount_id=None, discount_percent=0)
    await _show_invoice(bot=callback.bot, state=state,
        source_message=callback.message if isinstance(callback.message, Message) else None)


@router.callback_query(F.data == "buy:discount")
async def back_to_discount(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _current_purchase(callback, state):
        return
    await state.set_state(None)
    await _show_discount_step(callback, state)


@router.callback_query(F.data == "buy:pay:wallet")
async def pay_with_wallet(callback: CallbackQuery, state: FSMContext, paxiva: PaxivaClient):
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    if not await _current_purchase(callback, state):
        return
    lock = _user_lock(user.id)
    if lock.locked():
        await callback.answer("سفارش شما در حال پردازش است؛ کمی صبر کن.", show_alert=True)
        return
    await callback.answer()

    async with lock:
        data = await state.get_data()
        if data.get("purchase_pending") or user.id in _pending_purchase_users:
            await _edit_callback(callback, state,
                f"{premium_emoji('warning', '●')} <b>این سفارش نیازمند بررسی است.</b>\nامکان پرداخت مجدد وجود ندارد؛ با پشتیبانی تماس بگیر.")
            return
        if data.get("purchase_processing"):
            return
        if not _valid_purchase_data(data):
            await _edit_callback(callback, state, "اطلاعات سفارش نامعتبر است. از ابتدا شروع کن.", buy_type_selection_keyboard())
            await state.clear()
            return
        try:
            price, _stars, _discount, _discount_id = _build_order_prices(data)
            balance = get_balance(user.id)
        except Exception:
            logger.exception("Could not validate payment")
            await _edit_callback(callback, state, "بررسی مبلغ یا موجودی ناموفق بود. دوباره فاکتور بگیر.")
            return
        if balance < price:
            await _edit_callback(callback, state,
                f"{premium_emoji('wallet', '●')} <b>موجودی کیف پول کافی نیست.</b>\n\n"
                f"موجودی فعلی: <b>{int(balance):,} تومان</b>\nمبلغ سفارش: <b>{price:,} تومان</b>\n\n"
                "کیف پول را شارژ کن و دوباره تلاش کن.", purchase_retry_keyboard(price))
            return

        await state.update_data(purchase_processing=True)
        await _edit_callback(callback, state,
            f"{premium_emoji('light', '●')} <b>در حال ثبت سفارش...</b>\n\nدر حال کسر موجودی و ساخت سرویس در پنل هستیم. لطفاً صبر کن.")

        order_key = str(data.get("idempotency_key") or "")
        try:
            _persist_pending_purchase(user.id, order_key, "processing")
        except Exception:
            logger.exception("Could not persist purchase lock before payment")
            await _edit_callback(callback, state,
                "ثبت امن سفارش در دیتابیس ناموفق بود؛ برای جلوگیری از کسر وجه، پرداخت انجام نشد.")
            await state.update_data(purchase_processing=False)
            return

        status, result = await _provision_purchase(user_id=user.id, data=data, paxiva=paxiva)
        if status == "success":
            result = result if isinstance(result, dict) else {}
            try:
                _clear_pending_purchase(user.id)
            except Exception:
                logger.exception("Could not clear persistent purchase marker after success")
            await state.clear()
            success_text = (
                f"{premium_emoji('true', '●')} <b>خرید سرویس با موفقیت انجام شد.</b>\n\n"
                f"<b>نام کانفیگ:</b>\n<code>{_safe_text(result.get('config_name'))}</code>\n\n"
                f"<b>لینک اشتراک:</b>\n<code>{_safe_text(result.get('link'))}</code>\n\n"
                f"{premium_emoji('safe', '●')} لینک اشتراک محرمانه است؛ آن را در اختیار دیگران قرار نده."
            )
            try:
                await callback.message.edit_text(success_text,
                    reply_markup=purchase_success_keyboard(int(result.get("client_id", 0))))
            except TelegramBadRequest as exc:
                if "message is not modified" not in str(exc).lower():
                    logger.exception("Could not display purchase success")
            return
        if status == "pending":
            _pending_purchase_users.add(user.id)
            try:
                _persist_pending_purchase(user.id, order_key, "pending_review")
            except Exception:
                logger.exception("Could not persist pending-review marker")
            await state.update_data(purchase_processing=False, purchase_pending=True)
            await _edit_callback(callback, state,
                f"{premium_emoji('warning', '●')} <b>سفارش نیازمند بررسی است.</b>\n\n{_safe_text(result)}")
            return
        try:
            _clear_pending_purchase(user.id)
        except Exception:
            logger.exception("Could not clear purchase marker after definitive failure")
        await state.update_data(purchase_processing=False, purchase_pending=False,
            idempotency_key=generate_idempotency_key(f"buy-{user.id}"))
        await _edit_callback(callback, state,
            f"{premium_emoji('warning', '●')} <b>{_safe_text(result)}</b>\n\nدر صورت کسر وجه، مبلغ به کیف پولت بازگردانده شده است.",
            purchase_retry_keyboard(price))


@router.callback_query(F.data == "buy:pay:stars")
async def stars_payment_not_enabled(callback: CallbackQuery):
    await callback.answer("پرداخت با Stars هنوز فعال نشده است. از کیف پول استفاده کن.", show_alert=True)


@router.callback_query(F.data.startswith("buy:configs:"))
async def send_all_subscription_configs(callback: CallbackQuery, paxiva: PaxivaClient):
    await callback.answer()
    try:
        client_id = int(callback.data.rsplit(":", 1)[-1])
        if client_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        await callback.message.answer("شناسه اشتراک معتبر نیست.")
        return
    try:
        # در نسخه بعدی paxiva.py این مسیر به متد عمومی get_client_configs منتقل می‌شود.
        getter = getattr(paxiva, "get_client_configs", None)
        if callable(getter):
            response = await getter(client_id)
        else:
            response = await paxiva._request("GET", f"/clients/{client_id}/configs")
        items = response.get("items", []) if isinstance(response, dict) else []
        if not isinstance(items, list) or not items:
            await callback.message.answer(
                f"{premium_emoji('warning', '●')} فعلاً کانفیگی از پنل دریافت نشد. کمی بعد دوباره تلاش کن.")
            return
        sent = 0
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"کانفیگ {index}").strip()
            link = str(item.get("link") or "").strip()
            if not _valid_config_uri(link):
                logger.warning("Invalid config URI returned for client %s, item %s", client_id, index)
                continue
            await callback.message.answer(
                f"{premium_emoji('world', '●')} <b>{_safe_text(name)}</b>\n\n<code>{_safe_text(link)}</code>")
            sent += 1
        if sent:
            await callback.message.answer(
                f"{premium_emoji('true', '●')} <b>{sent} کانفیگ با موفقیت ارسال شد.</b>\nهر کانفیگ را جداگانه کپی کن.")
        else:
            await callback.message.answer("هیچ لینک کانفیگ معتبری در پاسخ پنل نبود.")
    except Exception:
        logger.exception("Could not retrieve PAXIVA configs for client %s", client_id)
        await callback.message.answer(
            f"{premium_emoji('warning', '●')} دریافت کانفیگ‌ها از پنل ناموفق بود. کمی بعد دوباره تلاش کن.")


@router.message(BuyStates.waiting_discount_code, F.text == "/cancel")
async def cancel_buy(message: Message, state: FSMContext):
    data = await state.get_data()
    if int(data.get("user_id", 0)) != (message.from_user.id if message.from_user else 0):
        return
    await _edit_user_message(message, state,
        f"{premium_emoji('warning', '●')} <b>ورود کد تخفیف لغو شد.</b>\nبرای شروع دوباره از منوی خرید وارد شو.")
    await state.clear()

مرجع API نمایندگی
با این API می‌توانید ربات تلگرام، وب‌سایت یا هر سامانهٔ فروش خودتان را به پنل نمایندگی وصل کنید: کاربر بسازید، تمدید کنید و لینک اشتراک و میزان مصرف را بخوانید. هزینهٔ هر کار از همان اعتبار و موجودی حجمی حساب شما کم می‌شود و تغییرها همان لحظه در ربات و پنل وب هم دیده می‌شوند.

آدرس پایه
https://panel.nyxcraft.ir/api/v1/
قالب داده
بدنهٔ درخواست و پاسخ هر دو با قالب JSON هستند. در درخواست‌های دارای بدنه، هدر Content-Type: application/json را هم بفرستید.
زمان
همهٔ زمان‌ها ثانیهٔ یونیکس (UTC) هستند.
حجم
مصرف به بایت و سقف حجم به گیگابایت است.
نسخه
v1 — ممکن است فیلد تازه‌ای به پاسخ‌ها اضافه شود، اما فیلدی حذف یا تغییرنام داده نمی‌شود. کد شما باید فیلدهای ناشناخته را نادیده بگیرد.
احراز هویت
کلید API را در هدر Authorization هر درخواست بفرستید. کلید را از ربات (پنل نمایندگی ← API) یا از پنل وب (تنظیمات ← API) می‌سازید. هر حساب حداکثر پنج کلید فعال دارد و هر کلید فقط یک بار، هنگام ساخت، نمایش داده می‌شود؛ پس همان لحظه آن را ذخیره کنید.

هدر
کپی
Authorization: Bearer rk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
کلید را فقط در سمت سرور نگه دارید و آن را در اپلیکیشن موبایل یا کد مرورگر نگذارید.
اگر کلیدی لو رفت، فوراً حذفش کنید؛ درخواست‌های بعدی با آن کلید پاسخ 401 می‌گیرند.
برای هر سامانه کلید جداگانه بسازید تا در صورت نیاز فقط همان را حذف کنید.
تکرار امن (Idempotency-Key)
درخواست‌های هزینه‌دار (ساخت کاربر، تمدید، افزایش دستگاه) را با یک شناسهٔ یکتا در هدر Idempotency-Key بفرستید؛ مثلاً شمارهٔ سفارش در سامانهٔ خودتان. اگر پاسخ به شما نرسید، همان درخواست را با همان شناسه دوباره بفرستید: نتیجهٔ درخواست اول برگردانده می‌شود و هزینه دوباره کم نمی‌شود.

هدر
کپی
Idempotency-Key: order-10452
شناسه بین ۱ تا ۱۰۰ نویسه است و فقط حروف انگلیسی، عدد و _ . : - می‌پذیرد. تا هفت روز نگه داشته می‌شود.
در ساخت کاربر، پاسخ تکراری فیلد "replayed": true دارد.
اگر درخواست اول رد شود (مثلاً چون اعتبار کافی نبود)، همان شناسه برای تلاش بعدی آزاد می‌ماند.
محدودیت درخواست
هر حساب در هر دقیقه تا 300 درخواست می‌فرستد که حداکثر 60 تای آن می‌تواند درخواست تغییر (ساخت، تمدید و مانند آن) باشد. درخواست‌های تغییر یکی‌یکی انجام می‌شوند؛ پیش از رسیدن پاسخ یکی، درخواست بعدی را نفرستید. پاسخ 429 فیلد retry_after (به ثانیه) دارد و می‌گوید چه زمانی دوباره امتحان کنید.

خطاها
پاسخ ناموفق همیشه یک کد وضعیت HTTP دارد و بدنه‌اش یک شیء JSON است با error (کد ثابت برای منطق برنامهٔ شما) و message (متن فارسی که می‌توانید به کاربر نشان دهید). گاهی فیلدهای دیگری مثل cost و credits هم دارد.

نمونه
کپی
{
  "error": "short",
  "message": "این کاربر ۲ اعتبار لازم دارد و اعتبار شما ۱ است.",
  "cost": 2,
  "credits": 1
}
وضعیت	error	معنا
400	bad_json · idempotency_key · bad	بدنهٔ درخواست JSON معتبر نیست، یا مقدار Idempotency-Key نامعتبر است.
401	auth	کلید ارسال نشده، نامعتبر است یا حذف شده است.
403	closed · blocked · not_reseller	API فعلاً بسته است، یا حساب مسدود شده، یا دیگر نمایندگی ندارد.
404	not_found	کاربر یا آدرس پیدا نشد. کاربرِ نمایندهٔ دیگر هم برای شما «پیدا نشد» است.
409	short · pool_empty · changed · cost · in_progress · trial_quota	اعتبار یا موجودی حجمی کافی نیست؛ کاربر یا فهرست در فاصلهٔ خواندن و اجرا تغییر کرده؛ هزینه از max_cost بیشتر است؛ درخواست قبلیِ همین Idempotency-Key هنوز در حال انجام است؛ یا سهمیهٔ اکانت تست امروز تمام شده است.
413	too_large	بدنهٔ درخواست از ۶۴ کیلوبایت بیشتر است.
422	name · gb · ips · days · periods · devices · kind · expired · trial · tags · url · all_hidden	مقدار یکی از فیلدها خارج از محدوده است یا این کار برای این نوع کاربر ممکن نیست (مثلاً برای اکانت تست تا پیش از تبدیل، سقف حجم و دستگاه تعیین نمی‌شود).
429	slow_down · busy	تعداد درخواست‌ها از سقف بیشتر است، یا تغییر قبلی هنوز تمام نشده. بعد از retry_after ثانیه دوباره بفرستید.
502 · 503	panel_down	سرور موقتاً پاسخ نمی‌دهد. چند دقیقه بعد دوباره امتحان کنید.
شیء کاربر
هر درخواستی که به یک کاربر مربوط باشد، با همین شیء پاسخ می‌دهد.

فیلدها
id	integer	شناسهٔ کاربر
kind	string	unl (نامحدود، با اعتبار) یا vol (حجمی، از موجودی)
name / note	string	نام و یادداشت داخلی
state	string	وضعیت؛ جدول زیر
enabled	boolean	false یعنی کاربر را شما متوقف کرده‌اید
expires_at	integer | null	انقضا (ثانیهٔ یونیکس)؛ null برای کاربر حجمی بدون انقضا
volume_gb	number	سقف حجم دوره به گیگابایت (برای کمتر از یک گیگ اعشاری است، مثلاً 0.1953125)؛ ۰ یعنی بدون سقف
volume_mb	integer	همان سقف به مگابایت (مثلاً ۲۰۰ برای کاربر ۲۰۰ مگابایتی)
used_bytes	integer | null	مصرف دورهٔ فعلی به بایت
consumed_bytes	integer	کل مصرف از ابتدا؛ برای کاربر حجمی همان مقداری که از موجودی کم شده
devices / paid_devices	integer	دستگاه همزمان، و دستگاه‌های پرداخت‌شده تا زمان انقضا
link / sub_id	string	لینک اشتراک (اگر دامنهٔ اختصاصی فعال باشد، روی آن دامنه) و شناسهٔ آن
tags	string[]	برچسب‌های کاربر
trial / trial_mb	boolean / integer	آیا اکانت تست رایگان است، و حجم آن به مگابایت
hidden_servers	string[] | null	سرورهای پنهان‌شدهٔ مخصوص این کاربر؛ null یعنی پیروی از پیش‌فرض شما
live / pending	boolean	مصرف همین لحظه از سرور خوانده شده / آخرین تغییر هنوز به سرور نرسیده
daily_cap_gb / daily_used_bytes / daily_cut	integer / integer | null / boolean	سقف مصرف روزانه (۰ یعنی بدون سقف)، مصرف امروز، و اینکه امروز به سقف رسیده و قطع است
cut_at / resume_at	integer | null	زمان‌بندی قطع و وصل (ثانیهٔ یونیکس)
مقدارهای state
active	فعال
ending	فعال، اما نزدیک انقضا
depleted	حجم این دوره تمام شده است
daycut	به سقف مصرف امروز رسیده؛ فردا خودکار وصل می‌شود
expired	منقضی شده است
paused	توسط شما متوقف شده
blocked	موجودی پنل حجمی تمام شده؛ تا خرید حجم، قطع است
creating	در حال ساخت روی سرور؛ چند ثانیه بعد فعال می‌شود
deleting	در حال حذف
وب‌هوک: رویدادها و امضا
وقتی برای کاربران یا موجودی شما اتفاقی می‌افتد، یک درخواست POST با بدنهٔ JSON به آدرس وب‌هوک شما فرستاده می‌شود. اگر پاسخ 2xx دریافت نکنیم، ارسال را بعد از ۱، ۵ و ۱۵ دقیقه و سپس بعد از ۱، ۳، ۶ و ۱۲ ساعت تکرار می‌کنیم و در پایان متوقف می‌شویم و در تلگرام به شما اطلاع می‌دهیم. هر رویداد در همهٔ تلاش‌ها id یکسان دارد؛ با آن رویدادهای تکراری را نادیده بگیرید.

بدنه
کپی
{
  "id": "evt_1041",
  "type": "client.created",
  "created_at": 1764633605,
  "data": { "client": { "id": 812, "name": "Ali", "link": "https://…", "...": "..." } }
}
هدرها
X-Webhook-Id	شناسهٔ رویداد (همان id بدنه)
X-Webhook-Event	نوع رویداد
X-Webhook-Timestamp	زمان ارسال (ثانیهٔ یونیکس)
X-Webhook-Signature	مقدار v1= به‌همراه HMAC-SHA256 (هگز) روی رشتهٔ «Timestamp + نقطه + بدنهٔ خام»، با کلید امضای شما
امضا را همیشه بررسی کنید و رویدادی را که Timestamp آن بیش از پنج دقیقه با ساعت سرور شما فاصله دارد رد کنید:

Node.js
کپی
const crypto = require("crypto");
function verify(rawBody, headers, secret) {
  const ts = headers["x-webhook-timestamp"];
  const sig = (headers["x-webhook-signature"] || "").replace(/^v1=/, "");
  const mac = crypto.createHmac("sha256", secret).update(ts + "." + rawBody).digest("hex");
  const fresh = Math.abs(Date.now() / 1000 - Number(ts)) < 300;
  return fresh && sig.length === mac.length && crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(mac));
}
Python
کپی
import hmac, hashlib, time
def verify(raw_body: bytes, headers, secret: str) -> bool:
    ts = headers["X-Webhook-Timestamp"]
    sig = headers.get("X-Webhook-Signature", "").removeprefix("v1=")
    mac = hmac.new(secret.encode(), ts.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return abs(time.time() - int(ts)) < 300 and hmac.compare_digest(sig, mac)
رویدادها
client.created	کاربر روی سرور ساخته شد و لینک او آماده است
client.renewed	کاربر تمدید شد (نامحدود با اعتبار، حجمی با انقضای تازه)
client.converted	اکانت تست به کاربر دائمی تبدیل شد
client.expiring	کاربر به‌زودی منقضی می‌شود (فیلد days_left)
client.expired	کاربر یا اکانت تست منقضی شد
client.usage_warning	مصرف کاربر به درصد هشدارِ سقف حجم رسید (فیلد percent)
client.depleted	حجم کاربر تمام شد
client.daily_limit	کاربر به سقف مصرف روزانه رسید و تا فردا قطع شد (فیلد daily_gb)
client.deleted	کاربر حذف شد
credits.added	اعتبار خریداری شد (auto برابر true یعنی با شارژ خودکار)
credits.low	اعتبار از حد هشدار پایین‌تر رفت
pool.added	حجم به موجودی پنل حجمی اضافه شد
pool.low	موجودی حجمی رو به پایان است
pool.empty	موجودی حجمی تمام شد و کاربران حجمی قطع هستند
topup.failed	شارژ خودکار انجام نشد (دلیل در فیلد reason)
test	ارسال آزمایشی از ربات یا پنل
در رویدادهای کاربر، data.client همان شیء کاربر است (بدون فیلدهای لحظه‌ای مانند live)؛ رویدادهای اعتبار و حجم هم مقدارهای مربوط به خودشان را دارند.

حساب
GET
/me
وضعیت حساب
موجودی پنل حجمی (پرداخت به‌ازای مصرف)، سطح نمایندگی، شمار کاربران و محدودیت‌ها. پیش از ساخت کاربر، موجودی را از اینجا بخوانید. credits و unlimited_panel فقط برای کسانی کاربرد دارند که هنوز پنل نامحدود (اعتبار) دارند.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/me" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{
  "id": 7210936715,
  "brand": "Aria VPN",
  "credits": 0,
  "unlimited_panel": false,
  "pool": { "gb": 512, "used_bytes": 196280473600, "left_bytes": 353482752000, "off": false },
  "counts": { "clients": 58, "active": 51, "ending": 4, "expired": 3, "paused": 1, "creating": 0, "vol": 12 },
  "tier": {
    "key": "silver", "percent_off": 5, "sales_30d": 23550000,
    "next": { "key": "gold", "need_toman": 36450000, "percent_off": 10 }
  },
  "rules": {
    "days_per_credit": 30, "max_devices": 10, "periods_max": 12,
    "volume_gb_max": 10000, "vol_days_max": 3650, "name_max": 32, "note_max": 200
  },
  "shop": { "credits_open": false, "volume_open": true }
}
کاربران
GET
/clients
فهرست کاربران
فهرست کاربران شما، به‌صورت صفحه‌بندی‌شده. مصرفی که در این فهرست می‌بینید آخرین مقدار ثبت‌شده است؛ برای مصرف لحظه‌ای جزئیات کاربر را بخوانید.

پارامترهای آدرس
status	string	all (پیش‌فرض)، active، soon (رو به اتمام)، expired، paused، depleted (حجم دوره تمام)، trial (اکانت تست)
kind	string	unl (نامحدود) یا vol (حجمی)؛ خالی یعنی هر دو
q	string	جستجو در نام، یادداشت و برچسب (حداکثر 32 حرف)
tag	string	فقط کاربرانی که این برچسب را دارند
sort	string	new (پیش‌فرض)، old، expiry
page	integer	از ۱
size	integer	۱ تا 200؛ پیش‌فرض ۵۰
درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/clients" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{
  "items": [ { "id": 812, "kind": "unl", "name": "Ali", "state": "active", "...": "..." } ],
  "total": 58,
  "page": 1,
  "size": 50
}
POST
/clients
ساخت کاربر
ساخت کاربر نامحدود به‌اندازهٔ «دوره × دستگاه» اعتبار برمی‌دارد. ساخت کاربر حجمی هزینه‌ای ندارد و مصرف واقعی او از موجودی پنل حجمی کم می‌شود. پاسخ شامل کاربر ساخته‌شده و لینک اشتراک اوست.

این درخواست هزینه دارد. آن را با هدر Idempotency-Key بفرستید تا تکرارش هزینهٔ دوباره نداشته باشد.

بدنهٔ درخواست
kind	string	vol (حجمی، از موجودی) یا unl (نامحدود، با اعتبار؛ فقط برای کسی که هنوز اعتبار یا کاربر نامحدود دارد)؛ اگر نفرستید vol است، مگر اینکه هنوز پنل نامحدود داشته باشید
name	string	حداکثر 32 حرف؛ اگر نفرستید نام خودکار داده می‌شود
periods	integer	فقط unl؛ تعداد دوره‌های ۳۰ روزه، ۱ تا 12
devices	integer	تعداد دستگاه همزمان؛ پیش‌فرض ۱
volume_gb	number	سقف حجم به گیگابایت، ۰ تا 10000؛ ۰ یعنی بدون سقف. مقدار اعشاری هم مجاز است (۰٫۵ یعنی ۵۱۲ مگابایت)
volume_mb	integer	به‌جای volume_gb، برای کاربرانی با حجم کمتر از یک گیگ (مثلاً ۲۰۰ مگابایت): سقف حجم به مگابایت. اگر هر دو را بفرستید، volume_gb ملاک است
days	integer	فقط vol؛ مدت به روز، ۰ تا 3650؛ ۰ یعنی بدون انقضا
tags	string[]	برچسب‌ها (حداکثر ۵، هرکدام تا ۲۰ حرف)
trial	boolean	true یعنی اکانت تست رایگان (حجم و مدت آن را پشتیبانی تعیین کرده و یک دستگاه دارد). در این حالت periods، devices، volume_gb و days نادیده گرفته می‌شوند. سهمیهٔ روزانه را از GET /trial بخوانید
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: order-10452" \
  -H "Content-Type: application/json" \
  -d '{"kind":"unl","name":"Ali","periods":1,"devices":1,"volume_gb":0,"tags":["vip"]}'
پاسخ 200
کپی
{
  "id": 812,
  "kind": "unl",
  "name": "Ali",
  "note": null,
  "state": "active",
  "enabled": true,
  "expires_at": 1767225600,
  "volume_gb": 0,
  "volume_mb": 0,
  "used_bytes": 1073741824,
  "devices": 1,
  "link": "https://panel.nyxcraft.ir/s/9f2c4e1a7b3d5f60",
  "sub_id": "9f2c4e1a7b3d5f60",
  "tags": ["vip"],
  "trial": false,
  "trial_mb": 0,
  "hidden_servers": null,
  "created_at": 1764633600,
  "consumed_bytes": 1073741824,
  "live": true,
  "pending": false,
  "credits_spent": 1,
  "paid_devices": 1,
  "periods_left": 1,
  "activated_at": 1764633605,
  "renewed_at": null
}
GET
/clients/{id}
جزئیات کاربر
کاربر همراه با مصرف لحظه‌ای که همان موقع از سرور خوانده می‌شود (live برابر true است). اگر سرور در دسترس نباشد، آخرین مقدار ثبت‌شده برمی‌گردد و live برابر false است.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/clients/812" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{
  "id": 812,
  "kind": "unl",
  "name": "Ali",
  "note": null,
  "state": "active",
  "enabled": true,
  "expires_at": 1767225600,
  "volume_gb": 0,
  "volume_mb": 0,
  "used_bytes": 1073741824,
  "devices": 1,
  "link": "https://panel.nyxcraft.ir/s/9f2c4e1a7b3d5f60",
  "sub_id": "9f2c4e1a7b3d5f60",
  "tags": ["vip"],
  "trial": false,
  "trial_mb": 0,
  "hidden_servers": null,
  "created_at": 1764633600,
  "consumed_bytes": 1073741824,
  "live": true,
  "pending": false,
  "credits_spent": 1,
  "paid_devices": 1,
  "periods_left": 1,
  "activated_at": 1764633605,
  "renewed_at": null
}
GET
/clients/{id}/configs
کانفیگ‌های تکی
لینک کانفیگ هر سرور به‌صورت جداگانه، برای برنامه‌هایی که لینک اشتراک را نمی‌پذیرند.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/clients/812/configs" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{
  "items": [
    { "name": "Germany - Ali", "link": "vless://…" },
    { "name": "Netherlands - Ali", "link": "vless://…" }
  ]
}
مدیریت کاربر
POST
/clients/{id}/renew
تمدید کاربر نامحدود
مدت تمدید به انقضای فعلی اضافه می‌شود (اگر کاربر منقضی شده باشد، از همین لحظه حساب می‌شود) و حجم دوره از نو شروع می‌شود. هزینه برابر است با «دوره × دستگاه‌های فعلی». لینک اشتراک تغییر نمی‌کند.

این درخواست هزینه دارد. آن را با هدر Idempotency-Key بفرستید تا تکرارش هزینهٔ دوباره نداشته باشد.

بدنهٔ درخواست
periods	integer	۱ تا 12؛ پیش‌فرض ۱
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/renew" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: order-10452" \
  -H "Content-Type: application/json" \
  -d '{"periods":1}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/expiry
انقضای کاربر حجمی
روزهای تازه به انقضای فعلی (یا اگر گذشته باشد، به امروز) اضافه می‌شود. تمدید زمانی کاربر حجمی هزینه‌ای ندارد.

بدنهٔ درخواست
daysالزامی	integer	۰ تا 3650؛ ۰ یعنی بدون انقضا
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/expiry" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"days":30}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/reset
شروع دوبارهٔ حجم
فقط برای کاربر حجمی: شمارش مصرف از همین لحظه از صفر شروع می‌شود. مصرف قبلی که از موجودی پنل کم شده، برنمی‌گردد.

درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/reset" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/volume
سقف حجم
سقف حجم دورهٔ کاربر را تغییر می‌دهد. اگر مصرف فعلی از سقف تازه بیشتر باشد، کاربر تا تمدید یا افزایش سقف قطع می‌شود.

بدنهٔ درخواست
volume_gb	number	یکی از volume_gb یا volume_mb الزامی است. بازه: ۰ تا 10000؛ ۰ یعنی بدون سقف؛ مقدار اعشاری هم مجاز است (۰٫۵ یعنی ۵۱۲ مگابایت)
volume_mb	integer	به‌جای volume_gb، برای کمتر از یک گیگ: سقف به مگابایت (مثلاً ۲۰۰)
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/volume" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"volume_gb":50}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/devices
تعداد دستگاه
برای کاربر حجمی رایگان است. برای کاربر نامحدود، کم کردن دستگاه رایگان است و افزایش تا سقف دستگاه‌های پرداخت‌شده هم هزینه ندارد؛ بیشتر از آن، به ازای هر دستگاه اضافه و هر دورهٔ باقی‌مانده یک اعتبار کم می‌شود.

این درخواست هزینه دارد. آن را با هدر Idempotency-Key بفرستید تا تکرارش هزینهٔ دوباره نداشته باشد.

بدنهٔ درخواست
devicesالزامی	integer	تعداد تازهٔ دستگاه همزمان
max_cost	integer	بیشترین اعتباری که می‌پذیرید. اگر هزینه از آن بیشتر باشد، چیزی کم نمی‌شود و پاسخ 409 همراه با مقدار cost برمی‌گردد
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/devices" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: order-10452" \
  -H "Content-Type: application/json" \
  -d '{"devices":2,"max_cost":1}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/pause
توقف
تا زمانی که دوباره فعال نشود، کاربر وصل نمی‌شود. زمان انقضا در این مدت ادامه دارد. با until می‌توانید تعیین کنید که خودکار چه زمانی دوباره وصل شود.

بدنهٔ درخواست
until	integer	زمان وصل شدن دوباره (ثانیهٔ یونیکس)، از حالا تا یک سال دیگر. اگر نفرستید، کاربر تا زمانی که خودتان فعالش نکنید متوقف می‌ماند
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/pause" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"until":1767225600}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/resume
فعال کردن دوباره
کاربر متوقف‌شده دوباره وصل می‌شود. کاربر منقضی‌شده با این درخواست فعال نمی‌شود؛ باید او را تمدید کنید.

درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/resume" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/rotate
لینک تازه
شناسه و لینک اشتراک تازه‌ای ساخته می‌شود و لینک قبلی بلافاصله از کار می‌افتد. لینک تازه را دوباره برای مشتری بفرستید.

درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/rotate" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/name
تغییر نام
نام کاربر را عوض می‌کند؛ این نام در پنل و در نام کانفیگ‌ها دیده می‌شود.

بدنهٔ درخواست
nameالزامی	string	حداکثر 32 حرف
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/name" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Ali Rezaei"}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/note
یادداشت
یادداشت داخلی شما؛ مشتری آن را نمی‌بیند.

بدنهٔ درخواست
note	string	حداکثر 200 حرف؛ رشتهٔ خالی یادداشت را حذف می‌کند
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/note" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"note":"telegram: @ali"}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

DELETE
/clients/{id}
حذف کاربر
کاربر قطع می‌شود و به سطل بازیافت می‌رود (trashed: true). تا ۲۴ ساعت می‌توانید او را با POST /trash/{id}/restore برگردانید و پس از آن حذف نهایی می‌شود. با ?purge=true همان لحظه برای همیشه حذف می‌شود. اگر کاربر نامحدود هیچ مصرفی نداشته باشد، اعتبارش هنگام حذف نهایی برگردانده می‌شود (refund). مصرفِ کاربر حجمی که از موجودی کم شده، برنمی‌گردد.

پارامترهای آدرس
purge	boolean	true یعنی حذف نهایی، بدون عبور از سطل بازیافت
درخواست
کپی
curl -X DELETE "https://panel.nyxcraft.ir/api/v1/clients/812" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "done": true, "refund": 1, "trashed": true }
POST
/clients/{id}/tags
برچسب‌ها
برچسب‌های کاربر با این فهرست جایگزین می‌شوند؛ آرایهٔ خالی یعنی بدون برچسب. با GET /clients?tag=vip می‌توانید کاربران دارای یک برچسب را پیدا کنید.

بدنهٔ درخواست
tagsالزامی	string[]	حداکثر ۵ برچسب، هرکدام تا ۲۰ حرف (حرف، عدد، _ و -)
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/tags" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tags":["vip","telegram"]}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

GET
/tags
همهٔ برچسب‌ها
برچسب‌هایی که کاربران شما دارند، همراه با تعداد کاربرِ هر برچسب.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/tags" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "tags": [ { "tag": "vip", "n": 12 }, { "tag": "telegram", "n": 40 } ] }
سقف روزانه، زمان‌بندی و سطل بازیافت
POST
/clients/{id}/daily-cap
سقف مصرف روزانه
کاربر در هر روز (به وقت تهران) تا این مقدار مصرف می‌کند. وقتی به سقف برسد تا نیمه‌شب قطع می‌ماند و فردا خودکار وصل می‌شود (state برابر daycut). مصرف هر چند دقیقه یک بار بررسی می‌شود. مقدار ۰ سقف را برمی‌دارد. روی اکانت تست کار نمی‌کند.

بدنهٔ درخواست
gbالزامی	integer	۰ تا 10000 گیگ
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/daily-cap" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"gb":5}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/clients/{id}/schedule
زمان‌بندی قطع و وصل
کاربر در cut_at قطع و در resume_at دوباره وصل می‌شود (می‌توانید هرکدام را خالی بگذارید). اگر هر دو null باشند، زمان‌بندی لغو می‌شود.

بدنهٔ درخواست
cut_at	integer | null	ثانیهٔ یونیکس؛ از حالا تا یک سال دیگر
resume_at	integer | null	ثانیهٔ یونیکس؛ بعد از cut_at
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/schedule" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"cut_at":1767225600,"resume_at":1767312000}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

GET
/clients/{id}/ips
آدرس‌های اخیر کاربر
آدرس‌هایی که کاربر در ۳۰ دقیقهٔ اخیر با آن‌ها دیده شده، همراه با سرور مربوط و تعداد دستگاه مجاز. over برابر true یعنی تعداد آدرس‌ها از دستگاه‌های مجاز بیشتر است.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/clients/812/ips" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "limit": 1, "count": 2, "over": true, "items": [ { "ip": "198.51.100.7", "at": 1767225000, "node": "nl-ams-1" } ] }
POST
/clients/{id}/ips/clear
پاک کردن فهرست آدرس‌ها
فهرست از نو شروع می‌شود تا ببینید چه آدرس‌هایی واقعاً وصل می‌شوند.

درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/ips/clear" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "limit": 1, "count": 0, "over": false, "items": [] }
GET
/sharing
اشتراک‌گذاری مشکوک
کاربرانی که در ۳۰ دقیقهٔ اخیر با تعداد آدرسی بیشتر از دستگاه‌های مجازشان وصل بوده‌اند؛ بیشترین تخطی اول می‌آید.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/sharing" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "items": [ { "id": 812, "name": "Ali", "limit": 1, "count": 3, "last_at": 1767225000 } ], "at": 1767225100 }
GET
/trash
سطل بازیافت
کاربران حذف‌شده‌ای که هنوز مهلت ۲۴ ساعتهٔ بازگردانی‌شان تمام نشده است.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/trash" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "items": [ { "id": 812, "name": "Ali", "kind": "unl", "trashed_at": 1767225000, "expires_at": 1767311400 } ], "hours": 24 }
POST
/trash/{id}/restore
برگرداندن از سطل
کاربر همان‌طور که بود، با همان لینک، دوباره وصل می‌شود.

درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/trash/812/restore" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

POST
/trash/{id}/purge
حذف نهایی از سطل
کاربر همین لحظه برای همیشه حذف می‌شود؛ اعتبار کاربر نامحدودِ مصرف‌نشده برگردانده می‌شود.

درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/trash/812/purge" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "done": true, "refund": 1 }
GET
/audit
گزارش فعالیت
فهرست تغییرها و اینکه چه کسی هرکدام را انجام داده است (شما از ربات، مینی‌اپ یا پنل وب، یکی از همکاران، کلید API، سیستم یا پشتیبانی). سابقه ۱۸۰ روز نگه داشته می‌شود و جدیدترین‌ها اول می‌آیند.

پارامترهای آدرس
client	integer	فقط تغییرهای همین کاربر
group	string	users · access · delete · account · team
who	string	owner · system · api · admin، یا شناسهٔ همکار
before	integer	شناسهٔ آخرین مورد صفحهٔ قبل، برای گرفتن صفحهٔ بعد
درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/audit" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "items": [ { "id": 41, "at": 1767225000, "who": "API: bot", "action": "renew", "text": "تمدید ۳۰ روز — ۱ اعتبار", "client_id": 812, "client_name": "Ali" } ], "more": false, "days": 180 }
اکانت تست
GET
/trial
سهمیهٔ اکانت تست
تعداد اکانت تستی که در ۲۴ ساعت می‌توانید بسازید، تعداد ساخته‌شده و مشخصات هر تست. اکانت تست با POST /clients و trial: true ساخته می‌شود و دو روز پس از پایان خودکار حذف می‌شود.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/trial" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "open": true, "per_day": 5, "used": 2, "mb": 300, "minutes": 60, "vol": true }
POST
/clients/{id}/convert
تبدیل تست به کاربر دائمی
اکانت تست با همان لینک به کاربر عادی تبدیل می‌شود. تست نامحدود با اعتبار «دوره × دستگاه» تبدیل می‌شود؛ تست حجمی رایگان است و انقضا و سقف حجم را شما تعیین می‌کنید (مصرف از این لحظه از صفر شمرده می‌شود). روی کاربری که تست نیست اثری ندارد.

این درخواست هزینه دارد. آن را با هدر Idempotency-Key بفرستید تا تکرارش هزینهٔ دوباره نداشته باشد.

بدنهٔ درخواست
periods	integer	تست نامحدود: ۱ تا 12؛ پیش‌فرض ۱
days	integer	تست حجمی: ۰ تا 3650 روز از همین لحظه؛ ۰ یعنی بدون انقضا؛ پیش‌فرض ۳۰
volume_gb	number	تست حجمی: سقف حجم به گیگابایت؛ ۰ یعنی تا موجودی پنل
volume_mb	integer	تست حجمی: به‌جای volume_gb، سقف به مگابایت
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/convert" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: order-10452" \
  -H "Content-Type: application/json" \
  -d '{"periods":1}'
پاسخ 200
شیء کاربر با وضعیت تازه؛ فهرست فیلدها و نمونهٔ کامل را ببینید.

تمدید همه
GET
/renew-all
کاربرانی که تمدید همه می‌گیرد
کاربران نامحدود (غیر از اکانت تست) که رو به اتمام‌اند یا در سه روز اخیر منقضی شده‌اند، همراه با هزینهٔ تمدید یک دوره برای همه و اعتبار فعلی شما.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/renew-all" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "items": [ { "id": 812, "name": "Ali", "devices": 1, "...": "..." } ], "cost": 14, "credits": 40, "days": 30 }
POST
/renew-all
تمدید همه
همان فهرستی را که خواندید یک دوره تمدید می‌کند. count و cost باید همان اعداد پاسخ GET باشند؛ اگر فهرست در این فاصله تغییر کرده باشد، چیزی کم نمی‌شود و پاسخ 409 با خطای changed برمی‌گردد.

این درخواست هزینه دارد. آن را با هدر Idempotency-Key بفرستید تا تکرارش هزینهٔ دوباره نداشته باشد.

بدنهٔ درخواست
countالزامی	integer	تعداد کاربران فهرست (count در پاسخ GET)
costالزامی	integer	هزینهٔ کل فهرست به اعتبار (cost در پاسخ GET)
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/renew-all" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: order-10452" \
  -H "Content-Type: application/json" \
  -d '{"count":7,"cost":14}'
پاسخ 200
کپی
{ "renewed": [812, 813], "failed": [], "cost": 14 }
سرورهای اشتراک
GET
/servers
سرورها و پیش‌فرض شما
سرورهای لینک اشتراک (names، به ترتیبی که تعیین کرده‌اید)، سرورهایی که برای همهٔ کاربران پنهان کرده‌اید (hidden) و نام‌هایی که به سرورها داده‌اید (labels). اگر سروری مشکل داشت، پنهانش کنید تا برنامه‌ها با به‌روزرسانی بعدی اشتراک به سرورهای دیگر وصل شوند؛ لینک‌ها تغییر نمی‌کنند.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/servers" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "names": ["🇩🇪 Germany", "🇳🇱 Netherlands"], "hidden": ["🇩🇪 Germany"], "own": false, "own_users": 2, "labels": [{ "name": "🇳🇱 Netherlands", "label": "🇳🇱 هلند" }] }
POST
/servers
پنهان کردن، نام و ترتیب سرورها
این تنظیم برای همهٔ کاربرانی است که فهرست سرورِ مخصوص خودشان را ندارند. نمی‌توان همهٔ سرورها را پنهان کرد. با all: true انتخاب مخصوص هر کاربر هم پاک می‌شود. order و labels برای همهٔ کاربران شماست و هرکدام را نفرستید، بدون تغییر می‌ماند؛ برای بازگرداندن به حالت اول order: [] و labels: [] بفرستید. hidden فقط وقتی لازم است که order و labels را نفرستاده باشید.

بدنهٔ درخواست
hidden	string[]	نام سرورهایی که نباید در لینک باشند (همان names)
all	boolean	true یعنی همهٔ کاربران از این تنظیم پیروی کنند
order	string[]	نام سرورها به ترتیبی که در برنامهٔ کاربران نمایش داده شوند (سرورهایی که ذکر نشوند، بعد از آن‌ها می‌آیند)
labels	{ name, label }[]	نامی که کاربران به‌جای نام اصلی سرور می‌بینند (تا ۴۰ حرف)؛ سروری که در این فهرست نباشد با نام اصلی‌اش نمایش داده می‌شود
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/servers" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"order":["🇳🇱 Netherlands","🇩🇪 Germany"],"labels":[{"name":"🇳🇱 Netherlands","label":"🇳🇱 هلند"}]}'
پاسخ 200
کپی
{ "names": ["🇳🇱 Netherlands", "🇩🇪 Germany"], "hidden": [], "own": false, "own_users": 0, "labels": [{ "name": "🇳🇱 Netherlands", "label": "🇳🇱 هلند" }] }
POST
/clients/{id}/servers
سرورهای یک کاربر
سرورهای پنهان‌شدهٔ مخصوص یک کاربر؛ اگر hidden برابر null باشد، کاربر از پیش‌فرض شما پیروی می‌کند.

بدنهٔ درخواست
hiddenالزامی	string[] | null	نام سرورهای پنهان، یا null برای پیروی از پیش‌فرض
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/clients/812/servers" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"hidden":[]}'
پاسخ 200
کپی
{ "names": ["🇩🇪 Germany", "🇳🇱 Netherlands"], "hidden": [], "own": true, "own_users": 0, "labels": [] }
هشدار و شارژ خودکار
GET
/settings
تنظیمات هشدار و شارژ خودکار
هشدارهای تلگرام (انقضا، حجم کاربران، گزارش ماهانه)، حد هشدار اعتبار و حجم، و مقدار شارژ خودکار از کیف پول.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/settings" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{
  "alert_expiry": true, "alert_usage": true, "alert_report": true,
  "low_credits": 5, "low_gb": 0, "auto_credits": 50, "auto_gb": 0, "auto_failed": false,
  "credits": 42, "pool": null, "wallet": { "open": true, "balance": 2100000 },
  "limits": { "credits": { "min": 10, "max": 1000 }, "gb": { "min": 256, "max": 50000 }, "usage_warn": 80, "auto_per_day": 10 }
}
POST
/settings
تغییر تنظیمات
فقط فیلدهایی که بفرستید تغییر می‌کنند. شارژ خودکار وقتی اعتبار (یا موجودی حجمی) از حد هشدار پایین‌تر برود، از کیف پول و با قیمت و تخفیف سطح شما خرید می‌کند؛ حداکثر ده بار در روز.

بدنهٔ درخواست
alert_expiry / alert_usage / alert_report	boolean	پیام‌های تلگرام
low_credits	integer	حد هشدار اعتبار؛ ۰ یعنی خاموش
low_gb	integer	حد هشدار موجودی حجمی به گیگابایت؛ ۰ یعنی ده درصد آخرین خرید
auto_credits	integer	اعتبار هر شارژ خودکار؛ ۰ یعنی خاموش
auto_gb	integer	گیگ هر شارژ خودکار؛ ۰ یعنی خاموش
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/settings" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"low_credits":10,"auto_credits":50}'
پاسخ 200
کپی
{ "alert_expiry": true, "...": "..." }
GET
/report/month
گزارش ماهانه
خلاصهٔ یک ماه شمسی: شمار کاربران ساخته‌شده، تمدیدشده و حذف‌شده، اعتبار و حجم خریداری‌شده و مصرف‌شده، مصرف کاربران و پورسانت.

پارامترهای آدرس
month	string	current (ماه جاری تا امروز؛ پیش‌فرض) یا previous (ماه قبل)
درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/report/month" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{
  "key": "1405-07", "label": "مهر ۱۴۰۵", "partial": true, "from": 1758400200, "to": 1760992200,
  "bought": 100, "spent": 87, "refunded": 0, "renewed": 31, "unl": 12, "vol": 5, "trials": 9, "deleted": 2,
  "gb": 1024, "orders": 3, "toman": 23000000, "commission": 450000, "subs": 1, "used": 901943132160, "running": 48
}
GET
/export/clients.csv
خروجی CSV
فایل CSV با کدگذاری UTF-8 که در اکسل هم باز می‌شود. سه فایل داریم: clients.csv (کاربران)، credits.csv (دفتر اعتبار) و volume.csv (دفتر حجم).

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/export/clients.csv" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
شماره,نام,نوع,اکانت تست,وضعیت,برچسب‌ها,...
812,Ali,نامحدود,,فعال,vip,...
وب‌هوک
GET
/webhook
وب‌هوک شما
آدرس، رویدادهای انتخاب‌شده، تعداد شکست‌های پیاپی و آخرین ارسال‌ها. راهنمای امضا و فهرست رویدادها در بخش «وب‌هوک» بالای همین صفحه است.

درخواست
کپی
curl -X GET "https://panel.nyxcraft.ir/api/v1/webhook" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{
  "open": true, "url": "https://mybot.example.com/hook", "events": ["client.created", "client.expired"],
  "all_events": [ { "key": "client.created", "label": "…" } ], "fails": 0, "has_secret": true,
  "log": [ { "id": 1041, "event": "client.created", "state": "done", "status": 200, "error": null, "attempts": 1, "at": 1764633605 } ]
}
POST
/webhook
تنظیم وب‌هوک
آدرس https (دامنه، نه IP؛ پورت ۴۴۳ یا ۸۴۴۳) و رویدادهای دلخواه. در بار اول کلید امضا ساخته می‌شود و فقط در همین پاسخ، در فیلد secret، نمایش داده می‌شود.

بدنهٔ درخواست
url	string	آدرس https
events	string[]	رویدادهایی که می‌خواهید؛ اگر نفرستید همهٔ رویدادها فرستاده می‌شود
درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/webhook" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://mybot.example.com/hook"}'
پاسخ 200
کپی
{ "url": "https://mybot.example.com/hook", "secret": "whsec_…", "...": "..." }
POST
/webhook/secret
کلید امضای تازه
کلید قبلی از همین لحظه باطل می‌شود؛ کلید تازه در فیلد secret همین پاسخ آمده است.

درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/webhook/secret" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "secret": "whsec_…", "...": "..." }
POST
/webhook/test
ارسال آزمایشی
یک رویداد test همین لحظه به آدرس شما فرستاده می‌شود و پاسخ سرور شما در جواب برمی‌گردد.

درخواست
کپی
curl -X POST "https://panel.nyxcraft.ir/api/v1/webhook/test" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "ok": true, "status": 200, "error": null }
DELETE
/webhook
حذف وب‌هوک
دیگر چیزی ارسال نمی‌شود و رویدادهای در صف دور ریخته می‌شوند.

درخواست
کپی
curl -X DELETE "https://panel.nyxcraft.ir/api/v1/webhook" \
  -H "Authorization: Bearer $API_KEY"
پاسخ 200
کپی
{ "url": null, "...": "..." }

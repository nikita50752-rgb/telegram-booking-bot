"""
Booking Bot — Telegram bot for appointment booking (salons, studios, car washes, tutors).

Features:
  * clients pick a service -> day -> free time slot -> leave name & phone
  * no double bookings (slots respect service duration)
  * automatic reminder to the client 24 hours before the visit
  * clients can view and cancel their bookings
  * the business owner gets instant notifications + /today and /week schedules
  * Russian / English interface (chosen automatically from the user's Telegram language)

Run:  python bot.py   (settings are read from .env, see .env.example)
"""

import asyncio
import html
import json
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

BASE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- settings
def load_env(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE per line), so no extra dependency is needed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env(BASE / ".env")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
TZ = timezone(timedelta(hours=int(os.environ.get("TZ_OFFSET_HOURS", "7"))))

CONFIG = json.loads((BASE / "business.json").read_text(encoding="utf-8"))
SERVICES: dict = CONFIG["services"]
WORK_START: int = CONFIG["work_hours"][0]
WORK_END: int = CONFIG["work_hours"][1]
DAYS_OFF: set = set(CONFIG.get("days_off", []))  # 0 = Monday ... 6 = Sunday
SLOT_STEP = CONFIG.get("slot_step_minutes", 30)
DAYS_AHEAD = CONFIG.get("days_ahead", 7)
REMIND_BEFORE = timedelta(hours=CONFIG.get("remind_hours_before", 24))

# ---------------------------------------------------------------- texts (RU / EN)
T = {
    "hello": {
        "ru": "👋 Здравствуйте! Это бот записи в <b>{name}</b>.\nВыберите, что хотите сделать:",
        "en": "👋 Hello! This is the booking bot of <b>{name}</b>.\nWhat would you like to do?",
    },
    "btn_book": {"ru": "📅 Записаться", "en": "📅 Book"},
    "btn_my": {"ru": "📋 Мои записи", "en": "📋 My bookings"},
    "btn_info": {"ru": "ℹ️ Цены и контакты", "en": "ℹ️ Prices & contacts"},
    "btn_back": {"ru": "⬅️ Назад", "en": "⬅️ Back"},
    "btn_menu": {"ru": "🏠 Меню", "en": "🏠 Menu"},
    "choose_service": {"ru": "Выберите услугу:", "en": "Choose a service:"},
    "choose_day": {"ru": "<b>{service}</b>\nВыберите день:", "en": "<b>{service}</b>\nChoose a day:"},
    "choose_time": {
        "ru": "<b>{service}</b>, {day}\nСвободное время:",
        "en": "<b>{service}</b>, {day}\nAvailable times:",
    },
    "no_slots": {
        "ru": "😔 На этот день всё занято. Выберите другой день.",
        "en": "😔 This day is fully booked. Please choose another day.",
    },
    "ask_name": {"ru": "Как вас зовут?", "en": "What is your name?"},
    "ask_phone": {
        "ru": "Оставьте номер телефона — нажмите кнопку ниже или напишите его.",
        "en": "Please share your phone number — tap the button below or type it.",
    },
    "btn_phone": {"ru": "📱 Отправить мой номер", "en": "📱 Share my number"},
    "bad_phone": {"ru": "Похоже, это не номер телефона. Попробуйте ещё раз.", "en": "That doesn't look like a phone number. Try again."},
    "confirm": {
        "ru": "Проверьте запись:\n\n💇 {service}\n📅 {when}\n💰 {price}\n👤 {name}, {phone}\n\nВсё верно?",
        "en": "Please check your booking:\n\n💇 {service}\n📅 {when}\n💰 {price}\n👤 {name}, {phone}\n\nIs everything correct?",
    },
    "btn_yes": {"ru": "✅ Подтвердить", "en": "✅ Confirm"},
    "btn_no": {"ru": "❌ Отменить", "en": "❌ Cancel"},
    "booked": {
        "ru": "🎉 Готово! Вы записаны: <b>{service}</b>, {when}.\nНапомним за сутки. Отменить можно в «Мои записи».",
        "en": "🎉 Done! You are booked: <b>{service}</b>, {when}.\nWe'll remind you a day before. You can cancel in “My bookings”.",
    },
    "slot_taken": {
        "ru": "😔 Это время только что заняли. Выберите другое.",
        "en": "😔 Sorry, this time was just taken. Please choose another one.",
    },
    "flow_cancelled": {"ru": "Запись отменена.", "en": "Booking cancelled."},
    "my_empty": {"ru": "У вас нет предстоящих записей.", "en": "You have no upcoming bookings."},
    "my_list": {"ru": "Ваши записи (нажмите, чтобы отменить):", "en": "Your bookings (tap to cancel):"},
    "cancelled": {"ru": "Запись на {when} отменена.", "en": "Your booking for {when} is cancelled."},
    "reminder": {
        "ru": "⏰ Напоминаем: завтра вы записаны в <b>{name}</b>\n💇 {service}\n📅 {when}\n📍 {address}\n\nЕсли планы изменились — отмените запись в «Мои записи».",
        "en": "⏰ Reminder: you have a booking at <b>{name}</b>\n💇 {service}\n📅 {when}\n📍 {address}\n\nIf your plans changed, please cancel in “My bookings”.",
    },
    "info": {
        "ru": "<b>{name}</b>\n📍 {address}\n📞 {phone}\n🕙 {hours}\n\n<b>Услуги и цены:</b>\n{prices}",
        "en": "<b>{name}</b>\n📍 {address}\n📞 {phone}\n🕙 {hours}\n\n<b>Services & prices:</b>\n{prices}",
    },
    "minutes": {"ru": "мин", "en": "min"},
    "btn_lang": {"ru": "🌐 English", "en": "🌐 Русский"},
    # messages for the business owner
    "adm_new": {
        "ru": "🆕 Новая запись #{id}\n💇 {service}\n📅 {when}\n👤 {name}, {phone}{username}",
        "en": "🆕 New booking #{id}\n💇 {service}\n📅 {when}\n👤 {name}, {phone}{username}",
    },
    "adm_cancel": {
        "ru": "🚫 Отмена записи #{id}\n💇 {service}\n📅 {when}\n👤 {name}, {phone}",
        "en": "🚫 Booking #{id} cancelled\n💇 {service}\n📅 {when}\n👤 {name}, {phone}",
    },
    "adm_today": {"ru": "📋 <b>Сегодня</b>", "en": "📋 <b>Today</b>"},
    "adm_week": {"ru": "📋 <b>Ближайшие 7 дней</b>", "en": "📋 <b>Next 7 days</b>"},
    "adm_empty": {"ru": "Записей нет.", "en": "No bookings."},
}
WEEKDAYS = {
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


def lang_of(user) -> str:
    """Language chosen with the 🌐 button, otherwise guessed from the Telegram app language."""
    row = db.execute("SELECT lang FROM user_lang WHERE user_id=?", (user.id,)).fetchone()
    if row:
        return row["lang"]
    code = (user.language_code or "en").lower()
    return "ru" if code[:2] in ("ru", "uk", "be", "kk") else "en"


def lang_by_id(user_id: int) -> str:
    row = db.execute("SELECT lang FROM user_lang WHERE user_id=?", (user_id,)).fetchone()
    return row["lang"] if row else "ru"


def price_of(service: dict, lang: str) -> str:
    p = service["price"]
    return p[lang] if isinstance(p, dict) else p


def t(key: str, lang: str, **kw) -> str:
    return T[key][lang].format(**kw)


def svc_name(key: str, lang: str) -> str:
    return SERVICES[key]["name"][lang]


def fmt_dt(dt: datetime, lang: str) -> str:
    return f"{WEEKDAYS[lang][dt.weekday()]} {dt:%d.%m} {dt:%H:%M}"


def biz(field: str, lang: str) -> str:
    v = CONFIG[field]
    return v[lang] if isinstance(v, dict) else v


# ---------------------------------------------------------------- database
db = sqlite3.connect(BASE / "bookings.db")
db.row_factory = sqlite3.Row
db.execute(
    """CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, lang TEXT, name TEXT, phone TEXT,
        service TEXT, start TEXT, end TEXT,
        status TEXT DEFAULT 'active', reminded INTEGER DEFAULT 0,
        created TEXT)"""
)
db.execute("CREATE TABLE IF NOT EXISTS user_lang (user_id INTEGER PRIMARY KEY, lang TEXT)")
db.commit()


def now() -> datetime:
    return datetime.now(TZ)


def busy_intervals(day: date) -> list[tuple[datetime, datetime]]:
    rows = db.execute(
        "SELECT start, end FROM bookings WHERE status='active' AND substr(start,1,10)=?",
        (day.isoformat(),),
    ).fetchall()
    return [(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])) for r in rows]


def free_slots(day: date, service: str) -> list[datetime]:
    duration = timedelta(minutes=SERVICES[service]["minutes"])
    busy = busy_intervals(day)
    slot = datetime(day.year, day.month, day.day, WORK_START, tzinfo=TZ)
    close = datetime(day.year, day.month, day.day, WORK_END, tzinfo=TZ)
    earliest = now() + timedelta(hours=1)
    result = []
    while slot + duration <= close:
        if slot >= earliest and all(slot + duration <= b0 or slot >= b1 for b0, b1 in busy):
            result.append(slot)
        slot += timedelta(minutes=SLOT_STEP)
    return result


def open_days() -> list[date]:
    today = now().date()
    days = [today + timedelta(days=i) for i in range(DAYS_AHEAD + 7)]
    return [d for d in days if d.weekday() not in DAYS_OFF][:DAYS_AHEAD]


# ---------------------------------------------------------------- keyboards
def kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=txt, callback_data=data) for txt, data in row] for row in rows]
    )


def main_menu(lang: str) -> InlineKeyboardMarkup:
    return kb(
        [
            [(t("btn_book", lang), "book")],
            [(t("btn_my", lang), "my")],
            [(t("btn_info", lang), "info")],
            [(t("btn_lang", lang), "lang")],
        ]
    )


# ---------------------------------------------------------------- handlers
router = Router()


class Booking(StatesGroup):
    name = State()
    phone = State()
    confirm = State()


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext):
    await state.clear()
    lang = lang_of(msg.from_user)
    await msg.answer(t("hello", lang, name=biz("name", lang)), reply_markup=main_menu(lang))


@router.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = lang_of(cb.from_user)
    await cb.message.edit_text(t("hello", lang, name=biz("name", lang)), reply_markup=main_menu(lang))


@router.callback_query(F.data == "lang")
async def switch_lang(cb: CallbackQuery, state: FSMContext):
    new = "en" if lang_of(cb.from_user) == "ru" else "ru"
    db.execute("INSERT OR REPLACE INTO user_lang (user_id, lang) VALUES (?, ?)", (cb.from_user.id, new))
    db.commit()
    await menu(cb, state)


@router.callback_query(F.data == "info")
async def info(cb: CallbackQuery):
    lang = lang_of(cb.from_user)
    prices = "\n".join(
        f"• {s['name'][lang]} — {price_of(s, lang)} ({s['minutes']} {t('minutes', lang)})" for s in SERVICES.values()
    )
    hours = f"{WORK_START:02d}:00–{WORK_END:02d}:00"
    await cb.message.edit_text(
        t("info", lang, name=biz("name", lang), address=biz("address", lang), phone=CONFIG["phone"], hours=hours, prices=prices),
        reply_markup=kb([[(t("btn_back", lang), "menu")]]),
    )


@router.callback_query(F.data == "book")
async def choose_service(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = lang_of(cb.from_user)
    rows = [[(f"{s['name'][lang]} · {price_of(s, lang)}", f"svc:{key}")] for key, s in SERVICES.items()]
    rows.append([(t("btn_back", lang), "menu")])
    await cb.message.edit_text(t("choose_service", lang), reply_markup=kb(rows))


@router.callback_query(F.data.startswith("svc:"))
async def choose_day(cb: CallbackQuery, state: FSMContext):
    lang = lang_of(cb.from_user)
    service = cb.data.split(":", 1)[1]
    if service not in SERVICES:
        return await cb.answer()
    await state.update_data(service=service)
    days = open_days()
    buttons = [(f"{WEEKDAYS[lang][d.weekday()]} {d:%d.%m}", f"day:{d.isoformat()}") for d in days]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([(t("btn_back", lang), "book")])
    await cb.message.edit_text(t("choose_day", lang, service=svc_name(service, lang)), reply_markup=kb(rows))


@router.callback_query(F.data.startswith("day:"))
async def choose_time(cb: CallbackQuery, state: FSMContext):
    lang = lang_of(cb.from_user)
    data = await state.get_data()
    service = data.get("service")
    if not service:
        return await choose_service(cb, state)
    day = date.fromisoformat(cb.data.split(":", 1)[1])
    slots = free_slots(day, service)
    if not slots:
        return await cb.answer(t("no_slots", lang), show_alert=True)
    buttons = [(f"{s:%H:%M}", f"time:{s.isoformat()}") for s in slots]
    rows = [buttons[i : i + 4] for i in range(0, len(buttons), 4)]
    rows.append([(t("btn_back", lang), f"svc:{service}")])
    day_txt = f"{WEEKDAYS[lang][day.weekday()]} {day:%d.%m}"
    await cb.message.edit_text(
        t("choose_time", lang, service=svc_name(service, lang), day=day_txt), reply_markup=kb(rows)
    )


@router.callback_query(F.data.startswith("time:"))
async def ask_name(cb: CallbackQuery, state: FSMContext):
    lang = lang_of(cb.from_user)
    await state.update_data(start=cb.data.split(":", 1)[1])
    await state.set_state(Booking.name)
    await cb.message.edit_text(t("ask_name", lang))


@router.message(Booking.name, F.text)
async def got_name(msg: Message, state: FSMContext):
    lang = lang_of(msg.from_user)
    await state.update_data(name=html.escape(msg.text.strip()[:60]))  # messages use HTML mode
    await state.set_state(Booking.phone)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("btn_phone", lang), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await msg.answer(t("ask_phone", lang), reply_markup=keyboard)


@router.message(Booking.phone)
async def got_phone(msg: Message, state: FSMContext):
    lang = lang_of(msg.from_user)
    phone = html.escape(msg.contact.phone_number if msg.contact else (msg.text or "").strip()[:30])
    digits = [c for c in phone if c.isdigit()]
    if not 6 <= len(digits) <= 15:
        return await msg.answer(t("bad_phone", lang))
    await state.update_data(phone=phone)
    await state.set_state(Booking.confirm)
    data = await state.get_data()
    start_dt = datetime.fromisoformat(data["start"])
    await msg.answer("👌", reply_markup=ReplyKeyboardRemove())
    await msg.answer(
        t(
            "confirm",
            lang,
            service=svc_name(data["service"], lang),
            when=fmt_dt(start_dt, lang),
            price=price_of(SERVICES[data["service"]], lang),
            name=data["name"],
            phone=phone,
        ),
        reply_markup=kb([[(t("btn_yes", lang), "confirm"), (t("btn_no", lang), "abort")]]),
    )


@router.callback_query(Booking.confirm, F.data == "confirm")
async def confirm(cb: CallbackQuery, state: FSMContext, bot: Bot):
    lang = lang_of(cb.from_user)
    data = await state.get_data()
    await state.clear()
    service = data["service"]
    start_dt = datetime.fromisoformat(data["start"])
    if start_dt not in free_slots(start_dt.date(), service):  # someone took it meanwhile
        await cb.message.edit_text(t("slot_taken", lang), reply_markup=kb([[(t("btn_book", lang), "book")]]))
        return
    end_dt = start_dt + timedelta(minutes=SERVICES[service]["minutes"])
    cur = db.execute(
        "INSERT INTO bookings (user_id, lang, name, phone, service, start, end, created) VALUES (?,?,?,?,?,?,?,?)",
        (cb.from_user.id, lang, data["name"], data["phone"], service, start_dt.isoformat(), end_dt.isoformat(), now().isoformat()),
    )
    db.commit()
    when = fmt_dt(start_dt, lang)
    await cb.message.edit_text(
        t("booked", lang, service=svc_name(service, lang), when=when), reply_markup=kb([[(t("btn_menu", lang), "menu")]])
    )
    username = f" @{cb.from_user.username}" if cb.from_user.username else ""
    await notify_admins(
        bot,
        lambda al: t(
            "adm_new", al, id=cur.lastrowid, service=svc_name(service, al), when=fmt_dt(start_dt, al),
            name=data["name"], phone=data["phone"], username=username,
        ),
    )


@router.callback_query(F.data == "abort")
async def abort(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = lang_of(cb.from_user)
    await cb.message.edit_text(t("flow_cancelled", lang), reply_markup=main_menu(lang))


@router.callback_query(F.data == "my")
async def my_bookings(cb: CallbackQuery):
    lang = lang_of(cb.from_user)
    rows = db.execute(
        "SELECT * FROM bookings WHERE user_id=? AND status='active' AND start>=? ORDER BY start",
        (cb.from_user.id, now().isoformat()),
    ).fetchall()
    if not rows:
        return await cb.message.edit_text(t("my_empty", lang), reply_markup=kb([[(t("btn_back", lang), "menu")]]))
    buttons = [
        [(f"❌ {svc_name(r['service'], lang)} · {fmt_dt(datetime.fromisoformat(r['start']), lang)}", f"cancel:{r['id']}")]
        for r in rows
    ]
    buttons.append([(t("btn_back", lang), "menu")])
    await cb.message.edit_text(t("my_list", lang), reply_markup=kb(buttons))


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_booking(cb: CallbackQuery, bot: Bot):
    lang = lang_of(cb.from_user)
    booking_id = int(cb.data.split(":", 1)[1])
    row = db.execute(
        "SELECT * FROM bookings WHERE id=? AND user_id=? AND status='active'", (booking_id, cb.from_user.id)
    ).fetchone()
    if not row:
        return await cb.answer()
    db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    db.commit()
    start_dt = datetime.fromisoformat(row["start"])
    await cb.message.edit_text(
        t("cancelled", lang, when=fmt_dt(start_dt, lang)), reply_markup=kb([[(t("btn_menu", lang), "menu")]])
    )
    await notify_admins(
        bot,
        lambda al: t(
            "adm_cancel", al, id=booking_id, service=svc_name(row["service"], al), when=fmt_dt(start_dt, al),
            name=row["name"], phone=row["phone"],
        ),
    )


# ---------------------------------------------------------------- admin
def schedule_text(days: int, lang: str = "ru") -> str:
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(
        "SELECT * FROM bookings WHERE status='active' AND start>=? AND start<? ORDER BY start",
        (start.isoformat(), (start + timedelta(days=days)).isoformat()),
    ).fetchall()
    if not rows:
        return t("adm_empty", lang)
    lines, last_day = [], None
    for r in rows:
        s = datetime.fromisoformat(r["start"])
        if s.date() != last_day:
            lines.append(f"\n<b>{WEEKDAYS[lang][s.weekday()]} {s:%d.%m}</b>")
            last_day = s.date()
        lines.append(f"{s:%H:%M} — {svc_name(r['service'], lang)} · {r['name']}, {r['phone']}")
    return "\n".join(lines).strip()


@router.message(Command("today"), F.from_user.id.in_(ADMIN_IDS))
async def admin_today(msg: Message):
    lang = lang_of(msg.from_user)
    await msg.answer(t("adm_today", lang) + "\n" + schedule_text(1, lang))


@router.message(Command("week"), F.from_user.id.in_(ADMIN_IDS))
async def admin_week(msg: Message):
    lang = lang_of(msg.from_user)
    await msg.answer(t("adm_week", lang) + "\n" + schedule_text(7, lang))


async def notify_admins(bot: Bot, make_text) -> None:
    """make_text(lang) builds the message in each admin's own language."""
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, make_text(lang_by_id(admin)))
        except Exception as e:  # admin may have blocked the bot
            logging.warning("cannot notify admin %s: %s", admin, e)


# ---------------------------------------------------------------- reminders
async def reminder_loop(bot: Bot) -> None:
    while True:
        try:
            limit = (now() + REMIND_BEFORE).isoformat()
            rows = db.execute(
                "SELECT * FROM bookings WHERE status='active' AND reminded=0 AND start<=? AND start>?",
                (limit, now().isoformat()),
            ).fetchall()
            for r in rows:
                lang = r["lang"]
                try:
                    await bot.send_message(
                        r["user_id"],
                        t(
                            "reminder",
                            lang,
                            name=biz("name", lang),
                            service=svc_name(r["service"], lang),
                            when=fmt_dt(datetime.fromisoformat(r["start"]), lang),
                            address=biz("address", lang),
                        ),
                        reply_markup=kb([[(t("btn_my", lang), "my")]]),
                    )
                except Exception as e:
                    logging.warning("reminder failed for booking %s: %s", r["id"], e)
                db.execute("UPDATE bookings SET reminded=1 WHERE id=?", (r["id"],))
                db.commit()
        except Exception:
            logging.exception("reminder loop error")
        await asyncio.sleep(60)


# ---------------------------------------------------------------- main
async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is missing: copy .env.example to .env and fill it in.")
    from aiogram.client.default import DefaultBotProperties

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

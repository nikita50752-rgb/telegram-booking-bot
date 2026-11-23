# 📅 Booking Bot — Telegram appointment booking for small businesses

A ready-to-use Telegram bot that lets clients book appointments 24/7, without calls or messages.
Made for beauty salons, barbershops, car washes, photo studios, tutors, and fitness or dance studios.

<p align="center"><img src="docs/demo.gif" width="320" alt="Booking bot demo: service → day → time → confirm → reminder"></p>

## What it does

**For clients**
- Choose a service, then a day, then a free time slot, all with buttons.
- Leave a name and phone number (one tap: “Share my number”).
- Get an automatic **reminder 24 hours before** the visit.
- See their bookings and cancel them in one tap.
- The interface is in Russian or English, picked automatically from the client's Telegram language.

**For the business owner**
- An instant notification for every new booking or cancellation.
- `/today` and `/week` show the schedule.
- No double bookings: free slots take the service's duration into account.
- Services, prices, working hours, days off and address are set in one simple file (`business.json`). No coding needed.

## Demo flow

```
/start → 📅 Book → Manicure · 2 000 ₽ → Tue 24.11 → 14:30 → name → 📱 phone → ✅ Confirm
Client:  🎉 Done! You are booked: Manicure, Tue 24.11 14:30
Owner:   🆕 New booking #12 — Manicure, Tue 24.11 14:30 — Anna, +7 900 …
Next day: ⏰ Reminder sent to the client automatically
```

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
# put your BotFather token and your Telegram ID into .env
python bot.py
```

Edit `business.json` to set your services, prices, hours and address.

## Tech

Python 3.10+, [aiogram 3](https://docs.aiogram.dev), SQLite, and a finite-state machine for the booking dialog. The whole bot is one file, about 400 lines, easy to extend.

## Custom versions

Possible custom versions include:
- several staff members with their own schedules;
- prepayment through Telegram Payments;
- Google Calendar or Google Sheets sync;
- loyalty cards;
- an admin panel;
- broadcasts to clients.

---

### 🇷🇺 Кратко по-русски

Это Telegram-бот для записи клиентов. Клиент сам выбирает услугу, день и время, а за сутки до визита бот присылает ему напоминание. Владелец получает уведомление о каждой записи и видит расписание командами `/today` и `/week`. Услуги, цены и часы работы настраиваются в файле `business.json`.

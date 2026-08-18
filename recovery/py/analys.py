# PUBLIC GITHUB COPY: set TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN in environment; active token intentionally not committed.
import os
import random
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

# ================= TELEGRAM =================
# Токен и ID группы можно заменить через переменные окружения:
# TELEGRAM_TOKEN и TELEGRAM_CHAT_ID.
ADMIN_ID = int(os.getenv("ADMIN_ID", "8016237913"))
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "-1003916331483"))

# ================= LUCKYJET API =================
API = "https://crash-gateway-grm-cr.100hp.app/state"
HEADERS = {
    "customer-id": os.getenv("LUCKYJET_CUSTOMER_ID", ""),
    "session-id": os.getenv("LUCKYJET_SESSION_ID", ""),
    "accept": "application/json",
}

TZ = ZoneInfo("Europe/Kyiv")
POLL_SECONDS = 5
PAUSE_AFTER_LOSSES = 2
PAUSE_SECONDS = 5 * 60

SETTINGS = {
    "mode": "PRO",  # SAFE / PRO / SNIPER
    "goal": "balance",  # many / balance / rare
    "range": {"min": 2.0, "max": 5.0},
}

coefs = []
last5 = []
grand_events = []
results = []
stats = {"ok": 0, "ko": 0}
last_no_signal = "Пока идет сбор данных."
paused_loss_streak = 0
update_offset = None
pending_mode = None
auto_signal = False


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def now():
    return datetime.now(TZ)


def fmt_time(dt):
    return dt.astimezone(TZ).strftime("%H:%M")


def send_telegram(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=payload, timeout=15)
        if not response.ok:
            print(f"[telegram] Ошибка отправки: {response.status_code} {response.text}")
            return False
        return True
    except requests.RequestException as exc:
        print(f"[telegram] Ошибка отправки: {exc}")
        return False


def signal_keyboard(new=False):
    return {
        "inline_keyboard": [
            [{"text": "AUTO сигнал", "callback_data": "auto_signal"}],
            [{"text": "Отключить AUTO", "callback_data": "auto_off"}],
            [{"text": "GRAND 10X", "callback_data": "grand_signal"}],
            [{"text": "Простой сигнал", "callback_data": "simple_signal"}],
        ]
    }


def send_signal_button(new=False):
    if new:
        text = "Готов искать следующий прогноз. Нажмите кнопку ниже."
    else:
        text = "Нажмите кнопку ниже, когда хотите получить сигнал."
    send_telegram(text, reply_markup=signal_keyboard(new))


def answer_callback(callback_id, text="Принято"):
    url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
    try:
        requests.post(
            url,
            json={"callback_query_id": callback_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"[telegram] Ошибка answerCallbackQuery: {exc}")


def button_pressed():
    global update_offset

    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 1}
    if update_offset is not None:
        params["offset"] = update_offset

    try:
        response = requests.get(url, params=params, timeout=5)
        if not response.ok:
            print(f"[telegram] Ошибка getUpdates: {response.status_code} {response.text}")
            return False

        pressed = False
        for item in response.json().get("result", []):
            update_offset = item["update_id"] + 1
            callback = item.get("callback_query")
            if not callback:
                continue
            data = callback.get("data")
            if data not in ("simple_signal", "get_signal", "grand_signal", "auto_signal", "auto_off"):
                continue

            message = callback.get("message", {})
            chat = message.get("chat", {})
            if int(chat.get("id", 0)) != CHAT_ID:
                answer_callback(callback["id"], "Это не та группа")
                continue

            if data == "grand_signal":
                answer_callback(callback["id"], "Анализирую GRAND")
                pressed = "grand"
            elif data == "auto_signal":
                answer_callback(callback["id"], "AUTO включен")
                pressed = "auto"
            elif data == "auto_off":
                answer_callback(callback["id"], "AUTO выключен")
                pressed = "auto_off"
            else:
                answer_callback(callback["id"], "Ищу сигнал")
                pressed = "simple"

        return pressed
    except requests.RequestException as exc:
        print(f"[telegram] Ошибка getUpdates: {exc}")
        return False


def skip_old_updates():
    global update_offset

    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        if not response.ok:
            print(f"[telegram] Ошибка getUpdates: {response.status_code} {response.text}")
            return

        updates = response.json().get("result", [])
        if updates:
            update_offset = updates[-1]["update_id"] + 1
    except requests.RequestException as exc:
        print(f"[telegram] Ошибка getUpdates: {exc}")


def show_known_chats():
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        response = requests.get(url, timeout=15)
        if not response.ok:
            print(f"[telegram] Ошибка getUpdates: {response.status_code} {response.text}")
            return

        updates = response.json().get("result", [])
        seen = set()
        for item in updates:
            for key in ("message", "channel_post", "edited_message", "my_chat_member"):
                data = item.get(key)
                if not isinstance(data, dict):
                    continue
                chat = data.get("chat")
                if not chat or chat.get("id") in seen:
                    continue
                seen.add(chat.get("id"))
                name = chat.get("title") or chat.get("username") or chat.get("first_name") or "-"
                print(f"{chat.get('id')} | {chat.get('type')} | {name}")

        if not seen:
            print("Чатов пока нет. Добавьте бота в группу и напишите там любое сообщение.")
    except requests.RequestException as exc:
        print(f"[telegram] Ошибка getUpdates: {exc}")


def get_coef():
    try:
        response = requests.get(API, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
        value = data.get("stopCoefficients", [None])[0]
        if value is None:
            return None

        coef = float(value)
        if coef == 1:
            coef = 1.01
        return round(coef, 2)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        print(f"[api] Ошибка получения коэффициента: {exc}")
        return None


def add_coef(coef):
    if coef is None:
        return False
    if coefs and coefs[-1] == coef:
        return False

    coefs.append(coef)
    last5.append(coef)
    del coefs[:-12]
    del last5[:-5]
    remember_grand_event(coef)
    print(f"[coef] {coef:.2f}X")
    return True


def remember_grand_event(coef):
    if coef < 10:
        return

    event_time = now()
    grand_events.append(
        {
            "coef": coef,
            "time": event_time,
            "minute": event_time.minute,
            "clock": event_time.strftime("%H:%M"),
        }
    )
    del grand_events[:-300]
    print(f"[grand] {coef:.2f}X at {event_time.strftime('%H:%M:%S')}")


def minute_distance(a, b):
    diff = abs(a - b)
    return min(diff, 60 - diff)


def next_time_for_minute(minute):
    candidate = now().replace(minute=minute, second=0, microsecond=0)
    if candidate <= now():
        candidate += timedelta(hours=1)
    return candidate


def grand_analysis():
    if len(grand_events) < 2:
        return None

    current_minute = now().minute
    candidates = []
    for shift in range(1, 16):
        minute = (current_minute + shift) % 60
        exact = sum(1 for event in grand_events if event["minute"] == minute)
        near = sum(1 for event in grand_events if minute_distance(event["minute"], minute) == 1)
        score = exact * 3 + near
        if score:
            candidates.append((score, exact, near, minute))

    if not candidates:
        return None

    score, exact, near, minute = max(candidates)
    target_time = next_time_for_minute(minute)
    confidence = round(clamp(35 + score * 8 + min(len(grand_events), 10) * 2, 35, 88))
    last_events = grand_events[-5:]
    avg_high = sum(event["coef"] for event in last_events) / len(last_events)
    target = round(clamp(avg_high * 0.42 + confidence * 0.08, 10, 35), 2)

    return {
        "minute": minute,
        "time": target_time,
        "exact": exact,
        "near": near,
        "score": score,
        "confidence": confidence,
        "target": target,
        "last_events": last_events,
    }


def send_grand_signal():
    analysis = grand_analysis()
    if not analysis:
        send_telegram(
            "GRAND 10X пока не готов.\n\n"
            f"Нужно минимум 2 события 10X+, сейчас найдено: {len(grand_events)}.\n"
            "Я продолжаю запоминать минуты, где выпадает 10X и выше.",
            reply_markup=signal_keyboard(new=False),
        )
        return

    last_text = "\n".join(
        f"{event['clock']} - {event['coef']:.2f}X" for event in analysis["last_events"]
    )
    send_telegram(
        "👑 GRAND 10X анализ\n\n"
        f"🎯 Рабочая минута: {analysis['time'].strftime('%H:%M')} по Киеву\n"
        "📌 Логика: смотрю минуты, где раньше выпадало 10X+, "
        "и ближайшие минуты рядом с ними.\n"
        f"📊 Совпадений в эту минуту: {analysis['exact']}\n"
        f"📍 Рядом +/-1 минута: {analysis['near']}\n"
        f"✅ Уверенность: {analysis['confidence']}%\n\n"
        f"Последние 10X+:\n{last_text}\n\n"
        "Это отдельный GRAND-прогноз, не гарантия результата.",
        reply_markup=signal_keyboard(new=True),
    )


def send_grand_plan(analysis):
    last_text = "\n".join(
        f"{event['clock']} - {event['coef']:.2f}X" for event in analysis["last_events"]
    )
    send_telegram(
        "👑 GRAND 10X сигнал\n\n"
        f"⏰ Ставить: {analysis['time'].strftime('%H:%M')} по Киеву\n"
        f"🎯 Цель: {analysis['target']:.2f}X\n"
        f"📊 Совпадений в эту минуту: {analysis['exact']}\n"
        f"📍 Рядом +/-1 минута: {analysis['near']}\n"
        f"✅ Уверенность: {analysis['confidence']}%\n\n"
        f"Последние 10X+:\n{last_text}\n\n"
        "Проверю результат до 3 раундов после входа.",
        reply_markup=signal_keyboard(new=True),
    )


def finish_grand_signal(ok, target, real_coef, round_number):
    if ok:
        text = (
            "👑✅ GRAND зашёл\n\n"
            f"🎯 Цель: {target:.2f}X\n"
            f"📌 Выпало: {real_coef:.2f}X\n"
            f"🔁 Раунд: {round_number}/3"
        )
    else:
        text = (
            "👑❌ GRAND не зашёл\n\n"
            f"🎯 Цель: {target:.2f}X\n"
            f"📌 Последний: {real_coef:.2f}X\n"
            "🔁 Проверено: 3/3 раунда"
        )
    send_telegram(text, reply_markup=signal_keyboard(new=True))


def run_grand_cycle():
    analysis = grand_analysis()
    if not analysis:
        send_grand_signal()
        return False

    target = analysis["target"]
    entry_time = analysis["time"]
    send_grand_plan(analysis)
    print(f"[grand signal] target={target:.2f}X entry={fmt_time(entry_time)}")

    wait_until_entry(entry_time)
    send_telegram("👑⏱ GRAND вход сейчас. Проверяю следующие раунды.")

    last_real = coefs[-1] if coefs else None
    for round_number in range(1, 4):
        real_coef = wait_next_coef(last_real)
        last_real = real_coef
        print(f"[grand round {round_number}] real={real_coef:.2f}X target={target:.2f}X")
        if real_coef >= target:
            finish_grand_signal(True, target, real_coef, round_number)
            return True

    finish_grand_signal(False, target, last_real, 3)
    return True


def handle_simple_request(from_wait=False):
    global pending_mode

    if can_signal():
        pending_mode = None
        run_signal_cycle()
        return True

    pending_mode = "simple"
    if not from_wait:
        send_telegram(
            "Простой сигнал поставлен в ожидание.\n\n"
            f"Сейчас причина: {last_no_signal}\n"
            "Как только рынок восстановится, я сам пришлю сигнал.",
            reply_markup=signal_keyboard(new=False),
        )
    return False


def handle_grand_request(from_wait=False):
    global pending_mode

    if grand_analysis():
        pending_mode = None
        run_grand_cycle()
        return True

    pending_mode = "grand"
    if not from_wait:
        send_telegram(
            "GRAND поставлен в ожидание.\n\n"
            f"Нужно минимум 2 события 10X+, сейчас найдено: {len(grand_events)}.\n"
            "Когда накопится логика по минутам, я сам пришлю GRAND-сигнал.",
            reply_markup=signal_keyboard(new=False),
        )
    return False


def handle_pending_request():
    if pending_mode == "simple":
        handle_simple_request(from_wait=True)
    elif pending_mode == "grand":
        handle_grand_request(from_wait=True)


def poll_once():
    coef = get_coef()
    if add_coef(coef):
        return coef
    return None


def filtered_coefs():
    if SETTINGS["mode"] == "SAFE":
        return [x for x in coefs if 1.2 <= x <= 5]
    if SETTINGS["mode"] == "SNIPER":
        return [x for x in coefs if x >= 3]
    return list(coefs)


def consecutive_losses():
    losses = 0
    for result in reversed(results):
        if result != "ko":
            break
        losses += 1
    return losses


def analyze():
    if len(coefs) < 3:
        return {
            "score": 50,
            "level": "safe",
            "risk": "низкий",
            "why": "данных пока мало",
            "conf": 50,
        }

    recent = coefs[-8:]
    low_count = sum(1 for x in recent if x < 1.5)
    low_ratio = low_count / len(recent)
    very_low = sum(1 for x in recent if x < 1.2)
    losses = consecutive_losses()

    prev_part = recent[:4]
    now_part = recent[-4:]
    prev_avg = sum(prev_part) / max(1, len(prev_part))
    now_avg = sum(now_part) / max(1, len(now_part))
    trend_up = now_avg > prev_avg

    raw_score = 100 - low_ratio * 42 - very_low * 8 - losses * 22
    raw_score += 6 if trend_up else -6
    score = round(clamp(raw_score, 0, 100))

    if score >= 70 and losses == 0:
        risk = "низкий"
        level = "safe"
    elif score >= 45 and losses < 2:
        risk = "средний"
        level = "warn"
    else:
        risk = "высокий"
        level = "danger"

    if losses >= 2:
        why = f"{losses} проигрыша подряд"
    elif low_count >= 4:
        why = "много низких коэффициентов"
    elif trend_up:
        why = "тренд растет"
    else:
        why = "тренд слабый или рынок шумный"

    conf = score
    if risk == "высокий":
        conf -= 10
    if SETTINGS["goal"] == "rare":
        conf += 6
    conf = round(clamp(conf, 35, 92))

    return {
        "score": score,
        "level": level,
        "risk": risk,
        "why": why,
        "conf": conf,
        "low_count": low_count,
        "trend_up": trend_up,
        "losses": losses,
    }


def smart_target(min_coef, max_coef):
    src = filtered_coefs()[-8:]
    if len(src) < 5:
        src = list(last5)
    if not src:
        return round(min_coef, 2)

    avg = sum(src) / len(src)
    low_ratio = sum(1 for x in src if x < 1.5) / len(src)
    analysis = analyze()
    target = avg * 0.72 + analysis["score"] / 100 * 0.55 - low_ratio * 0.35

    if SETTINGS["mode"] == "SAFE":
        target = min(target, 2.2)
    if SETTINGS["mode"] == "SNIPER":
        target = max(target, min(max_coef, 3.0))
    if SETTINGS["goal"] == "many":
        target -= 0.25
    if SETTINGS["goal"] == "rare":
        target += 0.35

    return round(clamp(target, min_coef, max_coef), 2)


def explain_signal():
    analysis = analyze()
    good = sum(1 for x in last5 if x > 1.5)
    return (
        f"Сигнал выбран: {good}/5 последних коэффициентов выше 1.50, "
        f"рынок {analysis['score']}/100, риск {analysis['risk']}, "
        f"причина: {analysis['why']}."
    )


def can_signal():
    global last_no_signal

    analysis = analyze()
    if analysis["level"] == "danger":
        last_no_signal = f"Нет сигнала: слабый рынок, {analysis['why']}."
        return False

    if len(last5) < 5:
        last_no_signal = f"Нет сигнала: нужно 5 последних коэффициентов, сейчас {len(last5)}."
        return False

    good = sum(1 for x in last5 if x > 1.5)
    if good < 3:
        last_no_signal = f"Нет сигнала: коэффициентов выше 1.50 только {good}/5."
        return False

    if SETTINGS["goal"] == "rare" and analysis["conf"] < 70:
        last_no_signal = f"Нет сигнала: уверенность {analysis['conf']}%, нужно от 70%."
        return False

    return True


def choose_entry_time():
    entry = now() + timedelta(minutes=random.randint(1, 4))
    entry = entry.replace(second=0, microsecond=0)
    if entry <= now() + timedelta(seconds=10):
        entry += timedelta(minutes=1)
    return entry


def wait_until_entry(entry_time):
    while now() < entry_time:
        poll_once()
        left = max(1, int((entry_time - now()).total_seconds()))
        time.sleep(min(POLL_SECONDS, left))


def wait_next_coef(previous_coef=None):
    while True:
        coef = poll_once()
        if coef is not None and coef != previous_coef:
            return coef
        time.sleep(POLL_SECONDS)


def send_signal(target, entry_time):
    analysis = analyze()
    message = (
        "🚀 LuckyJet сигнал\n\n"
        f"⏰ Вход: {fmt_time(entry_time)} по Киеву\n"
        f"🎯 Цель: {target:.2f}X\n"
        f"📊 Рынок: {analysis['score']}/100\n"
        f"⚠️ Риск: {analysis['risk']}\n"
        f"✅ Уверенность: {analysis['conf']}%\n\n"
        f"{explain_signal()}\n"
        "План: проверка до 3 раундов."
    )
    send_telegram(message)


def finish_signal(ok, target, real_coef, round_number):
    global paused_loss_streak

    result = "ok" if ok else "ko"
    results.append(result)
    del results[:-10]
    stats[result] += 1
    if ok:
        paused_loss_streak = 0

    if ok:
        text = (
            "✅ Сигнал успешно зашел\n\n"
            f"🎯 Цель: {target:.2f}X\n"
            f"📌 Реальный коэффициент: {real_coef:.2f}X\n"
            f"🔁 Раунд: {round_number}/3\n"
            f"📈 Статистика: {stats['ok']} успешных / {stats['ko']} неудачных"
        )
    else:
        text = (
            "❌ Сигнал не зашел\n\n"
            f"🎯 Цель: {target:.2f}X\n"
            f"📌 Последний коэффициент: {real_coef:.2f}X\n"
            "🔁 Проверено: 3/3 раунда\n"
            f"📈 Статистика: {stats['ok']} успешных / {stats['ko']} неудачных"
        )
    send_telegram(text)
    send_signal_button(new=True)


def run_signal_cycle():
    min_coef = max(1.0, float(SETTINGS["range"]["min"]))
    max_coef = max(min_coef + 0.01, float(SETTINGS["range"]["max"]))
    target = smart_target(min_coef, max_coef)
    entry_time = choose_entry_time()

    send_signal(target, entry_time)
    print(f"[signal] target={target:.2f}X entry={fmt_time(entry_time)}")

    wait_until_entry(entry_time)
    send_telegram("⏱ Время входа. Ставить сейчас.")

    skipped = wait_next_coef(coefs[-1] if coefs else None)
    print(f"[signal] skipped current round: {skipped:.2f}X")

    last_real = skipped
    for round_number in range(1, 4):
        real_coef = wait_next_coef(last_real)
        last_real = real_coef
        print(f"[round {round_number}] real={real_coef:.2f}X target={target:.2f}X")

        if real_coef >= target:
            finish_signal(True, target, real_coef, round_number)
            return

    finish_signal(False, target, last_real, 3)


def pause_if_needed():
    global paused_loss_streak

    losses = consecutive_losses()
    if losses < PAUSE_AFTER_LOSSES:
        paused_loss_streak = 0
        return

    if losses <= paused_loss_streak:
        return

    paused_loss_streak = losses
    minutes = PAUSE_SECONDS // 60
    send_telegram(
        "⏸ Пауза активна\n\n"
        f"Причина: {losses} проигрыша подряд.\n"
        f"Продолжу мониторинг через {minutes} минут."
    )
    print(f"[pause] {minutes} minutes")
    time.sleep(PAUSE_SECONDS)
    while results and results[-1] == "ko":
        results.pop()
    paused_loss_streak = 0
    send_telegram("▶️ Пауза закончилась. Снова ищу новый сигнал.")
    send_signal_button(new=True)


def warmup():
    print("[start] Сбор первых коэффициентов...")
    while len(last5) < 5:
        poll_once()
        time.sleep(POLL_SECONDS)


def main():
    global auto_signal, pending_mode

    if "--test" in sys.argv:
        ok = send_telegram(
            "✅ Тест: analys.py подключился к группе.\n"
            "Бот работает и ждёт прогноз."
        )
        print("OK" if ok else "FAILED")
        return

    if "--chats" in sys.argv:
        show_known_chats()
        return

    skip_old_updates()
    send_telegram(
        "✅ Бот начал работать\n\n"
        "📡 Собираю коэффициенты LuckyJet.\n"
        "⏳ Когда нужен прогноз, нажмите кнопку ниже."
    )
    warmup()
    send_signal_button(new=False)

    while True:
        try:
            pause_if_needed()

            poll_once()

            action = button_pressed()
            if action == "auto":
                auto_signal = True
                pending_mode = None
                send_telegram(
                    "AUTO сигнал включен.\n\n"
                    "Если рынок сейчас слабый, я подожду восстановления и сам пришлю сигнал.",
                    reply_markup=signal_keyboard(new=False),
                )
            elif action == "auto_off":
                auto_signal = False
                pending_mode = None
                send_telegram(
                    "AUTO сигнал выключен.\n\n"
                    "Новые сигналы будут только после нажатия кнопки.",
                    reply_markup=signal_keyboard(new=False),
                )
            elif action == "grand":
                auto_signal = False
                handle_grand_request()
            elif action == "simple":
                auto_signal = False
                handle_simple_request()
            else:
                print(f"[wait] {last_no_signal}")

            if pending_mode:
                handle_pending_request()
            elif auto_signal and can_signal():
                run_signal_cycle()

            time.sleep(1)
        except KeyboardInterrupt:
            send_telegram("🛑 analys.py остановлен вручную.")
            raise
        except Exception as exc:
            print(f"[error] {exc}")
            send_telegram(f"⚠️ Ошибка в analys.py: {exc}")
            time.sleep(15)


if __name__ == "__main__":
    main()

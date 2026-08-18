# PUBLIC GITHUB COPY: set TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN in environment; active token intentionally not committed.
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import math
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# ================= TELEGRAM =================
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8016237913"))
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "-1003916331483"))

# ================= ALLPREDICTOR / SITE EXACT =================
BASE = "https://allpredictor.com/api/v1"
API_KEY = os.getenv(
    "ALLPREDICTOR_API_KEY",
    "",
)
API_HEADERS = {"X-API-Key": API_KEY, "accept": "application/json"}

# То же прямое получение истории, что стоит в ru-ukraine версии страницы.
DIRECT_HISTORY_URL = "https://crash-gateway-grm-cr.100hp.app/history"
DIRECT_HISTORY_HEADERS = {
    "customer-id": os.getenv("LUCKYJET_CUSTOMER_ID", ""),
    "session-id": os.getenv("LUCKYJET_SESSION_ID", ""),
    "accept": "application/json",
}

KYIV = ZoneInfo("Europe/Kyiv")
API_TIMEOUT = 15
API_RETRY_DELAY = 5 * 60
AUTO_RETRY_SECONDS = 15
POST_RESULT_DELAY = 3
COEFFICIENT_POLL_SECONDS = 5
MARKET_POLL_SECONDS = 30

# Точный диапазон страницы ru-ukraine по умолчанию.
MIN_ODDS = float(os.getenv("MIN_ODDS", "2.00"))
MAX_ODDS = float(os.getenv("MAX_ODDS", "8.00"))

# ================= STATE =================
auto_mode = True
last_market_poll = 0.0
market_level = None
api_unavailable_until = 0.0
active = None
last_generated_coef = None
last_round_signature = None
last_status_sent = 0.0
LANG = os.getenv("BOT_LANGUAGE", "ru")
STATS_FILE = Path(os.getenv("STATS_FILE", "luckyjet_stats.json"))
wins_total = 0
losses_total = 0



TEXTS = {
    "ru": {
        "choose_language": "🌐 Выберите язык / Choose language / Elige idioma:",
        "language_set": "✅ Язык установлен: Русский",
        "signal_title": "🚀 СИГНАЛ LUCKYJET · RU-UKRAINE EXACT",
        "coef": "🎯 Коэффициент",
        "confidence": "📊 Надёжность",
        "status": "🛡 Статус",
        "market": "🧭 Рынок",
        "entry": "⏰ Время входа (Украина)",
        "source": "📡 Источник прогноза",
        "verify_info": "После указанного времени жду завершения текущего раунда,\nзатем проверяю следующие 3 раунда.",
        "bet_now": "🎯 СТАВЬ СЕЙЧАС",
        "target": "Цель",
        "checking": "Начинаю проверку следующих 3 раундов.",
        "win": "✅ ЗАШЛО",
        "lost": "❌ НЕ ЗАШЛО ПОСЛЕ 3 РАУНДОВ",
        "dropped": "🚀 Выпало",
        "round": "🔢 Раунд",
        "verification": "📋 Проверка",
        "rounds": "📉 Раунды",
        "stats": "📊 СТАТИСТИКА ЗА ВСЁ ВРЕМЯ",
        "wins": "✅ Удачных",
        "losses": "❌ Неудачных",
        "total": "🔢 Всего",
        "winrate": "🎯 Winrate",
        "stats_button": "📊 Статистика",
        "lang_button": "🌐 Язык",
        "safe": "БЕЗОПАСНО",
        "warn": "ОСТОРОЖНО",
        "danger": "ОПАСНО",
        "ready": "ГОТОВ",
    },
    "en": {
        "choose_language": "🌐 Choose language:",
        "language_set": "✅ Language set: English",
        "signal_title": "🚀 LUCKYJET SIGNAL · RU-UKRAINE EXACT",
        "coef": "🎯 Coefficient",
        "confidence": "📊 Reliability",
        "status": "🛡 Status",
        "market": "🧭 Market",
        "entry": "⏰ Entry time (Ukraine)",
        "source": "📡 Prediction source",
        "verify_info": "After the specified time I wait for the current round to finish,\nthen I check the next 3 rounds.",
        "bet_now": "🎯 BET NOW",
        "target": "Target",
        "checking": "Starting verification of the next 3 rounds.",
        "win": "✅ WIN",
        "lost": "❌ NOT HIT AFTER 3 ROUNDS",
        "dropped": "🚀 Result",
        "round": "🔢 Round",
        "verification": "📋 Verification",
        "rounds": "📉 Rounds",
        "stats": "📊 ALL-TIME STATISTICS",
        "wins": "✅ Wins",
        "losses": "❌ Losses",
        "total": "🔢 Total",
        "winrate": "🎯 Winrate",
        "stats_button": "📊 Statistics",
        "lang_button": "🌐 Language",
        "safe": "SAFE",
        "warn": "CAUTION",
        "danger": "DANGER",
        "ready": "READY",
    },
    "es": {
        "choose_language": "🌐 Elige idioma:",
        "language_set": "✅ Idioma establecido: Español",
        "signal_title": "🚀 SEÑAL LUCKYJET · RU-UKRAINE EXACT",
        "coef": "🎯 Coeficiente",
        "confidence": "📊 Fiabilidad",
        "status": "🛡 Estado",
        "market": "🧭 Mercado",
        "entry": "⏰ Hora de entrada (Ucrania)",
        "source": "📡 Fuente de predicción",
        "verify_info": "Después de la hora indicada espero a que termine la ronda actual\ny luego verifico las siguientes 3 rondas.",
        "bet_now": "🎯 APUESTA AHORA",
        "target": "Objetivo",
        "checking": "Comienzo a verificar las siguientes 3 rondas.",
        "win": "✅ GANÓ",
        "lost": "❌ NO ENTRÓ DESPUÉS DE 3 RONDAS",
        "dropped": "🚀 Salió",
        "round": "🔢 Ronda",
        "verification": "📋 Verificación",
        "rounds": "📉 Rondas",
        "stats": "📊 ESTADÍSTICAS HISTÓRICAS",
        "wins": "✅ Aciertos",
        "losses": "❌ Fallos",
        "total": "🔢 Total",
        "winrate": "🎯 Winrate",
        "stats_button": "📊 Estadísticas",
        "lang_button": "🌐 Idioma",
        "safe": "SEGURO",
        "warn": "PRECAUCIÓN",
        "danger": "PELIGRO",
        "ready": "LISTO",
    },
}


def tr(key):
    return TEXTS.get(LANG, TEXTS["ru"]).get(key, key)


def load_stats():
    global wins_total, losses_total
    try:
        if STATS_FILE.exists():
            data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            wins_total = int(data.get("wins", 0))
            losses_total = int(data.get("losses", 0))
    except Exception:
        wins_total = 0
        losses_total = 0


def save_stats():
    try:
        STATS_FILE.write_text(
            json.dumps({"wins": wins_total, "losses": losses_total}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        print("[stats]", exc)


def stats_text():
    total = wins_total + losses_total
    winrate = (wins_total / total * 100) if total else 0.0
    return (
        f"{tr('stats')}\n\n"
        f"{tr('wins')}: {wins_total}\n"
        f"{tr('losses')}: {losses_total}\n"
        f"{tr('total')}: {total}\n"
        f"{tr('winrate')}: {winrate:.1f}%"
    )


def main_keyboard():
    return {
        "keyboard": [
            [tr("stats_button"), tr("lang_button")]
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def language_keyboard():
    return {
        "keyboard": [
            ["🇷🇺 Русский", "🇬🇧 English", "🇪🇸 Español"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def send_with_keyboard(text, keyboard=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.ok
    except requests.RequestException:
        return False


def handle_telegram_commands():
    global LANG
    # lightweight polling for language/stat buttons
    if not hasattr(handle_telegram_commands, "offset"):
        handle_telegram_commands.offset = 0
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"offset": handle_telegram_commands.offset, "timeout": 0},
            timeout=5,
        )
        if not r.ok:
            return
        data = r.json()
        for upd in data.get("result", []):
            handle_telegram_commands.offset = max(handle_telegram_commands.offset, upd.get("update_id", 0) + 1)
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                continue
            body = (msg.get("text") or "").strip()

            if body == "🇷🇺 Русский":
                LANG = "ru"
                send_with_keyboard(tr("language_set"), main_keyboard())
            elif body == "🇬🇧 English":
                LANG = "en"
                send_with_keyboard(tr("language_set"), main_keyboard())
            elif body == "🇪🇸 Español":
                LANG = "es"
                send_with_keyboard(tr("language_set"), main_keyboard())
            elif body in {"📊 Статистика", "📊 Statistics", "📊 Estadísticas", "/stats"}:
                send_with_keyboard(stats_text(), main_keyboard())
            elif body in {"🌐 Язык", "🌐 Language", "🌐 Idioma", "/language"}:
                send_with_keyboard(tr("choose_language"), language_keyboard())
    except Exception:
        return


def now_kyiv():
    return datetime.now(KYIV)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if not r.ok:
            print("[telegram]", r.status_code, r.text[:500])
            return False
        return True
    except requests.RequestException as exc:
        print("[telegram]", exc)
        return False


def api_get(path):
    global api_unavailable_until
    if time.time() < api_unavailable_until:
        raise RuntimeError("AllPredictor API временно на паузе после ошибки")

    url = BASE + path
    try:
        r = requests.get(url, headers=API_HEADERS, timeout=API_TIMEOUT)
    except requests.RequestException as exc:
        api_unavailable_until = time.time() + API_RETRY_DELAY
        raise RuntimeError(f"Ошибка сети AllPredictor: {exc}") from exc

    if r.status_code in (401, 403) or r.status_code >= 500:
        api_unavailable_until = time.time() + API_RETRY_DELAY

    if not r.ok:
        raise RuntimeError(f"AllPredictor HTTP {r.status_code}: {r.text[:300]}")

    try:
        return r.json()
    except ValueError as exc:
        api_unavailable_until = time.time() + API_RETRY_DELAY
        raise RuntimeError("AllPredictor вернул не JSON") from exc


def coefficient_value(item):
    if not isinstance(item, dict):
        return None
    value = item.get("topCoefficient")
    if value is None:
        value = item.get("coef")
    if value is None:
        value = item.get("crash")
    if value is None:
        value = item.get("value")
    if value is None and isinstance(item.get("finalValues"), list) and item["finalValues"]:
        value = item["finalValues"][0]
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 1 else None


def normalize_rows(items):
    if not isinstance(items, list):
        return []
    rows = []
    for index, item in enumerate(items):
        coef = coefficient_value(item)
        if coef is None:
            continue
        rid = str(
            item.get("id")
            or item.get("round_id")
            or item.get("hash")
            or f"{coef:.2f}:{index}"
        )
        rows.append({"coef": coef, "id": rid})
    return rows


def fetch_direct_history():
    r = requests.get(
        DIRECT_HISTORY_URL,
        headers=DIRECT_HISTORY_HEADERS,
        timeout=API_TIMEOUT,
    )
    if not r.ok:
        raise RuntimeError(f"Direct history HTTP {r.status_code}: {r.text[:300]}")
    rows = normalize_rows(r.json())
    if not rows:
        raise RuntimeError("Источник не вернул коэффициенты")
    return rows


def fetch_recent_rows(limit):
    try:
        return fetch_direct_history()[:limit]
    except Exception as direct_error:
        try:
            data = api_get(f"/luckyjet/coefficients?limit={limit}")
            rows = normalize_rows(data.get("data") if isinstance(data, dict) else None)
            if rows:
                return rows[:limit]
        except Exception:
            pass
        raise direct_error


def analyze_direct_market(rows):
    values = [row["coef"] for row in rows[:8]]
    if not values:
        return {"level": "warn", "score": 50, "average": 0}

    average = sum(values) / len(values)
    above_two = sum(1 for v in values if v >= 2)

    low_streak = 0
    for value in values:
        if value <= 1.3:
            low_streak += 1
        else:
            break

    level = "warn"
    if low_streak >= 4 or average < 1.35:
        level = "danger"
    elif above_two >= 4 and average >= 2:
        level = "safe"

    score = round(35 + above_two * 7 + min(average, 5) * 5 - low_streak * 8)
    score = max(0, min(100, score))
    return {"level": level, "score": score, "average": average}


def build_direct_prediction(rows):
    values = [r["coef"] for r in rows if math.isfinite(r["coef"])]
    if len(values) < 5:
        raise RuntimeError("Недостаточно реальных коэффициентов для анализа")

    sorted_values = sorted(values)
    min_v = max(1.01, MIN_ODDS)
    max_v = max(min_v + 0.01, MAX_ODDS)
    index = math.floor((len(sorted_values) - 1) * 0.4)
    predicted = min(max_v, max(min_v, sorted_values[index]))

    hits = sum(1 for value in values if value >= predicted)
    confidence = round(hits / len(values) * 100)
    confidence = max(35, min(88, confidence))
    signal = "safe" if confidence >= 70 else ("warn" if confidence >= 50 else "danger")

    generated = datetime.now(timezone.utc)
    target = generated + timedelta(minutes=2)

    return {
        "success": True,
        "predicted_coef": round(predicted, 2),
        "confidence": confidence,
        "signal": signal,
        "bet_time": target.strftime("%H:%M"),
        "market_score": confidence,
        "avg_recent_coef": round(sum(values) / len(values), 2),
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "source": "direct-history",
    }


def poll_market():
    global market_level, last_market_poll
    try:
        data = api_get("/luckyjet/market")
        market_level = (data.get("level") if isinstance(data, dict) else None) or "warn"
        last_market_poll = time.time()
        return market_level
    except Exception:
        rows = fetch_recent_rows(8)
        direct = analyze_direct_market(rows)
        market_level = direct["level"]
        last_market_poll = time.time()
        return market_level


def check_market():
    # 1-в-1 логика страницы: сначала /check, а если API не сработал —
    # разрешаем продолжать при наличии >=5 реальных завершённых раундов.
    try:
        data = api_get("/luckyjet/check")
        if isinstance(data, dict) and (data.get("blocked") or data.get("safe") is False):
            return False
        return True
    except Exception:
        rows = fetch_recent_rows(5)
        if len(rows) < 5:
            raise RuntimeError("Недостаточно завершённых раундов для анализа")
        return True


def fetch_prediction():
    try:
        data = api_get("/luckyjet/predict")
        if not isinstance(data, dict) or data.get("success") is not True:
            raise RuntimeError("API не вернул прогноз")
        return data
    except Exception:
        rows = fetch_recent_rows(20)
        return build_direct_prediction(rows)


def parse_api_schedule(prediction):
    raw = str(prediction.get("bet_time") or "")
    parts = raw.split(":")
    if len(parts) < 2:
        return None

    try:
        hour = int(parts[0])
        minute = int(parts[1][:2])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    generated_raw = prediction.get("generated_at")
    try:
        generated = datetime.fromisoformat(str(generated_raw).replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        else:
            generated = generated.astimezone(timezone.utc)
    except Exception:
        generated = datetime.now(timezone.utc)

    target = generated.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target.timestamp() < generated.timestamp() - 120:
        target += timedelta(days=1)

    delay = max(0, target.timestamp() - generated.timestamp())
    return time.time() + delay


def fetch_latest_round():
    rows = fetch_recent_rows(5)
    if not rows:
        return None
    return {
        "coef": rows[0]["coef"],
        "signature": "|".join(row["id"] for row in rows),
    }


def signal_label(signal):
    key = str(signal or "").lower()
    return tr(key if key in {"safe", "warn", "danger"} else "ready")


def format_kyiv_timestamp(ts):
    return datetime.fromtimestamp(ts, KYIV).strftime("%H:%M")


def generate_signal():
    global active, last_generated_coef, last_round_signature

    level = poll_market()
    safe = check_market()
    if not safe:
        return False, "AllPredictor /check временно заблокировал прогнозы"
    if level == "danger":
        return False, "Рынок опасный — как на странице, сигнал отменён"

    prediction = fetch_prediction()

    coefficient = float(prediction["predicted_coef"])
    coefficient = min(max(coefficient, MIN_ODDS), MAX_ODDS)
    current = round(coefficient, 2)

    # Тот же антидубль +0.01 / -0.01, который есть на странице.
    if last_generated_coef is not None and current == last_generated_coef:
        current = round(min(MAX_ODDS, current + 0.01), 2)
        if current == last_generated_coef:
            current = round(max(MIN_ODDS, current - 0.01), 2)
    last_generated_coef = current

    scheduled_start = parse_api_schedule(prediction)
    if scheduled_start is None:
        scheduled_start = time.time() + 120

    active = {
        "predicted": current,
        "confidence": prediction.get("confidence"),
        "signal": prediction.get("signal"),
        "source": prediction.get("source"),
        "scheduled_start": scheduled_start,
        "verification_started": False,
        "current_round": 0,
        "round_values": [],
    }
    last_round_signature = None

    confidence = prediction.get("confidence")
    conf_text = f"{confidence}%" if confidence is not None else "—"
    source_text = (
        "реальные завершённые раунды (fallback)"
        if prediction.get("source") == "direct-history"
        else "AllPredictor /luckyjet/predict"
    )

    send_with_keyboard(
        f"{tr('signal_title')}\n\n"
        f"{tr('coef')}: {current:.2f}x\n"
        f"{tr('confidence')}: {conf_text}\n"
        f"{tr('status')}: {signal_label(prediction.get('signal'))}\n"
        f"{tr('market')}: {level}\n"
        f"{tr('entry')}: {format_kyiv_timestamp(scheduled_start)}\n"
        f"{tr('source')}: {source_text}\n\n"
        f"{tr('verify_info')}",
        main_keyboard(),
    )
    return True, "signal"


def verify_tick():
    global active, last_round_signature
    if not active:
        return None

    latest = fetch_latest_round()
    if not latest:
        return None

    if last_round_signature is None:
        last_round_signature = latest["signature"]
        return None

    if latest["signature"] == last_round_signature:
        return None

    last_round_signature = latest["signature"]

    # На странице проверка начинается только после того, как наступило время
    # и завершился следующий раунд.
    if not active["verification_started"]:
        if time.time() >= active["scheduled_start"]:
            active["verification_started"] = True
            active["current_round"] = 0
            send_with_keyboard(
                f"{tr('bet_now')}\n\n"
                f"{tr('target')}: {active['predicted']:.2f}x\n"
                f"{tr('checking')}",
                main_keyboard(),
            )
        return None

    rounded = round(1.01 if latest["coef"] == 1 else float(latest["coef"]), 2)
    active["current_round"] += 1
    active["round_values"].append(rounded)

    if rounded >= active["predicted"]:
        round_no = active["current_round"]
        target = active["predicted"]
        rounds = ", ".join(f"{x:.2f}x" for x in active["round_values"])
        global wins_total
        wins_total += 1
        save_stats()
        send_with_keyboard(
            f"{tr('win')}\n\n"
            f"{tr('target')}: {target:.2f}x\n"
            f"{tr('dropped')}: {rounded:.2f}x\n"
            f"{tr('round')}: {round_no}/3\n"
            f"{tr('verification')}: {rounds}\n\n"
            f"{stats_text()}",
            main_keyboard(),
        )
        active = None
        return True

    if active["current_round"] >= 3:
        target = active["predicted"]
        rounds = ", ".join(f"{x:.2f}x" for x in active["round_values"])
        global losses_total
        losses_total += 1
        save_stats()
        send_with_keyboard(
            f"{tr('lost')}\n\n"
            f"{tr('target')}: {target:.2f}x\n"
            f"{tr('rounds')}: {rounds}\n\n"
            f"{stats_text()}",
            main_keyboard(),
        )
        active = None
        return False

    return None


def main():
    global last_status_sent

    load_stats()
    send_with_keyboard(tr("choose_language"), language_keyboard())
    time.sleep(1)

    send_with_keyboard(
        "✅ LuckyJet RU-Ukraine EXACT запущен\n\n"
        "Скопирована логика твоей страницы ru-ukraine:\n"
        "• /luckyjet/market\n"
        "• /luckyjet/check\n"
        "• /luckyjet/predict\n"
        "• fallback на реальную /history\n"
        "• диапазон 2.00x–8.00x\n"
        "• вход по bet_time\n"
        "• проверка следующих 3 раундов\n"
        "• AUTO включён",
        main_keyboard(),
    )

    next_auto_attempt = 0.0

    while True:
        try:
            handle_telegram_commands()
            now = time.time()

            if now - last_market_poll >= MARKET_POLL_SECONDS:
                try:
                    poll_market()
                except Exception as exc:
                    print("[market]", exc)

            if active:
                result = verify_tick()
                if result is not None:
                    next_auto_attempt = time.time() + POST_RESULT_DELAY
            elif auto_mode and now >= next_auto_attempt:
                try:
                    started, reason = generate_signal()
                    next_auto_attempt = time.time() + (
                        999999 if started else AUTO_RETRY_SECONDS
                    )
                    if not started:
                        print("[auto]", reason)
                except Exception as exc:
                    print("[auto]", exc)
                    next_auto_attempt = time.time() + AUTO_RETRY_SECONDS

            # Ненавязчивый статус раз в 10 минут.
            if now - last_status_sent >= 600:
                try:
                    rows = fetch_recent_rows(5)
                    recent = ", ".join(f"{r['coef']:.2f}x" for r in rows)
                    state = (
                        f"активный сигнал {active['predicted']:.2f}x"
                        if active else
                        "жду новый сигнал"
                    )
                    send_telegram(
                        "🔎 RU-Ukraine EXACT работает\n\n"
                        f"🧭 Рынок: {market_level or '—'}\n"
                        f"📌 Последние: {recent}\n"
                        f"🤖 AUTO: {state}"
                    )
                    last_status_sent = now
                except Exception:
                    pass

        except Exception as exc:
            print("[loop]", exc)

        time.sleep(1)


if __name__ == "__main__":
    main()

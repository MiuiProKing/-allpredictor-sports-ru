# PUBLIC GITHUB COPY: set TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN in environment; active token intentionally not committed.
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LuckyJet Hybrid Signal Bot
--------------------------
Основа:
1) живые завершённые коэффициенты из /history;
2) фильтр AllPredictor: минимум 3 из последних 5 > 1.50x;
3) фильтр входа: последний завершённый коэффициент > 1.30x;
4) проверка сигнала по следующим 3 раундам;
5) SAFE / PRO / 10X;
6) 10X timing score откалиброван по двум пользовательским сессиям >=10x.

Важно:
- Это вероятностная логика, не способ узнать будущий коэффициент.
- Для 10X нет отрицательных примеров, поэтому score — эвристика тайминга,
  а не обученная вероятность выигрыша.
"""

import json
import math
import os
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

# ============================================================
# TELEGRAM
# ============================================================

TOKEN = os.getenv(
    "TELEGRAM_TOKEN",
    "",
)
ADMIN_ID = int(os.getenv("ADMIN_ID", "8016237913"))
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "-1003959529321"))

# ============================================================
# LIVE SOURCE — тот же источник, который использует страница
# ============================================================

HISTORY_URL = "https://crash-gateway-grm-cr.100hp.app/history"
HISTORY_HEADERS = {
    "customer-id": os.getenv(
        "LUCKYJET_CUSTOMER_ID",
        "",
    ),
    "session-id": os.getenv(
        "LUCKYJET_SESSION_ID",
        "",
    ),
    "accept": "application/json",
}

KYIV = ZoneInfo("Europe/Kyiv")
POLL_SECONDS = 5
HTTP_TIMEOUT = 15

# ============================================================
# ALLPREDICTOR FILTERS
# ============================================================

RECENT_WINDOW = 5
RECENT_MIN_COEF = 1.50
RECENT_REQUIRED = 3
ENTRY_GATE = 1.30
VERIFY_ROUNDS = 3

# ============================================================
# MODES
# ============================================================

MODES = {
    "SAFE": {
        "min_target": 1.50,
        "max_target": 2.00,
        "quantile": 0.42,
        "cooldown_seconds": 90,
    },
    "PRO": {
        "min_target": 2.00,
        "max_target": 3.50,
        "quantile": 0.62,
        "cooldown_seconds": 120,
    },
    "10X": {
        "min_target": 10.00,
        "max_target": 10.00,
        "quantile": None,
        "cooldown_seconds": 120,
    },
}

MODE = os.getenv("SIGNAL_MODE", "PRO").upper()
if MODE not in MODES:
    MODE = "PRO"

# ============================================================
# 10X CALIBRATION
# Из двух приложенных сессий:
# combined intervals > 0:
# mean ≈ 3.194 min
# median ≈ 2.7045 min
# Q25 ≈ 1.10375
# Q75 ≈ 4.46975
# P90 ≈ 6.7411
# ============================================================

TENX_MEAN_MIN = 3.1940357142857145
TENX_MEDIAN_MIN = 2.7045
TENX_Q25_MIN = 1.10375
TENX_Q75_MIN = 4.46975
TENX_P90_MIN = 6.7411

TENX_SIGNAL_SCORE = float(os.getenv("TENX_SIGNAL_SCORE", "67"))

# ============================================================
# STATE / PERSISTENCE
# ============================================================

STATE_FILE = Path(os.getenv("STATE_FILE", "luckyjet_hybrid_state.json"))

history_values = []          # newest last, rolling
known_round_ids = set()
last_round_id = None
last_coef = None

# cycle:
# None
# {"stage":"armed","target":...,"mode":...,"armed_at":...}
# {"stage":"verify","target":...,"mode":...,"rounds":[]}
cycle = None

last_signal_at = 0.0
last_10x_seen_at = None
rounds_since_10x = None

stats = {
    "SAFE": {"wins": 0, "losses": 0},
    "PRO": {"wins": 0, "losses": 0},
    "10X": {"wins": 0, "losses": 0},
}

# ============================================================
# HELPERS
# ============================================================

def now_kyiv():
    return datetime.now(KYIV)

def fmt_time(ts=None):
    if ts is None:
        return now_kyiv().strftime("%H:%M:%S")
    return datetime.fromtimestamp(ts, KYIV).strftime("%H:%M:%S")

def tg(text, keyboard=None):
    payload = {
        "chat_id": CHAT_ID,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = keyboard

    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json=payload,
        timeout=HTTP_TIMEOUT,
    )
    if not r.ok:
        print("[telegram]", r.status_code, r.text[:300])

def keyboard():
    return {
        "keyboard": [
            ["🟢 SAFE", "🔵 PRO", "🔥 10X"],
            ["📊 Статистика", "📡 Статус"],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }

def save_state():
    data = {
        "mode": MODE,
        "stats": stats,
        "last_signal_at": last_signal_at,
        "last_10x_seen_at": last_10x_seen_at,
        "rounds_since_10x": rounds_since_10x,
    }
    try:
        STATE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print("[save_state]", e)

def load_state():
    global MODE, stats, last_signal_at, last_10x_seen_at, rounds_since_10x
    try:
        if not STATE_FILE.exists():
            return
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        m = str(d.get("mode", MODE)).upper()
        if m in MODES:
            MODE = m

        old_stats = d.get("stats", {})
        for m in stats:
            if m in old_stats:
                stats[m]["wins"] = int(old_stats[m].get("wins", 0))
                stats[m]["losses"] = int(old_stats[m].get("losses", 0))

        last_signal_at = float(d.get("last_signal_at", 0) or 0)
        x = d.get("last_10x_seen_at")
        last_10x_seen_at = float(x) if x else None
        rs = d.get("rounds_since_10x")
        rounds_since_10x = int(rs) if rs is not None else None
    except Exception as e:
        print("[load_state]", e)

def get_coef(item):
    for key in ("coef", "crash", "value", "topCoefficient", "multiplier"):
        if key in item and item[key] is not None:
            try:
                v = float(item[key])
                if v == 1.0:
                    v = 1.01
                return round(v, 2)
            except Exception:
                pass
    return None

def get_round_id(item):
    rid = item.get("id")
    if rid:
        return str(rid)
    # fallback signature
    return f"{item.get('hash','')}:{get_coef(item)}"

def fetch_history():
    r = requests.get(
        HISTORY_URL,
        headers=HISTORY_HEADERS,
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError("history response is not a list")
    return data

def percentile(values, q):
    if not values:
        return None
    s = sorted(float(x) for x in values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)

# ============================================================
# MARKET LOGIC
# ============================================================

def allpredictor_recent_filter():
    if len(history_values) < RECENT_WINDOW:
        return False, 0
    w = history_values[-RECENT_WINDOW:]
    count = sum(1 for c in w if c > RECENT_MIN_COEF)
    return count >= RECENT_REQUIRED, count

def market_metrics():
    recent = history_values[-20:]
    if not recent:
        return {
            "median": 0,
            "gt15": 0,
            "gt2": 0,
            "gt5": 0,
            "gt10": 0,
            "low13": 0,
        }

    n = len(recent)
    return {
        "median": percentile(recent, 0.5) or 0,
        "gt15": sum(c > 1.50 for c in recent) / n,
        "gt2": sum(c >= 2.00 for c in recent) / n,
        "gt5": sum(c >= 5.00 for c in recent) / n,
        "gt10": sum(c >= 10.00 for c in recent) / n,
        "low13": sum(c <= 1.30 for c in recent) / n,
    }

def tenx_timing_score():
    """
    Эвристический score 0..100.

    Основа — время после последнего НАБЛЮДЁННОГО live события >=10x
    и интервалы из двух пользовательских 10x-сессий.

    Это не математическая вероятность следующего 10x.
    """
    if last_10x_seen_at is None:
        return 0, "нужен live-базовый 10x"

    elapsed_min = (time.time() - last_10x_seen_at) / 60.0

    # Основной timing score:
    # около Q25 ещё рано; около median/mean — зона максимума;
    # очень большой хвост после P90 снижает уверенность.
    if elapsed_min < 0.45:
        timing = 15
    elif elapsed_min < TENX_Q25_MIN:
        # 15 -> 45
        t = (elapsed_min - 0.45) / max(0.01, TENX_Q25_MIN - 0.45)
        timing = 15 + 30 * t
    elif elapsed_min <= TENX_MEDIAN_MIN:
        # 45 -> 82
        t = (elapsed_min - TENX_Q25_MIN) / max(0.01, TENX_MEDIAN_MIN - TENX_Q25_MIN)
        timing = 45 + 37 * t
    elif elapsed_min <= TENX_Q75_MIN:
        # 82 -> 88 around broad empirical core
        center = TENX_MEAN_MIN
        spread = max(0.25, TENX_Q75_MIN - TENX_Q25_MIN)
        timing = 88 - 12 * abs(elapsed_min - center) / spread
        timing = max(72, timing)
    elif elapsed_min <= TENX_P90_MIN:
        # long but still observed frequently enough
        t = (elapsed_min - TENX_Q75_MIN) / max(0.01, TENX_P90_MIN - TENX_Q75_MIN)
        timing = 72 - 17 * t
    else:
        timing = max(28, 55 - (elapsed_min - TENX_P90_MIN) * 5)

    m = market_metrics()

    # Market adjustment. Не "предсказывает" RNG; лишь фильтрует состояние.
    adj = 0
    if m["gt15"] >= 0.60:
        adj += 7
    elif m["gt15"] < 0.40:
        adj -= 7

    if m["low13"] >= 0.40:
        adj -= 8

    if m["gt5"] >= 0.15:
        adj += 4

    # После самого 10x не блокируем сигнал надолго:
    # в приложенных данных большие значения иногда шли близко друг к другу.
    if rounds_since_10x is not None and rounds_since_10x <= 1:
        adj -= 5
    elif rounds_since_10x is not None and rounds_since_10x >= 4:
        adj += 3

    score = int(max(0, min(100, round(timing + adj))))
    reason = (
        f"{elapsed_min:.2f} мин после 10x+ • "
        f"median {TENX_MEDIAN_MIN:.2f} • mean {TENX_MEAN_MIN:.2f}"
    )
    return score, reason

def choose_target(mode):
    if mode == "10X":
        return 10.0

    cfg = MODES[mode]
    source = history_values[-20:] or history_values[-5:]
    qv = percentile(source, cfg["quantile"]) if source else cfg["min_target"]
    if qv is None:
        qv = cfg["min_target"]

    target = max(cfg["min_target"], min(cfg["max_target"], qv))
    return round(target, 2)

def signal_allowed(mode):
    ok, count = allpredictor_recent_filter()
    if not ok:
        return False, f"фильтр рынка: {count}/5 > 1.50"

    if last_coef is None or last_coef <= ENTRY_GATE:
        return False, f"последний {last_coef or 0:.2f}x <= {ENTRY_GATE:.2f}x"

    m = market_metrics()

    if mode == "SAFE":
        # избегаем слишком "тяжёлой" низкой серии
        if m["low13"] > 0.45:
            return False, "слишком много <=1.30x"

    if mode == "PRO":
        if m["gt2"] < 0.25:
            return False, "слишком мало 2x+ в последних 20"

    if mode == "10X":
        score, reason = tenx_timing_score()
        if score < TENX_SIGNAL_SCORE:
            return False, f"10X score {score}/100 • {reason}"

    return True, "рынок прошёл фильтры"

# ============================================================
# SIGNAL CYCLE
# ============================================================

def arm_signal():
    global cycle, last_signal_at

    allowed, why = signal_allowed(MODE)
    if not allowed:
        return False

    cooldown = MODES[MODE]["cooldown_seconds"]
    if time.time() - last_signal_at < cooldown:
        return False

    target = choose_target(MODE)
    score10, reason10 = tenx_timing_score()

    cycle = {
        "stage": "armed",
        "target": target,
        "mode": MODE,
        "armed_at": time.time(),
        "armed_round_id": last_round_id,
        "rounds": [],
    }

    last_signal_at = time.time()
    save_state()

    extra = ""
    if MODE == "10X":
        extra = f"\n🔥 10X timing score: {score10}/100\n🧪 {reason10}"

    ok5, count5 = allpredictor_recent_filter()
    recent_txt = " / ".join(f"{x:.2f}x" for x in history_values[-5:])

    tg(
        f"🟡 ПОДГОТОВКА К ВХОДУ · {MODE}\n\n"
        f"🎯 Цель: {target:.2f}x\n"
        f"🧭 AllPredictor-фильтр: {count5}/5 > 1.50x\n"
        f"✅ Последний коэффициент: {last_coef:.2f}x > 1.30x\n"
        f"📉 Последние 5: {recent_txt}\n"
        f"⏰ {fmt_time()}\n\n"
        f"Следующий завершённый раунд используется как переход.\n"
        f"После него пришлю «СТАВЬ СЕЙЧАС» и начну проверку следующих 3 раундов."
        f"{extra}",
        keyboard(),
    )
    return True

def start_verification():
    global cycle

    if not cycle or cycle["stage"] != "armed":
        return

    cycle["stage"] = "verify"
    cycle["verify_started_at"] = time.time()
    cycle["rounds"] = []

    tg(
        f"🎯 СТАВЬ СЕЙЧАС · {cycle['mode']}\n\n"
        f"Цель: {cycle['target']:.2f}x\n"
        f"Проверяю следующие {VERIFY_ROUNDS} новых раунда.\n"
        f"⏰ {fmt_time()}",
        keyboard(),
    )

def finish_cycle(win, hit_round=None):
    global cycle

    if not cycle:
        return

    mode = cycle["mode"]
    target = cycle["target"]
    rounds = list(cycle.get("rounds", []))

    if win:
        stats[mode]["wins"] += 1
        title = "✅ ЗАШЛО"
        detail = f"Цель {target:.2f}x достигнута на раунде {hit_round}/3."
    else:
        stats[mode]["losses"] += 1
        title = "❌ НЕ ЗАШЛО"
        detail = f"Цель {target:.2f}x не достигнута за 3 раунда."

    save_state()

    total = stats[mode]["wins"] + stats[mode]["losses"]
    wr = 100.0 * stats[mode]["wins"] / total if total else 0
    rs = " / ".join(f"{x:.2f}x" for x in rounds)

    tg(
        f"{title} · {mode}\n\n"
        f"{detail}\n"
        f"📉 Раунды: {rs}\n"
        f"📊 {mode}: {stats[mode]['wins']} WIN / {stats[mode]['losses']} LOSS "
        f"• {wr:.1f}%\n"
        f"⏰ {fmt_time()}",
        keyboard(),
    )

    cycle = None

def process_new_round(rid, coef):
    global last_round_id, last_coef, last_10x_seen_at, rounds_since_10x, cycle

    last_round_id = rid
    last_coef = coef

    history_values.append(coef)
    if len(history_values) > 100:
        del history_values[:-100]

    # Live 10x tracking
    if coef >= 10.0:
        last_10x_seen_at = time.time()
        rounds_since_10x = 0
        save_state()
    else:
        if rounds_since_10x is not None:
            rounds_since_10x += 1

    # Cycle state machine
    if cycle and cycle["stage"] == "armed":
        # Именно этот один новый завершённый раунд — переход.
        # После него начинается проверка СЛЕДУЮЩИХ 3.
        start_verification()
        return

    if cycle and cycle["stage"] == "verify":
        cycle["rounds"].append(coef)
        n = len(cycle["rounds"])

        if coef >= cycle["target"]:
            finish_cycle(True, n)
            return

        if n >= VERIFY_ROUNDS:
            finish_cycle(False)
            return

        tg(
            f"⏳ ПРОВЕРКА {n}/3 · {cycle['mode']}\n"
            f"Выпало: {coef:.2f}x\n"
            f"Цель: {cycle['target']:.2f}x\n"
            f"Осталось раундов: {VERIFY_ROUNDS - n}"
        )
        return

    # No active cycle -> try to arm
    arm_signal()

# ============================================================
# TELEGRAM COMMANDS
# ============================================================

telegram_offset = 0

def poll_telegram_commands():
    global telegram_offset, MODE

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"offset": telegram_offset, "timeout": 0},
            timeout=HTTP_TIMEOUT,
        )
        if not r.ok:
            return

        data = r.json()
        if not data.get("ok"):
            return

        for upd in data.get("result", []):
            telegram_offset = max(telegram_offset, upd["update_id"] + 1)
            msg = upd.get("message") or upd.get("channel_post") or {}
            text = str(msg.get("text", "")).strip()

            new_mode = None
            if text in ("🟢 SAFE", "/safe", "SAFE"):
                new_mode = "SAFE"
            elif text in ("🔵 PRO", "/pro", "PRO"):
                new_mode = "PRO"
            elif text in ("🔥 10X", "/10x", "10X"):
                new_mode = "10X"

            if new_mode:
                MODE = new_mode
                save_state()
                tg(f"✅ Режим переключён: {MODE}", keyboard())
                continue

            if text in ("📊 Статистика", "/stats"):
                tg(stats_text(), keyboard())
                continue

            if text in ("📡 Статус", "/status"):
                tg(status_text(), keyboard())
                continue
    except Exception as e:
        print("[telegram commands]", e)

def stats_text():
    parts = ["📊 СТАТИСТИКА"]
    for m in ("SAFE", "PRO", "10X"):
        w = stats[m]["wins"]
        l = stats[m]["losses"]
        total = w + l
        wr = 100 * w / total if total else 0
        parts.append(f"{m}: ✅ {w} / ❌ {l} • {wr:.1f}%")
    return "\n".join(parts)

def status_text():
    ok, count = allpredictor_recent_filter()
    score, reason = tenx_timing_score()
    recent = " / ".join(f"{x:.2f}x" for x in history_values[-5:]) or "—"
    cyc = cycle["stage"] if cycle else "нет"
    return (
        f"📡 LUCKYJET HYBRID\n\n"
        f"Режим: {MODE}\n"
        f"Последний: {last_coef:.2f}x\n" if last_coef is not None else
        f"📡 LUCKYJET HYBRID\n\nРежим: {MODE}\nПоследний: —\n"
    ) + (
        f"Фильтр 3/5 >1.50: {count}/5 {'✅' if ok else '⏳'}\n"
        f"10X score: {score}/100\n"
        f"10X: {reason}\n"
        f"Цикл: {cyc}\n"
        f"Последние 5: {recent}"
    )

# ============================================================
# BOOT / LIVE LOOP
# ============================================================

def bootstrap():
    global history_values, known_round_ids, last_round_id, last_coef, rounds_since_10x

    data = fetch_history()
    if not data:
        raise RuntimeError("empty history")

    # API returns newest first.
    recent = data[:30]
    chronological = list(reversed(recent))

    history_values = []
    known_round_ids = set()

    latest_10x_distance = None
    distance = 0

    for item in chronological:
        rid = get_round_id(item)
        coef = get_coef(item)
        if coef is None:
            continue
        known_round_ids.add(rid)
        history_values.append(coef)

    newest = recent[0]
    last_round_id = get_round_id(newest)
    last_coef = get_coef(newest)

    # round distance from current snapshot to latest >=10x
    for item in recent:
        c = get_coef(item)
        if c is None:
            continue
        if c >= 10:
            latest_10x_distance = distance
            break
        distance += 1

    if rounds_since_10x is None and latest_10x_distance is not None:
        rounds_since_10x = latest_10x_distance

def find_new_rounds(data):
    """
    Возвращает новые раунды в хронологическом порядке.
    Дедупликация по ID, а не по значению коэффициента.
    """
    new_items = []
    for item in data:
        rid = get_round_id(item)
        if rid in known_round_ids:
            continue
        coef = get_coef(item)
        if coef is None:
            continue
        new_items.append((rid, coef))

    # API newest first -> process oldest first
    new_items.reverse()
    return new_items

def main():
    load_state()

    while True:
        try:
            bootstrap()
            break
        except Exception as e:
            print("[bootstrap]", e)
            time.sleep(5)

    tg(
        "🚀 LUCKYJET HYBRID запущен\n\n"
        f"Режим: {MODE}\n"
        f"Источник: live /history\n"
        f"Фильтр: 3 из 5 > 1.50x\n"
        f"Вход: последний > 1.30x\n"
        f"Проверка: 3 следующих раунда\n"
        f"10X calibration: 2 сессии, 28 интервалов\n\n"
        f"⚠️ Сигналы вероятностные; будущий RNG напрямую не читается.",
        keyboard(),
    )

    while True:
        try:
            poll_telegram_commands()

            data = fetch_history()
            new_rounds = find_new_rounds(data)

            for rid, coef in new_rounds:
                known_round_ids.add(rid)
                # ограничим память IDs
                if len(known_round_ids) > 500:
                    current_ids = {get_round_id(x) for x in data[:100]}
                    known_round_ids.intersection_update(current_ids)
                    known_round_ids.add(rid)

                print(fmt_time(), rid, coef)
                process_new_round(rid, coef)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print("[loop]", repr(e))

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()

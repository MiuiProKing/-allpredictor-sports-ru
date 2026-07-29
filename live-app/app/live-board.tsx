"use client";

import { useEffect, useMemo, useState } from "react";

const BOOKMAKER_URL = "https://one-vv1220.com/betting?p=yshe";

const SPORTS = [
  { id: "football", name: "Футбол", icon: "⚽" },
  { id: "tennis", name: "Теннис", icon: "🎾" },
  { id: "basketball", name: "Баскетбол", icon: "🏀" },
  { id: "hockey", name: "Хоккей", icon: "🏒" },
  { id: "baseball", name: "Бейсбол", icon: "⚾" },
  { id: "rugby", name: "Регби", icon: "🏉" },
] as const;

type SportId = (typeof SPORTS)[number]["id"];

type Form = {
  played: number;
  wins: number;
  draws: number;
  losses: number;
  recent: string[];
};

type Prediction = {
  probabilities: {
    home: number;
    draw: number | null;
    away: number;
  };
  recommendedCode: "1" | "X" | "2";
  recommendedLabel: string;
  confidence: "Низкая" | "Средняя";
  note: string;
  totalHint: string | null;
  bttsHint: string | null;
};

type Match = {
  id: string;
  sport: string;
  league: string;
  country: string | null;
  home: string;
  away: string;
  date: string;
  time: string | null;
  timestamp: string | null;
  status: string | null;
  score: string | null;
  homeBadge: string | null;
  awayBadge: string | null;
  form: {
    home: Form;
    away: Form;
  };
  prediction: Prediction | null;
};

type MatchesResponse = {
  matches: Match[];
  updatedAt: string;
  source: string;
  limitedCoverage: boolean;
  message?: string;
};

type Selection = {
  matchId: string;
  matchName: string;
  league: string;
  code: "1" | "X" | "2";
  label: string;
  probability: number;
};

function kyivIsoDate(offset: number) {
  const date = new Date(Date.now() + offset * 86_400_000);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Kyiv",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);

  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";

  return `${get("year")}-${get("month")}-${get("day")}`;
}

function formatDate(offset: number) {
  if (offset === 0) return "Сегодня";
  if (offset === 1) return "Завтра";
  if (offset === 2) return "Послезавтра";

  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Kyiv",
    day: "numeric",
    month: "short",
  }).format(new Date(Date.now() + offset * 86_400_000));
}

function shortDate(offset: number) {
  const [, month, day] = kyivIsoDate(offset).split("-");
  return `${day}.${month}`;
}

function formatKickoff(match: Match) {
  if (match.timestamp) {
    const parsed = new Date(match.timestamp);
    if (!Number.isNaN(parsed.getTime())) {
      return new Intl.DateTimeFormat("ru-RU", {
        timeZone: "Europe/Kyiv",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(parsed);
    }
  }

  return match.time?.slice(0, 5) || "Время уточняется";
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formClass(result: string) {
  if (result === "В") return "form-dot form-win";
  if (result === "Н") return "form-dot form-draw";
  return "form-dot form-loss";
}

function TeamBadge({
  src,
  name,
}: {
  src: string | null;
  name: string;
}) {
  const [failed, setFailed] = useState(false);
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  if (!src || failed) {
    return <span className="team-fallback">{initials || "?"}</span>;
  }

  return (
    // The source API returns public team artwork URLs.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className="team-badge"
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

export default function LiveBoard() {
  const [sport, setSport] = useState<SportId>("football");
  const [dateOffset, setDateOffset] = useState(0);
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);

  const date = useMemo(() => kyivIsoDate(dateOffset), [dateOffset]);
  const sportName =
    SPORTS.find((item) => item.id === sport)?.name ?? "Спорт";
  const hasDrawMarket =
    sport === "football" || sport === "hockey" || sport === "rugby";

  useEffect(() => {
    const controller = new AbortController();

    const demoMode =
      new URLSearchParams(window.location.search).get("demo") === "1";
    fetch(
      `/match-feed?sport=${sport}&date=${date}${demoMode ? "&demo=1" : ""}`,
      {
      signal: controller.signal,
      },
    )
      .then(async (response) => {
        const payload = (await response.json()) as MatchesResponse & {
          error?: string;
        };
        if (!response.ok) {
          throw new Error(payload.error || "Не удалось загрузить матчи");
        }
        return payload;
      })
      .then(setData)
      .catch((requestError: unknown) => {
        if (
          requestError instanceof DOMException &&
          requestError.name === "AbortError"
        ) {
          return;
        }
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Не удалось загрузить матчи",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [sport, date]);

  function beginFilterChange() {
    setLoading(true);
    setError(null);
    setSelection(null);
  }

  function chooseOutcome(
    match: Match,
    code: "1" | "X" | "2",
    probability: number,
  ) {
    const label =
      code === "1"
        ? `Победа: ${match.home}`
        : code === "2"
          ? `Победа: ${match.away}`
          : "Ничья";

    setSelection({
      matchId: match.id,
      matchName: `${match.home} — ${match.away}`,
      league: match.league,
      code,
      label,
      probability,
    });

    window.setTimeout(() => {
      document
        .getElementById("selection-slip")
        ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }, 50);
  }

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="В начало">
          <span className="brand-mark">A</span>
          <span>
            <strong>ALLPREDICTOR</strong>
            <small>SPORTS LIVE</small>
          </span>
        </a>
        <div className="live-state">
          <span className="live-dot" />
          Реальные матчи
        </div>
      </header>

      <div className="page-shell" id="top">
        <section className="hero">
          <div>
            <p className="eyebrow">Линия и понятный разбор</p>
            <h1>
              Выберите матч.
              <br />
              Разберитесь <em>до ставки.</em>
            </h1>
            <p className="hero-copy">
              Матчи загружаются из открытой спортивной базы. Оценки считаются
              по доступной недавней форме команд и не являются гарантией.
            </p>
          </div>
          <div className="hero-guide">
            <span className="guide-number">1</span>
            <p>
              Сначала нажмите вид спорта, затем дату и нужный исход
              <strong> 1 / X / 2</strong>.
            </p>
          </div>
        </section>

        <section className="responsible-note">
          <span aria-hidden="true">⚠</span>
          <p>
            <strong>18+ · Игра на деньги связана с риском.</strong> Этот сайт
            не принимает ставки, не хранит логин или банковские данные и не
            обещает выигрыш.
          </p>
        </section>

        <nav className="sports-tabs" aria-label="Виды спорта">
          {SPORTS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={sport === item.id ? "sport-tab active" : "sport-tab"}
              onClick={() => {
                if (item.id === sport) return;
                beginFilterChange();
                setSport(item.id);
              }}
            >
              <span>{item.icon}</span>
              {item.name}
            </button>
          ))}
        </nav>

        <div className="content-grid">
          <section className="line-column" aria-busy={loading}>
            <div className="line-heading">
              <div>
                <p className="section-kicker">Линия</p>
                <h2>{sportName}</h2>
              </div>
              <span className="source-badge">
                Данные: {data?.source || "TheSportsDB"}
              </span>
            </div>

            <div className="date-tabs" aria-label="Дата матчей">
              {[0, 1, 2].map((offset) => (
                <button
                  key={offset}
                  type="button"
                  className={dateOffset === offset ? "active" : ""}
                  onClick={() => {
                    if (offset === dateOffset) return;
                    beginFilterChange();
                    setDateOffset(offset);
                  }}
                >
                  <strong>{formatDate(offset)}</strong>
                  <small>{shortDate(offset)}</small>
                </button>
              ))}
            </div>

            <div className="market-legend">
              <span>
                <b>1</b> победа первой команды
              </span>
              {hasDrawMarket && (
                <span>
                  <b>X</b> ничья
                </span>
              )}
              <span>
                <b>2</b> победа второй команды
              </span>
              <span className="legend-info">Проценты ≠ коэффициенты</span>
            </div>

            {loading && (
              <div className="state-card">
                <span className="loader" />
                <div>
                  <strong>Загружаю реальные матчи</strong>
                  <p>Получаю расписание и доступную форму команд…</p>
                </div>
              </div>
            )}

            {!loading && error && (
              <div className="state-card error-card">
                <span>!</span>
                <div>
                  <strong>Источник временно недоступен</strong>
                  <p>{error}. Попробуйте сменить дату или обновить страницу.</p>
                </div>
              </div>
            )}

            {!loading && !error && data?.matches.length === 0 && (
              <div className="state-card">
                <span>○</span>
                <div>
                  <strong>На эту дату матчей не найдено</strong>
                  <p>
                    Бесплатный источник показывает ограниченную часть
                    расписания. Проверьте соседнюю дату или другой спорт.
                  </p>
                  {dateOffset === 0 && (
                    <button
                      type="button"
                      className="next-date-button"
                      onClick={() => {
                        beginFilterChange();
                        setDateOffset(1);
                      }}
                    >
                      Показать завтра →
                    </button>
                  )}
                </div>
              </div>
            )}

            {!loading &&
              !error &&
              data?.matches.map((match) => {
                const prediction = match.prediction;
                const codes: Array<{
                  code: "1" | "X" | "2";
                  value: number | null;
                }> = [
                  { code: "1", value: prediction?.probabilities.home ?? null },
                  ...(prediction?.probabilities.draw !== null
                    ? [
                        {
                          code: "X" as const,
                          value: prediction?.probabilities.draw ?? null,
                        },
                      ]
                    : []),
                  { code: "2", value: prediction?.probabilities.away ?? null },
                ];

                return (
                  <article className="match-card" key={match.id}>
                    <div className="match-meta">
                      <span>{match.country || "Международный турнир"}</span>
                      <strong>{match.league}</strong>
                      <time>{formatKickoff(match)} · Киев</time>
                    </div>

                    <div className="teams">
                      <div className="team">
                        <TeamBadge src={match.homeBadge} name={match.home} />
                        <div>
                          <strong>{match.home}</strong>
                          <div className="form-row" aria-label="Последняя форма">
                            {match.form.home.recent.length ? (
                              match.form.home.recent.map((result, index) => (
                                <span
                                  className={formClass(result)}
                                  key={`${result}-${index}`}
                                >
                                  {result}
                                </span>
                              ))
                            ) : (
                              <small>форма не найдена</small>
                            )}
                          </div>
                        </div>
                      </div>

                      <span className="versus">VS</span>

                      <div className="team away-team">
                        <TeamBadge src={match.awayBadge} name={match.away} />
                        <div>
                          <strong>{match.away}</strong>
                          <div className="form-row" aria-label="Последняя форма">
                            {match.form.away.recent.length ? (
                              match.form.away.recent.map((result, index) => (
                                <span
                                  className={formClass(result)}
                                  key={`${result}-${index}`}
                                >
                                  {result}
                                </span>
                              ))
                            ) : (
                              <small>форма не найдена</small>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>

                    {prediction ? (
                      <div className="analysis-strip">
                        <div>
                          <small>Расчёт модели</small>
                          <strong>{prediction.recommendedLabel}</strong>
                        </div>
                        <div>
                          <small>Уверенность</small>
                          <strong
                            className={
                              prediction.confidence === "Средняя"
                                ? "confidence-medium"
                                : "confidence-low"
                            }
                          >
                            {prediction.confidence}
                          </strong>
                        </div>
                        {(prediction.totalHint || prediction.bttsHint) && (
                          <div className="extra-hints">
                            {prediction.totalHint && (
                              <span>{prediction.totalHint}</span>
                            )}
                            {prediction.bttsHint && (
                              <span>{prediction.bttsHint}</span>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="analysis-strip no-data">
                        Недостаточно прошлых результатов для честной оценки.
                      </div>
                    )}

                    <div className="market-title">
                      <span>Исход матча</span>
                      <small>нажмите вариант, чтобы добавить в памятку</small>
                    </div>

                    <div
                      className={`market-buttons markets-${codes.length}`}
                      aria-label="Аналитическая вероятность исходов"
                    >
                      {codes.map(({ code, value }) => {
                        const isSelected =
                          selection?.matchId === match.id &&
                          selection.code === code;
                        return (
                          <button
                            type="button"
                            key={code}
                            disabled={value === null}
                            className={isSelected ? "selected" : ""}
                            onClick={() =>
                              value !== null &&
                              chooseOutcome(match, code, value)
                            }
                          >
                            <span>{code}</span>
                            <strong>{value === null ? "—" : percent(value)}</strong>
                          </button>
                        );
                      })}
                    </div>

                    {prediction && (
                      <details>
                        <summary>Почему такая оценка?</summary>
                        <p>{prediction.note}</p>
                      </details>
                    )}
                  </article>
                );
              })}

            {data?.limitedCoverage && !loading && !error && (
              <p className="coverage-note">
                Бесплатный источник ограничивает выдачу несколькими событиями
                на запрос. Это не полная линия букмекерской компании.
              </p>
            )}
          </section>

          <aside className="bet-guide" id="selection-slip">
            <div className="sticky-card">
              <div className="slip-heading">
                <div>
                  <p className="section-kicker">Ваша памятка</p>
                  <h2>Перед переходом</h2>
                </div>
                <span className="guide-number">2</span>
              </div>

              {selection ? (
                <div className="selection-card">
                  <button
                    type="button"
                    className="clear-selection"
                    onClick={() => setSelection(null)}
                    aria-label="Удалить выбор"
                  >
                    ×
                  </button>
                  <small>{selection.league}</small>
                  <strong>{selection.matchName}</strong>
                  <div className="selection-outcome">
                    <span>{selection.code}</span>
                    <p>
                      {selection.label}
                      <small>
                        Оценка модели: {percent(selection.probability)}
                      </small>
                    </p>
                  </div>
                </div>
              ) : (
                <div className="empty-selection">
                  <span>☝</span>
                  <p>
                    Нажмите <strong>1, X или 2</strong> возле матча. Здесь
                    появится выбранный исход, чтобы не перепутать его на сайте
                    ставок.
                  </p>
                </div>
              )}

              <div className="how-to">
                <h3>Где нажимать у букмекера</h3>
                <ol>
                  <li>
                    <span>1</span>
                    <p>
                      Нажмите зелёную кнопку ниже — страница ставок откроется в
                      новой вкладке.
                    </p>
                  </li>
                  <li>
                    <span>2</span>
                    <p>
                      Откройте <b>Спорт / Линия</b>, выберите тот же вид спорта
                      и найдите команды из памятки.
                    </p>
                  </li>
                  <li>
                    <span>3</span>
                    <p>
                      В строке матча нажмите коэффициент под <b>1</b>, <b>X</b>
                      или <b>2</b>. Он добавится в купон.
                    </p>
                  </li>
                  <li>
                    <span>4</span>
                    <p>
                      В купоне ещё раз проверьте матч и исход. Сумму вводите и
                      подтверждайте только на стороне букмекера.
                    </p>
                  </li>
                </ol>
              </div>

              <a
                className="bookmaker-button"
                href={BOOKMAKER_URL}
                target="_blank"
                rel="noopener noreferrer nofollow"
              >
                Открыть сайт ставок
                <span>↗</span>
              </a>
              <p className="external-warning">
                Внешний сайт. Проверьте адрес, возрастные и правовые ограничения
                вашей страны. Мы не проверяли его лицензию и безопасность.
              </p>
            </div>
          </aside>
        </div>

        <section className="explain-section">
          <div className="explain-heading">
            <p className="section-kicker">Как это работает</p>
            <h2>Без чёрного ящика</h2>
          </div>
          <div className="explain-grid">
            <article>
              <span>01</span>
              <h3>Реальное расписание</h3>
              <p>
                Названия команд, турниры и время берутся из TheSportsDB. Время
                показывается по Киеву.
              </p>
            </article>
            <article>
              <span>02</span>
              <h3>Доступная форма</h3>
              <p>
                Модель смотрит последние найденные результаты: победы,
                ничьи, поражения и забитые/пропущенные мячи.
              </p>
            </article>
            <article>
              <span>03</span>
              <h3>Вероятность, не обещание</h3>
              <p>
                Проценты помогают сравнить исходы. Это не букмекерский
                коэффициент и не гарантия результата.
              </p>
            </article>
          </div>
        </section>

        <section className="dictionary">
          <div>
            <p className="section-kicker">Шпаргалка</p>
            <h2>Что означают рынки</h2>
          </div>
          <dl>
            <div>
              <dt>1</dt>
              <dd>Победа команды, указанной первой</dd>
            </div>
            <div>
              <dt>X</dt>
              <dd>Ничья в основное время</dd>
            </div>
            <div>
              <dt>2</dt>
              <dd>Победа команды, указанной второй</dd>
            </div>
            <div>
              <dt>ТБ 2.5</dt>
              <dd>Три и больше голов за матч</dd>
            </div>
            <div>
              <dt>ТМ 2.5</dt>
              <dd>Не больше двух голов за матч</dd>
            </div>
            <div>
              <dt>ОЗ</dt>
              <dd>Обе команды забьют хотя бы по одному голу</dd>
            </div>
          </dl>
        </section>

        <footer>
          <p>
            AllPredictor Sports Live · Независимый аналитический интерфейс, не
            букмекер и не финансовая рекомендация.
          </p>
          <p>Источник расписания: TheSportsDB · Обновление с кэшированием.</p>
        </footer>
      </div>
    </main>
  );
}

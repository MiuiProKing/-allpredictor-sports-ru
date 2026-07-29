// Public, keyless match feed used by the interactive board.
const SPORTS = {
  football: { apiName: "Soccer", allowsDraw: true },
  tennis: { apiName: "Tennis", allowsDraw: false },
  basketball: { apiName: "Basketball", allowsDraw: false },
  hockey: { apiName: "Ice_Hockey", allowsDraw: true },
  baseball: { apiName: "Baseball", allowsDraw: false },
  rugby: { apiName: "Rugby", allowsDraw: true },
} as const;

type SportId = keyof typeof SPORTS;

type RawEvent = {
  idEvent?: string;
  idLeague?: string;
  strSport?: string;
  strLeague?: string;
  strSeason?: string;
  strCountry?: string;
  strHomeTeam?: string;
  strAwayTeam?: string;
  idHomeTeam?: string;
  idAwayTeam?: string;
  strHomeTeamBadge?: string;
  strAwayTeamBadge?: string;
  dateEvent?: string;
  strTime?: string;
  strTimestamp?: string;
  strStatus?: string;
  intHomeScore?: string | number | null;
  intAwayScore?: string | number | null;
};

type FormSnapshot = {
  played: number;
  wins: number;
  draws: number;
  losses: number;
  scoredAverage: number;
  concededAverage: number;
  pointsRate: number;
  recent: string[];
};

const EMPTY_FORM: FormSnapshot = {
  played: 0,
  wins: 0,
  draws: 0,
  losses: 0,
  scoredAverage: 0,
  concededAverage: 0,
  pointsRate: 0.5,
  recent: [],
};

const responseCache = new Map<
  string,
  { expiresAt: number; payload: Record<string, unknown> }
>();

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function sigmoid(value: number) {
  return 1 / (1 + Math.exp(-value));
}

function numberScore(value: RawEvent["intHomeScore"]) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

async function fetchJson(url: string) {
  const response = await fetch(url, {
    headers: { accept: "application/json" },
    next: { revalidate: 900 },
  });

  if (!response.ok) {
    throw new Error(`Спортивный источник ответил ${response.status}`);
  }

  return (await response.json()) as {
    events?: RawEvent[] | null;
    results?: RawEvent[] | null;
  };
}

async function recentEvents(teamId?: string) {
  if (!teamId) return [];
  try {
    const payload = await fetchJson(
      `https://www.thesportsdb.com/api/v1/json/123/eventslast.php?id=${encodeURIComponent(teamId)}`,
    );
    return payload.results ?? payload.events ?? [];
  } catch {
    return [];
  }
}

async function seasonEvents(leagueId?: string, season?: string) {
  if (!leagueId || !season) return [];
  try {
    const payload = await fetchJson(
      "https://www.thesportsdb.com/api/v1/json/123/eventsseason.php" +
        `?id=${encodeURIComponent(leagueId)}` +
        `&s=${encodeURIComponent(season)}`,
    );
    return payload.events ?? [];
  } catch {
    return [];
  }
}

function buildForm(
  teamName: string,
  events: RawEvent[],
  allowsDraw: boolean,
): FormSnapshot {
  let wins = 0;
  let draws = 0;
  let losses = 0;
  let scored = 0;
  let conceded = 0;
  const recent: string[] = [];

  for (const event of events.slice(0, 5)) {
    const homeScore = numberScore(event.intHomeScore);
    const awayScore = numberScore(event.intAwayScore);
    if (homeScore === null || awayScore === null) continue;

    const isHome = event.strHomeTeam === teamName;
    const isAway = event.strAwayTeam === teamName;
    if (!isHome && !isAway) continue;

    const teamScore = isHome ? homeScore : awayScore;
    const opponentScore = isHome ? awayScore : homeScore;
    scored += teamScore;
    conceded += opponentScore;

    if (teamScore > opponentScore) {
      wins += 1;
      recent.push("В");
    } else if (teamScore < opponentScore) {
      losses += 1;
      recent.push("П");
    } else {
      draws += 1;
      recent.push("Н");
    }
  }

  const played = wins + draws + losses;
  if (!played) return { ...EMPTY_FORM };

  const maximumPoints = allowsDraw ? played * 3 : played;
  const earnedPoints = allowsDraw ? wins * 3 + draws : wins;

  return {
    played,
    wins,
    draws,
    losses,
    scoredAverage: scored / played,
    concededAverage: conceded / played,
    pointsRate: earnedPoints / maximumPoints,
    recent,
  };
}

function roundProbability(value: number) {
  return Math.round(value * 1000) / 1000;
}

function buildPrediction(
  home: string,
  away: string,
  homeForm: FormSnapshot,
  awayForm: FormSnapshot,
  allowsDraw: boolean,
  sport: SportId,
) {
  const totalGames = homeForm.played + awayForm.played;
  if (totalGames < 3) return null;

  const homeGoalBalance =
    homeForm.scoredAverage - homeForm.concededAverage;
  const awayGoalBalance =
    awayForm.scoredAverage - awayForm.concededAverage;
  const formDelta = homeForm.pointsRate - awayForm.pointsRate;
  const homeAdvantage = sport === "football" ? 0.18 : 0.1;
  const rawStrength =
    homeAdvantage +
    formDelta * 1.9 +
    (homeGoalBalance - awayGoalBalance) * 0.16;
  const dataReliability = clamp(totalGames / 10, 0.3, 1);
  const strength = rawStrength * dataReliability;

  let homeProbability: number;
  let drawProbability: number | null;
  let awayProbability: number;

  if (allowsDraw) {
    drawProbability = clamp(
      0.3 - Math.min(Math.abs(strength), 1.6) * 0.065,
      0.18,
      0.3,
    );
    const homeShare = sigmoid(strength);
    homeProbability = (1 - drawProbability) * homeShare;
    awayProbability = 1 - drawProbability - homeProbability;
  } else {
    drawProbability = null;
    homeProbability = sigmoid(strength);
    awayProbability = 1 - homeProbability;
  }

  const candidates = [
    { code: "1" as const, value: homeProbability, label: `Победа: ${home}` },
    ...(drawProbability === null
      ? []
      : [{ code: "X" as const, value: drawProbability, label: "Ничья" }]),
    { code: "2" as const, value: awayProbability, label: `Победа: ${away}` },
  ].sort((a, b) => b.value - a.value);

  const gap = candidates[0].value - (candidates[1]?.value ?? 0);
  const confidence =
    totalGames >= 8 && gap >= 0.13 ? ("Средняя" as const) : ("Низкая" as const);

  const combinedGoalLevel =
    homeForm.scoredAverage +
    homeForm.concededAverage +
    awayForm.scoredAverage +
    awayForm.concededAverage;
  const totalHint =
    sport === "football" && totalGames >= 6
      ? combinedGoalLevel / 2 >= 2.65
        ? "Склонность: ТБ 2.5"
        : "Склонность: ТМ 2.5"
      : null;
  const bttsHint =
    sport === "football" &&
    totalGames >= 6 &&
    homeForm.scoredAverage >= 1 &&
    awayForm.scoredAverage >= 1
      ? "Обе забьют: возможно"
      : null;

  const availableText =
    homeForm.played && awayForm.played
      ? `Учтены ${homeForm.played} последних матчей «${home}» и ${awayForm.played} матчей «${away}».`
      : `Данные доступны только по одной из команд (${totalGames} матчей), поэтому уверенность ограничена.`;

  return {
    probabilities: {
      home: roundProbability(homeProbability),
      draw:
        drawProbability === null ? null : roundProbability(drawProbability),
      away: roundProbability(awayProbability),
    },
    recommendedCode: candidates[0].code,
    recommendedLabel: candidates[0].label,
    confidence,
    note: `${availableText} Сравнены доля набранных очков, результативность и баланс забитых/пропущенных. Составы, травмы и букмекерские коэффициенты модель не видит.`,
    totalHint,
    bttsHint,
  };
}

function isValidDate(value: string | null): value is string {
  return Boolean(value && /^\d{4}-\d{2}-\d{2}$/.test(value));
}

function previousIsoDate(date: string) {
  const parsed = new Date(`${date}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() - 1);
  return parsed.toISOString().slice(0, 10);
}

function timestampUtc(value?: string) {
  if (!value) return null;
  return /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
}

function kyivDateFromTimestamp(value?: string) {
  const normalized = timestampUtc(value);
  if (!normalized) return null;
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return null;

  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Europe/Kyiv",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(parsed);
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function isStillRelevant(event: RawEvent) {
  const finalStatuses = new Set([
    "FT",
    "AET",
    "AP",
    "CANC",
    "ABD",
    "AWD",
    "Match Finished",
  ]);
  if (event.strStatus && finalStatuses.has(event.strStatus)) return false;

  const normalized = timestampUtc(event.strTimestamp);
  if (!normalized) return true;
  const eventTime = new Date(normalized).getTime();
  if (Number.isNaN(eventTime)) return true;

  // Keep future events and a small window for matches that may already be live.
  return eventTime >= Date.now() - 6 * 60 * 60 * 1000;
}

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const sportParam = requestUrl.searchParams.get("sport") ?? "football";
  const dateParam = requestUrl.searchParams.get("date");
  const isDemo = requestUrl.searchParams.get("demo") === "1";

  if (!(sportParam in SPORTS)) {
    return Response.json(
      { error: "Неизвестный вид спорта" },
      { status: 400 },
    );
  }

  if (!isValidDate(dateParam)) {
    return Response.json(
      { error: "Дата должна быть в формате ГГГГ-ММ-ДД" },
      { status: 400 },
    );
  }

  const sport = sportParam as SportId;
  const sportConfig = SPORTS[sport];

  if (isDemo) {
    return Response.json({
      matches: [
        {
          id: `demo-${sport}-${dateParam}`,
          sport,
          league: "Тестовая линия",
          country: "ДЕМО — только проверка интерфейса",
          home: "Команда Север",
          away: "Команда Юг",
          date: dateParam,
          time: "19:30:00",
          timestamp: `${dateParam}T19:30:00Z`,
          status: "NS",
          score: null,
          homeBadge: null,
          awayBadge: null,
          form: {
            home: {
              played: 5,
              wins: 3,
              draws: 1,
              losses: 1,
              scoredAverage: 1.8,
              concededAverage: 0.8,
              pointsRate: 0.67,
              recent: ["В", "В", "Н", "П", "В"],
            },
            away: {
              played: 5,
              wins: 2,
              draws: 1,
              losses: 2,
              scoredAverage: 1.2,
              concededAverage: 1.4,
              pointsRate: 0.47,
              recent: ["П", "В", "Н", "В", "П"],
            },
          },
          prediction: {
            probabilities: {
              home: sportConfig.allowsDraw ? 0.52 : 0.61,
              draw: sportConfig.allowsDraw ? 0.27 : null,
              away: sportConfig.allowsDraw ? 0.21 : 0.39,
            },
            recommendedCode: "1",
            recommendedLabel: "Победа: Команда Север",
            confidence: "Средняя",
            note: "Это демонстрационные данные для проверки кнопок и мобильной вёрстки. Они не относятся к реальному матчу и не предназначены для ставки.",
            totalHint: sport === "football" ? "Склонность: ТБ 2.5" : null,
            bttsHint: sport === "football" ? "Обе забьют: возможно" : null,
          },
        },
      ],
      updatedAt: new Date().toISOString(),
      source: "Демо",
      limitedCoverage: false,
    });
  }

  const cacheKey = `${sport}:${dateParam}`;
  const cached = responseCache.get(cacheKey);

  if (cached && cached.expiresAt > Date.now()) {
    return Response.json(cached.payload, {
      headers: { "Cache-Control": "public, max-age=120, s-maxage=900" },
    });
  }

  try {
    const scheduleDates = [previousIsoDate(dateParam), dateParam];
    const schedules = await Promise.all(
      scheduleDates.map((scheduleDate) =>
        fetchJson(
          "https://www.thesportsdb.com/api/v1/json/123/eventsday.php" +
            `?d=${encodeURIComponent(scheduleDate)}` +
            `&s=${encodeURIComponent(sportConfig.apiName)}`,
        ),
      ),
    );
    const uniqueEvents = new Map<string, RawEvent>();
    schedules
      .flatMap((schedule) => schedule.events ?? [])
      .forEach((event, index) => {
        const key =
          event.idEvent ||
          `${event.dateEvent}-${event.strHomeTeam}-${event.strAwayTeam}-${index}`;
        uniqueEvents.set(key, event);
      });
    const events = Array.from(uniqueEvents.values())
      .filter((event) => {
        const kyivDate = kyivDateFromTimestamp(event.strTimestamp);
        const matchesDate = kyivDate
          ? kyivDate === dateParam
          : event.dateEvent === dateParam;
        return matchesDate && isStillRelevant(event);
      })
      .slice(0, 6);
    const leagueKeys = Array.from(
      new Set(
        events
          .filter((event) => event.idLeague && event.strSeason)
          .map((event) => `${event.idLeague}::${event.strSeason}`),
      ),
    );
    const leagueHistoryEntries = await Promise.all(
      leagueKeys.map(async (key) => {
        const [leagueId, season] = key.split("::");
        return [key, await seasonEvents(leagueId, season)] as const;
      }),
    );
    const leagueHistory = new Map(leagueHistoryEntries);

    const matches = await Promise.all(
      events.map(async (event) => {
        const home = event.strHomeTeam || "Команда 1";
        const away = event.strAwayTeam || "Команда 2";
        const leagueKey =
          event.idLeague && event.strSeason
            ? `${event.idLeague}::${event.strSeason}`
            : "";
        const seasonHistory = leagueHistory.get(leagueKey) ?? [];
        const completedSeasonHistory = seasonHistory
          .filter((item) => {
            const hasScore =
              numberScore(item.intHomeScore) !== null &&
              numberScore(item.intAwayScore) !== null;
            return hasScore && (!item.dateEvent || item.dateEvent < dateParam);
          })
          .sort((a, b) =>
            (b.strTimestamp || b.dateEvent || "").localeCompare(
              a.strTimestamp || a.dateEvent || "",
            ),
          );
        let homeHistory = completedSeasonHistory.filter(
          (item) => item.strHomeTeam === home || item.strAwayTeam === home,
        );
        let awayHistory = completedSeasonHistory.filter(
          (item) => item.strHomeTeam === away || item.strAwayTeam === away,
        );

        if (homeHistory.length < 2 || awayHistory.length < 2) {
          const [homeRecent, awayRecent] = await Promise.all([
            homeHistory.length < 2 ? recentEvents(event.idHomeTeam) : [],
            awayHistory.length < 2 ? recentEvents(event.idAwayTeam) : [],
          ]);
          homeHistory = [...homeRecent, ...homeHistory];
          awayHistory = [...awayRecent, ...awayHistory];
        }
        const homeForm = buildForm(
          home,
          homeHistory,
          sportConfig.allowsDraw,
        );
        const awayForm = buildForm(
          away,
          awayHistory,
          sportConfig.allowsDraw,
        );

        const homeScore = numberScore(event.intHomeScore);
        const awayScore = numberScore(event.intAwayScore);

        return {
          id:
            event.idEvent ||
            `${dateParam}-${sport}-${encodeURIComponent(`${home}-${away}`)}`,
          sport,
          league: event.strLeague || "Турнир не указан",
          country: event.strCountry || null,
          home,
          away,
          date: event.dateEvent || dateParam,
          time: event.strTime || null,
          timestamp: timestampUtc(event.strTimestamp),
          status: event.strStatus || null,
          score:
            homeScore !== null && awayScore !== null
              ? `${homeScore}:${awayScore}`
              : null,
          homeBadge: event.strHomeTeamBadge || null,
          awayBadge: event.strAwayTeamBadge || null,
          form: { home: homeForm, away: awayForm },
          prediction: buildPrediction(
            home,
            away,
            homeForm,
            awayForm,
            sportConfig.allowsDraw,
            sport,
          ),
        };
      }),
    );

    const payload = {
      matches,
      updatedAt: new Date().toISOString(),
      source: "TheSportsDB",
      limitedCoverage: true,
      message:
        matches.length === 0
          ? "В открытом источнике нет событий для выбранной даты."
          : undefined,
    };

    responseCache.set(cacheKey, {
      expiresAt: Date.now() + 15 * 60 * 1000,
      payload,
    });

    return Response.json(payload, {
      headers: { "Cache-Control": "public, max-age=120, s-maxage=900" },
    });
  } catch (error) {
    return Response.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Не удалось получить расписание",
      },
      { status: 502 },
    );
  }
}

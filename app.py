from datetime import datetime
from zoneinfo import ZoneInfo
import os
import markdown
import pandas as pd
import requests
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(
    page_title="BI Champs - Tipovačka MS ve fotbale 2026",
    layout="centered",
    initial_sidebar_state="collapsed",
)

POINTS_EXACT = 3
POINTS_OUTCOME = 1
POINTS_OTHER = 0

MATCH_COLUMNS = ["MEX-JAR", "CZE-KOR", "CZE-JAR", "MEX-KOR", "CZE-MEX", "JAR-KOR"]

# Maximální uvažovaná odchylka (součet |Δhome|+|Δaway|) gólů od AI tipu,
# na kterou se normalizuje realismus/odvaha na škálu 0-100 %.
# Při této a vyšší odchylce je realismus 0 % a odvaha 100 %.
MAX_GOAL_DIFF = 6

TIPS = [
    {"Jméno": "ADAMBOREC", "MEX-JAR": "2:0", "CZE-KOR": "1:1", "CZE-JAR": "2:0", "MEX-KOR": "1:1", "CZE-MEX": "1:3", "JAR-KOR": "2:1"},
    {"Jméno": "PAVLÍNABOREC", "MEX-JAR": "3:0", "CZE-KOR": "1:1", "CZE-JAR": "1:0", "MEX-KOR": "2:0", "CZE-MEX": "0:3", "JAR-KOR": "1:2"},
    {"Jméno": "HELLOKITTY", "MEX-JAR": "2:2", "CZE-KOR": "3:0", "CZE-JAR": "1:0", "MEX-KOR": "2:1", "CZE-MEX": "1:1", "JAR-KOR": "1:3"},
    {"Jméno": "JINDROS1881", "MEX-JAR": "2:1", "CZE-KOR": "3:2", "CZE-JAR": "1:0", "MEX-KOR": "4:1", "CZE-MEX": "1:2", "JAR-KOR": "2:2"},
    {"Jméno": "KUBAMAN", "MEX-JAR": "4:1", "CZE-KOR": "1:1", "CZE-JAR": "2:1", "MEX-KOR": "3:0", "CZE-MEX": "0:2", "JAR-KOR": "1:2"},
    {"Jméno": "KRISTÝNABOREC", "MEX-JAR": "3:1", "CZE-KOR": "2:2", "CZE-JAR": "3:1", "MEX-KOR": "3:1", "CZE-MEX": "1:3", "JAR-KOR": "1:3"},
    {"Jméno": "DAN", "MEX-JAR": "2:0", "CZE-KOR": "1:2", "CZE-JAR": "1:1", "MEX-KOR": "1:1", "CZE-MEX": "2:2", "JAR-KOR": "0:2"},
    {"Jméno": "ALEX", "MEX-JAR": "3:1", "CZE-KOR": "2:2", "CZE-JAR": "2:1", "MEX-KOR": "2:0", "CZE-MEX": "1:3", "JAR-KOR": "2:1"},
    {"Jméno": "NASŤA", "MEX-JAR": "3:0", "CZE-KOR": "1:2", "CZE-JAR": "1:0", "MEX-KOR": "1:0", "CZE-MEX": "0:2", "JAR-KOR": "0:2"},
]

AI_TIP = {
    "Jméno": "🤖 AI tip",
    "MEX-JAR": "2:0",
    "CZE-KOR": "1:2",
    "CZE-JAR": "2:1",
    "MEX-KOR": "2:1",
    "CZE-MEX": "0:2",
    "JAR-KOR": "0:2",
}

TEAM_NAMES = {
    "MEX": ["mexico", "mexiko", "mex"],
    "JAR": ["south africa", "jihoafrická republika", "jihoafricka republika", "jar", "rsa"],
    "CZE": ["czech republic", "czechia", "česko", "cesko", "cze"],
    "KOR": ["south korea", "korea republic", "korea republic of", "jižní korea", "jizni korea", "kor"],
}

FOOTBALL_DATA_API_URL = "https://api.football-data.org/v4/competitions/WC/matches"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
PRAGUE_TZ = ZoneInfo("Europe/Prague")


def parse_score(score):
    if pd.isna(score):
        return None

    text = str(score).strip().replace(" ", "")
    if ":" not in text:
        return None

    left, right = text.split(":", 1)

    try:
        return int(left), int(right)
    except ValueError:
        return None


def outcome(score_tuple):
    if score_tuple is None:
        return None

    home, away = score_tuple

    if home > away:
        return 1
    if home < away:
        return -1

    return 0


def points_for_tip(tip, real_result):
    tip_score = parse_score(tip)
    real_score = parse_score(real_result)

    if tip_score is None or real_score is None:
        return 0

    if tip_score == real_score:
        return POINTS_EXACT

    if outcome(tip_score) == outcome(real_score):
        return POINTS_OUTCOME

    return POINTS_OTHER


def normalize_text(value):
    return str(value or "").strip().lower()


def team_matches(code, value):
    text = normalize_text(value)
    return any(alias in text for alias in TEAM_NAMES.get(code, [code.lower()]))


def get_football_data_token():
    try:
        token = st.secrets.get("FOOTBALL_DATA_API_TOKEN")
    except Exception:
        token = None

    return token or os.getenv("FOOTBALL_DATA_API_TOKEN")


def get_groq_api_key():
    try:
        key = st.secrets.get("GROQ_API_KEY")
    except Exception:
        key = None

    return key or os.getenv("GROQ_API_KEY")


def parse_utc_date(utc_date):
    if not utc_date:
        return None

    try:
        return datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_kickoff(kickoff):
    if kickoff is None:
        return None

    local_dt = kickoff.astimezone(PRAGUE_TZ)
    return f"{local_dt.day}.{local_dt.month}. {local_dt.strftime('%H:%M')}"


def get_next_match(match_data):
    """Vrátí (match_code, kickoff) nejbližšího budoucího zápasu, nebo None."""
    now = datetime.now(PRAGUE_TZ)
    upcoming = []
    for match_code, info in match_data.items():
        kickoff = info.get("kickoff")
        status = info.get("status")
        if kickoff and status not in ("FINISHED",) and kickoff.astimezone(PRAGUE_TZ) > now:
            upcoming.append((match_code, kickoff))
    if not upcoming:
        return None
    return min(upcoming, key=lambda x: x[1])


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_world_cup_matches():
    token = get_football_data_token()
    if not token:
        return {}

    try:
        response = requests.get(
            FOOTBALL_DATA_API_URL,
            headers={"X-Auth-Token": token},
            timeout=10,
        )
        response.raise_for_status()

        match_data = {}

        for match in response.json().get("matches", []):
            home_name = match.get("homeTeam", {}).get("name", "")
            away_name = match.get("awayTeam", {}).get("name", "")

            full_time = match.get("score", {}).get("fullTime", {})
            home_score = full_time.get("home")
            away_score = full_time.get("away")

            status = match.get("status")
            kickoff = parse_utc_date(match.get("utcDate"))

            for match_code in MATCH_COLUMNS:
                home_code, away_code = match_code.split("-")

                if team_matches(home_code, home_name) and team_matches(away_code, away_name):
                    reversed_sides = False
                elif team_matches(away_code, home_name) and team_matches(home_code, away_name):
                    reversed_sides = True
                else:
                    continue

                score = None
                if status == "FINISHED" and home_score is not None and away_score is not None:
                    score = f"{away_score}:{home_score}" if reversed_sides else f"{home_score}:{away_score}"

                match_data[match_code] = {
                    "score": score,
                    "kickoff": kickoff,
                    "status": status,
                }

        return match_data

    except Exception:
        return {}


def get_played_matches_count(results):
    return sum(1 for match in MATCH_COLUMNS if parse_score(results.get(match)) is not None)


def evaluate(df, results):
    df = df.copy()
    point_cols = []

    played_matches = get_played_matches_count(results)

    for match in MATCH_COLUMNS:
        col = f"Body {match}"
        df[col] = df[match].apply(lambda tip: points_for_tip(tip, results.get(match, "")))
        point_cols.append(col)

    df["Odehráno"] = played_matches
    df["Celkem"] = df[point_cols].sum(axis=1)

    df = df.sort_values(["Celkem", "Jméno"], ascending=[False, True])
    df.insert(0, "Pořadí", range(1, len(df) + 1))

    return df


def get_expected_result(match_code):
    return AI_TIP.get(match_code, "?:?")


def realism_score(tip, expected):
    """Realismus tipu vůči AI odhadu (0-100 %).

    Postaveno na jediné vzdálenostní metrice (součet absolutních rozdílů
    gólů domácích a hostů od AI tipu), normalizované na maximální
    uvažovanou odchylku MAX_GOAL_DIFF. Skóre klesá monotónně s rostoucí
    vzdáleností - žádné skoky ani nekonzistentní prahy.
    """
    tip_score = parse_score(tip)
    exp_score = parse_score(expected)

    if tip_score is None or exp_score is None:
        return None

    distance = abs(tip_score[0] - exp_score[0]) + abs(tip_score[1] - exp_score[1])
    return max(0, 100 - (distance / MAX_GOAL_DIFF) * 100)


def audacity_score(tip, expected):
    """Odvaha tipu (0-100 %) - přesný doplněk realismu (100 - realismus).

    Díky společnému základu (stejná vzdálenostní metrika) jsou realismus
    a odvaha matematicky komplementární: realismus + odvaha = 100 %.
    """
    realism = realism_score(tip, expected)
    if realism is None:
        return None
    return 100 - realism


def analyze_tips(df_tips, results=None):
    results = results or {}
    stats = {}

    for _, row in df_tips.iterrows():
        name = row["Jméno"]

        total_goals = 0
        cze_goals = 0
        cze_goals_against = 0
        realism_values = []
        audacity_values = []
        tipped_matches = 0
        played_tip_points = []  # (match, points, tip) jen pro odehrané zápasy

        for match in MATCH_COLUMNS:
            tip_score = parse_score(row[match])
            if tip_score is None:
                continue

            tipped_matches += 1
            total_goals += tip_score[0] + tip_score[1]

            if "CZE" in match:
                home_code, away_code = match.split("-")

                if home_code == "CZE":
                    cze_goals += tip_score[0]
                    cze_goals_against += tip_score[1]
                else:
                    cze_goals += tip_score[1]
                    cze_goals_against += tip_score[0]

            expected = get_expected_result(match)

            realism = realism_score(row[match], expected)
            if realism is not None:
                realism_values.append(realism)
                audacity_values.append(100 - realism)

            real_result = results.get(match)
            if parse_score(real_result) is not None:
                pts = points_for_tip(row[match], real_result)
                played_tip_points.append((match, pts, row[match]))

        best_match = max(played_tip_points, key=lambda t: t[1]) if played_tip_points else None
        worst_match = min(played_tip_points, key=lambda t: t[1]) if played_tip_points else None

        stats[name] = {
            "total_goals": total_goals,
            "avg_goals": total_goals / len(MATCH_COLUMNS),
            "cze_balance": cze_goals - cze_goals_against,
            # Průměr přes skutečně tipnuté zápasy (ne přes všechny MATCH_COLUMNS),
            # aby hráč s méně tipy nebyl zkreslen chybějícími hodnotami.
            "avg_realism": sum(realism_values) / len(realism_values) if realism_values else 0,
            "avg_audacity": sum(audacity_values) / len(audacity_values) if audacity_values else 0,
            # Nejlepší/nejhorší tip jen mezi odehranými zápasy (kde je znám výsledek).
            "best_match": best_match,
            "worst_match": worst_match,
        }

    return stats


def analyze_match_consensus(df_tips, results):
    """Pro každý odehraný zápas spočítá shodu/rozptyl tipů skupiny.

    Vrací pro každý zápas: nejčastěji tipovaný výsledek (a kolik hráčů na
    něm souhlasilo), počet různých tipovaných výsledků (rozptyl) a kolik
    hráčů reálně trefilo přesné skóre / správný výsledek (výhra/remíza/
    prohra) - to je nutné počítat explicitně přes points_for_tip, ne
    odvozovat z "nejčastějšího tipu skupiny", protože nejčastější tip
    nemusí být ten správný, i když ho někteří hráči trefili.
    """
    from collections import Counter

    consensus = {}

    for match in MATCH_COLUMNS:
        real_result = results.get(match)
        if parse_score(real_result) is None:
            continue

        tip_values = [t for t in df_tips[match].tolist() if parse_score(t) is not None]
        if not tip_values:
            continue

        counts = Counter(tip_values)
        most_common_tip, most_common_count = counts.most_common(1)[0]

        exact_hits = sum(1 for t in tip_values if points_for_tip(t, real_result) == POINTS_EXACT)
        outcome_only_hits = sum(1 for t in tip_values if points_for_tip(t, real_result) == POINTS_OUTCOME)
        # Celkem kolik hráčů uhádlo aspoň správný výsledek (výhra/remíza/prohra) -
        # zahrnuje i ty, kdo trefili rovnou přesné skóre (přesné skóre je
        # podmnožina "správného výsledku"). Bez tohoto součtu si lze mylně
        # myslet, že "outcome_hits=0" znamená "nikdo neuhádl výsledek",
        # i když ve skutečnosti pár hráčů uhádlo výsledek ROVNOU přesně.
        outcome_total_hits = exact_hits + outcome_only_hits

        consensus[match] = {
            "real_result": real_result,
            "most_common_tip": most_common_tip,
            "most_common_count": most_common_count,
            "total_tips": len(tip_values),
            "unique_tips": len(counts),
            # exact_hits: trefili přesné skóre.
            # outcome_only_hits: trefili JEN výsledek (ne přesné skóre) - menšina.
            # outcome_total_hits: trefili aspoň výsledek celkem (= exact_hits + outcome_only_hits).
            "exact_hits": exact_hits,
            "outcome_only_hits": outcome_only_hits,
            "outcome_total_hits": outcome_total_hits,
        }

    return consensus


def get_ai_ranking(evaluated_df, results):
    """Spočítá, kolik bodů by AI tip získal, a na jaké by se umístil pozici
    mezi reálnými hráči (1 = nejlepší)."""
    ai_points = sum(points_for_tip(AI_TIP[m], results.get(m, "")) for m in MATCH_COLUMNS)
    better_players = (evaluated_df["Celkem"] > ai_points).sum()
    ai_rank = int(better_players) + 1

    return {
        "points": ai_points,
        "rank": ai_rank,
        "total_players": len(evaluated_df) + 1,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def generate_ai_insights_cached(standings_text, stats_summary, consensus_summary, ai_rank_summary, played_matches, results_cache_key):
    """Cached wrapper – regeneruje se jen pokud se změní výsledky (results_cache_key)."""
    api_key = get_groq_api_key()

    if not api_key:
        return None, "❌ Groq API klíč není nastaven. Přidej GROQ_API_KEY do .streamlit/secrets.toml"

    prompt = f"""
Jsi expert na fotbalovou analytiku a zábavný data storytelling.

Analyzuj firemní tipovací soutěž k MS ve fotbale 2026. Tipéři před turnajem
odhadovali skóre jednotlivých zápasů. Jako referenční "odborný" odhad slouží
🤖 AI tip (vygenerovaný předem AI modelem) - vůči němu se počítá realismus.

Aktuální tabulka (pořadí podle bodů za uhodnuté výsledky/skóre):
{standings_text}

Počet odehraných zápasů: {played_matches}/{len(MATCH_COLUMNS)}

Statistiky a nejlepší/nejhorší tip každého hráče (za odehrané zápasy):
{stats_summary}

Shoda/rozptyl mezi tipéry u jednotlivých odehraných zápasů:
{consensus_summary}

Jak by si vedl samotný AI tip:
{ai_rank_summary}

Vysvětlení metrik, abys jim správně rozuměl:
- "realismus %" = jak blízko byly tipy hráče k 🤖 AI tipu (100 % = identické s AI, 0 % = max. odchylka)
- "bilance ČR" = tipované góly ČR minus góly soupeřů v zápasech České republiky (kladné = věří ČR, záporné = skeptik)
- "nejlepší/nejhorší tip" = zápas, kde hráč získal nejvíc/nejméně bodů (podle skutečného výsledku)
- DŮLEŽITÉ - u každého zápasu jsou tři čísla o tom, kdo "uhodl":
  1) "CELKEM trefilo aspoň správný výsledek" = kolik hráčů celkem uhádlo výhru/remízu/prohru správně (toto je hlavní číslo pro "kolik lidí to uhodlo")
  2) "z toho přesné skóre" = z těch hráčů z bodu 1, kolik trefilo i přesné skóre (jsou součástí čísla z bodu 1, ne navíc)
  3) "JEN výsledek bez přesného skóre" = ti, kdo uhodli výhru/remízu/prohru, ale ne přesné skóre
  Pokud je "CELKEM trefilo aspoň správný výsledek" 0, znamená to, že NIKDO neuhodl ani výsledek. Pokud je tam třeba 2, znamená to, že 2 lidé uhodli výsledek (ať už přesně nebo jen typ výsledku) - NIKDY netvrď, že "nikdo neuhodl", pokud je toto číslo větší než 0.
- "nejčastější tip skupiny" popisuje jen to, na čem se nejvíc lidí shodlo (může, ale nemusí být správně) - slouží pro pozorování o shodě/rozptylu názorů, NE pro určení, kdo uhodl - k tomu používej výhradně čísla z předchozího bodu

Napiš česky krátký, výstižný AI insight, který popíše, JAK SI TIPÉŘI ZATÍM VEDOU
a CO JE NA KAŽDÉM Z NICH ZAJÍMAVÉ/ODLIŠNÉ - ne jen suchý výčet čísel, ale srozumitelný
příběh nad daty. Hledej konkrétní, překvapivá pozorování - typicky:
- kdo měl největší štěstí/neštěstí (např. vysoké skóre i přes nízký realismus, nebo naopak)
- u zápasů: kolik lidí celkem uhodlo (podle "CELKEM trefilo aspoň správný výsledek", NE podle nejčastějšího tipu) a kde se skupina nejvíc shodla nebo nejvíc rozdělila
- jak by si vedla AI vůči lidem - je nad nimi, nebo ji lidé porážejí?
- kdo se nejvíc/nejméně trefil do svého nejlepšího zápasu

Struktura:
- 1 krátký odstavec o aktuální tabulce - kdo vede, jak je to vyrovnané/nevyrovnané
- 3 odrážky k top 3 hráčům - co konkrétně dělají dobře a proč jsou nahoře (klidně zmiň jejich nejlepší tip)
- 1 odstavec/odrážka o tom, jak si vede AI tip vůči lidem (z dat o pořadí AI)
- 1 odstavec/odrážka o zápase(ech), kde se skupina nejvíc shodla nebo nejvíc rozdělila a jak to vyšlo
- ke každému dalšímu tipérovi 1 krátká věta s konkrétní zajímavostí podloženou číslem ze statistik (žádné obecné fráze)
- výstup musí být přesný a držet se POUZE poskytnutých dat (žádné vymyšlené detaily o zápasech ani hráčích)
- napiš to tak, aby tomu rozumělo i 10leté dítě - krátké věty, žádný analytický žargon
- tón: vtipný, sportovní, přátelský
- používej emoji
- na závěr 1 vtip o datech nebo datové analytice
"""

    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4000,
    }

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"], None

    except Exception as e:
        return None, f"❌ AI insight se nepodařilo vygenerovat: {e}"


def generate_ai_insights(evaluated_df, stats_dict, played_matches, results):
    api_key = get_groq_api_key()

    if not api_key:
        st.error("❌ Groq API klíč není nastaven. Přidej GROQ_API_KEY do .streamlit/secrets.toml")
        return None

    standings_text = evaluated_df[["Pořadí", "Jméno", "Odehráno", "Celkem"]].to_string(index=False)

    stats_summary = ""
    for name, stat in list(stats_dict.items())[:9]:
        best = stat.get("best_match")
        worst = stat.get("worst_match")
        best_str = f"nejlepší tip {best[0]} ({best[2]}, {best[1]} b.)" if best else "bez odehraných zápasů"
        worst_str = f"nejhorší tip {worst[0]} ({worst[2]}, {worst[1]} b.)" if worst else ""

        stats_summary += (
            f"- {name}: {stat['avg_goals']:.1f} gólů/zápas, "
            f"realismus {stat['avg_realism']:.0f} %, "
            f"bilance ČR {stat['cze_balance']:+d}, "
            f"{best_str}"
            + (f", {worst_str}" if worst_str and worst != best else "")
            + "\n"
        )

    consensus = analyze_match_consensus(df, results)
    consensus_summary = ""
    for match, c in consensus.items():
        shoda_pct = round(100 * c["most_common_count"] / c["total_tips"])
        consensus_summary += (
            f"- {match}: skutečný výsledek {c['real_result']} | "
            f"CELKEM trefilo aspoň správný výsledek (výhra/remíza/prohra): {c['outcome_total_hits']}/{c['total_tips']} hráčů, "
            f"z toho přesné skóre trefilo {c['exact_hits']}/{c['total_tips']} hráčů "
            f"a JEN výsledek bez přesného skóre trefilo {c['outcome_only_hits']}/{c['total_tips']} hráčů | "
            f"nejčastější tip skupiny byl {c['most_common_tip']} ({c['most_common_count']}/{c['total_tips']} hráčů, {shoda_pct} %), "
            f"celkem {c['unique_tips']} různých tipů\n"
        )

    ai_rank = get_ai_ranking(evaluated_df, results)
    ai_rank_summary = (
        f"🤖 AI tip má zatím {ai_rank['points']} bodů, což by stačilo na "
        f"{ai_rank['rank']}. místo z {ai_rank['total_players']} (včetně AI)."
    )

    # Cache key složen z výsledků – při novém výsledku se insight přegeneruje
    results_cache_key = "|".join(
        f"{m}={results.get(m, '')}" for m in MATCH_COLUMNS
    )

    ai_text, error = generate_ai_insights_cached(
        standings_text, stats_summary, consensus_summary, ai_rank_summary,
        played_matches, results_cache_key,
    )

    if error:
        st.error(error)
        return None

    return ai_text




def render_results_table(df, results):
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    row_classes = {1: "top1", 2: "top2", 3: "top3"}

    header_cells = '<th class="rank-col">Pořadí</th><th class="name-col">Jméno</th>'
    header_cells += "".join(f"<th>{match}</th>" for match in MATCH_COLUMNS)
    header_cells += '<th>Odehráno</th><th class="total-col">Celkem</th>'

    rows_html = []

    for _, row in df.iterrows():
        place = int(row["Pořadí"])
        row_class = row_classes.get(place, "")
        medal = medals.get(place, "")

        cells = f'<td class="rank-cell">{medal} {place}</td>'
        cells += f'<td class="name-cell">{row["Jméno"]}</td>'

        for match in MATCH_COLUMNS:
            tip_value = row[match]
            real_result = results.get(match, "")

            if parse_score(real_result) is None or parse_score(tip_value) is None:
                css_class = "score-pending"
            else:
                points = points_for_tip(tip_value, real_result)
                if points == POINTS_EXACT:
                    css_class = "score-exact"
                elif points == POINTS_OUTCOME:
                    css_class = "score-outcome"
                else:
                    css_class = "score-miss"

            cells += f'<td class="score-cell {css_class}">{tip_value}</td>'

        cells += f'<td class="played-cell">{int(row["Odehráno"])}/{len(MATCH_COLUMNS)}</td>'
        cells += f'<td class="total-cell">{int(row["Celkem"])}</td>'

        rows_html.append(f'<tr class="{row_class}">{cells}</tr>')

    # AI tip – fixně na konci, nezapočítává se do pořadí
    ai_points = sum(points_for_tip(AI_TIP[m], results.get(m, "")) for m in MATCH_COLUMNS)
    ai_played = sum(1 for m in MATCH_COLUMNS if parse_score(results.get(m)) is not None)
    ai_cells = '<td class="rank-cell">—</td>'
    ai_cells += f'<td class="name-cell">{AI_TIP["Jméno"]}</td>'
    for match in MATCH_COLUMNS:
        tip_value = AI_TIP[match]
        real_result = results.get(match, "")
        if parse_score(real_result) is None:
            css_class = "score-pending"
        else:
            pts = points_for_tip(tip_value, real_result)
            if pts == POINTS_EXACT:
                css_class = "score-exact"
            elif pts == POINTS_OUTCOME:
                css_class = "score-outcome"
            else:
                css_class = "score-miss"
        ai_cells += f'<td class="score-cell {css_class}">{tip_value}</td>'
    ai_cells += f'<td class="played-cell">{ai_played}/{len(MATCH_COLUMNS)}</td>'
    ai_cells += f'<td class="total-cell">{ai_points}</td>'
    rows_html.append(f'<tr class="ai-row">{ai_cells}</tr>')

    return f"""
    <div class="table-wrapper">
        <table class="results-table">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{"".join(rows_html)}</tbody>
        </table>
    </div>
    """


def render_charts(evaluated_df, stats_dict, results):
    """Vykreslí grafy bodů, realismu a odvahy hráčů."""
    played = get_played_matches_count(results)
    if played == 0:
        return

    names = evaluated_df["Jméno"].tolist()
    points = evaluated_df["Celkem"].tolist()
    colors = []
    for i, _ in enumerate(names):
        if i == 0:
            colors.append("#FFD700")
        elif i == 1:
            colors.append("#C0C0C0")
        elif i == 2:
            colors.append("#CD7F32")
        else:
            colors.append("#1f77b4")

    # Graf 1 – Body hráčů.
    fig_points = go.Figure(go.Bar(
        x=names,
        y=points,
        marker_color=colors,
        text=points,
        textposition="outside",
        cliponaxis=False,
    ))
    fig_points.update_layout(
        title=dict(text="📊 Body hráčů", font=dict(size=16)),
        yaxis=dict(title="Body", gridcolor="rgba(128,128,128,0.15)"),
        xaxis=dict(tickangle=-30),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=50, b=60, l=40, r=20),
        height=320,
    )

    # Graf 2 – Realismus vs Průměr gólů.
    # Pozn.: odvaha = 100 % - realismus (přesný doplněk), proto by graf
    # realismus x odvaha vždy degeneroval na jednu přímku a nenesl by
    # žádnou novou informaci. Místo toho dvě nezávislé osy: realismus
    # (jak blízko AI tipu) a průměr gólů (defenzivní vs. útočný styl tipování).
    realism_vals = [stats_dict[n]["avg_realism"] for n in names if n in stats_dict]
    avg_goals_vals = [stats_dict[n]["avg_goals"] for n in names if n in stats_dict]
    chart_names = [n for n in names if n in stats_dict]

    fig_scatter = go.Figure(go.Scatter(
        x=realism_vals,
        y=avg_goals_vals,
        mode="markers+text",
        text=chart_names,
        textposition="top center",
        marker=dict(
            size=14,
            color=points[:len(chart_names)],
            colorscale="Blues",
            showscale=True,
            colorbar=dict(title="Body"),
            line=dict(width=1, color="#1f77b4"),
        ),
        name="Tipéři",
        showlegend=False,
    ))

    # AI tip jako referenční bod – realismus je z definice 100 %
    # (AI tip = vlastní reference, od které se realismus počítá).
    ai_goals = [parse_score(AI_TIP[m]) for m in MATCH_COLUMNS]
    ai_avg_goals = sum(h + a for h, a in ai_goals) / len(MATCH_COLUMNS)

    fig_scatter.add_trace(go.Scatter(
        x=[100],
        y=[ai_avg_goals],
        mode="markers+text",
        text=["🤖 AI tip"],
        textposition="top center",
        marker=dict(
            size=18,
            color="#9c27b0",
            symbol="star",
            line=dict(width=1.5, color="#6a1b7a"),
        ),
        name="AI tip",
        showlegend=False,
    ))

    fig_scatter.update_layout(
        title=dict(text="🎯 Realismus vs Průměr gólů", font=dict(size=16)),
        xaxis=dict(title="Realismus (%)", gridcolor="rgba(128,128,128,0.15)", range=[-5, 105]),
        yaxis=dict(title="Průměr gólů / zápas", gridcolor="rgba(128,128,128,0.15)"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=50, b=60, l=60, r=20),
        height=360,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(fig_points, use_container_width=True)
        st.caption(
            "Kolik bodů má každý tipér celkem. "
            "Body získáváš za správně tipnutý výsledek nebo přesné skóre. "
            "Čím vyšší sloupec, tím lépe tipuješ. 🥇🥈🥉 = top 3."
        )
    with col2:
        st.plotly_chart(fig_scatter, use_container_width=True)
        st.caption(
            "Každý bod = jeden tipér. "
            "**Vodorovná osa (realismus):** jak moc se tvoje tipy shodují s 🤖 AI tipem – "
            "čím víc vpravo, tím konzervativněji tipuješ (vlevo = odvážněji, netradičně). "
            "**Svislá osa (průměr gólů):** kolik gólů průměrně čekáš v zápase – "
            "čím výš, tím otevřenější, gólovější zápasy tipuješ. "
            "Barva bodu = počet bodů (tmavší = více bodů). "
            "Fialová hvězda = 🤖 AI tip (referenční bod, realismus 100 %)."
        )


# ---------------- UI ----------------

df = pd.DataFrame(TIPS)

st.markdown("""
<style>
.match-card {
    background: var(--secondary-background-color);
    color: var(--text-color);
    border-radius: 8px;
    padding: 16px;
    margin: 8px 0;
    border: 1px solid rgba(128, 128, 128, 0.15);
    border-left: 4px solid #1f77b4;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.match-card-title {
    margin: 0;
    font-size: 1.1em;
    font-weight: 600;
}

.match-card-score {
    margin: 10px 0 0 0;
    font-size: 1.5em;
    font-weight: bold;
    color: #1f77b4;
}

.match-card-kickoff {
    margin: 4px 0 0 0;
    font-size: 0.85em;
    opacity: 0.65;
}

.table-wrapper {
    border-radius: 12px;
    overflow-x: auto;
    overflow-y: hidden;
    box-shadow: 0 4px 16px rgba(0,0,0,0.15);
    margin-bottom: 10px;
    border: 1px solid rgba(128, 128, 128, 0.15);
    -webkit-overflow-scrolling: touch;
}

.results-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--secondary-background-color);
    color: var(--text-color);
    font-size: 0.95em;
}

.results-table thead th {
    background: #1f77b4;
    color: white;
    padding: 12px 10px;
    text-align: center;
    font-weight: 700;
}

.results-table tbody td {
    padding: 10px;
    text-align: center;
    border-bottom: 1px solid rgba(128, 128, 128, 0.15);
}

.results-table .name-cell {
    text-align: left;
    font-weight: 600;
    white-space: nowrap;
}

.results-table .rank-cell,
.results-table .played-cell,
.results-table .total-cell {
    font-weight: 800;
    white-space: nowrap;
}

.results-table .total-cell {
    color: #1f77b4;
    font-size: 1.15em;
}

.results-table tbody tr.top1 { background-color: rgba(255, 215, 0, 0.18) !important; }
.results-table tbody tr.top2 { background-color: rgba(192, 192, 192, 0.2) !important; }
.results-table tbody tr.top3 { background-color: rgba(205, 127, 50, 0.18) !important; }
.results-table tbody tr.ai-row { background-color: rgba(156, 39, 176, 0.06) !important; border-top: 2px dashed rgba(156, 39, 176, 0.35) !important; }
.results-table tbody tr.ai-row td { opacity: 0.82; font-style: italic; }
.results-table tbody tr.ai-row .name-cell { color: #9c27b0; font-style: normal; font-weight: 700; }
.results-table tbody tr.ai-row .rank-cell { color: #9c27b0; font-weight: 700; }
.results-table tbody tr.ai-row .total-cell { color: #9c27b0; }

.score-exact {
    background-color: #f0faf0;
    color: #2e7d32;
}

.score-outcome {
    background-color: #fffbe8;
    color: #b8860b;
}

.score-miss {
    background-color: #fdf3f2;
    color: #c0392b;
}

.score-pending {
    background-color: rgba(128, 128, 128, 0.15);
    opacity: 0.6;
}

.countdown-card {
    background: var(--secondary-background-color);
    border-radius: 8px;
    padding: 14px 20px;
    margin: 8px 0;
    border: 1px solid rgba(128, 128, 128, 0.15);
    border-left: 4px solid #e07b00;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    text-align: center;
}

.countdown-label {
    margin: 0 0 6px 0;
    font-size: 0.95em;
    opacity: 0.75;
}

.countdown-timer {
    font-size: 2em;
    font-weight: 800;
    color: #e07b00;
    letter-spacing: 2px;
    font-variant-numeric: tabular-nums;
    margin: 0;
}

.countdown-match {
    margin: 4px 0 0 0;
    font-size: 1.05em;
    font-weight: 600;
}

.table-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    justify-content: center;
    margin: 10px 0 20px 0;
    font-size: 0.9em;
    opacity: 0.75;
}

.legend-swatch {
    display: inline-block;
    width: 14px;
    height: 14px;
    border-radius: 3px;
    margin-right: 6px;
    vertical-align: middle;
    border: 1px solid rgba(128, 128, 128, 0.25);
}

.section-header {
    margin: 2rem 0 1rem 0;
    padding: 10px 16px;
    background: linear-gradient(90deg, rgba(31,119,180,0.12), rgba(31,119,180,0.0));
    border-left: 4px solid #1f77b4;
    border-radius: 0 6px 6px 0;
    font-size: 1.15em;
    font-weight: 700;
    letter-spacing: 0.01em;
}

            @media (max-width: 768px) {

  .block-container {
    padding-left: 0.75rem;
    padding-right: 0.75rem;
    padding-top: 1rem;
  }

  h1 {
    font-size: 1.7rem !important;
    line-height: 1.2 !important;
  }

  h2,
  h3 {
    font-size: 1.25rem !important;
  }

  .match-card {
    padding: 12px;
    margin: 8px 0;
  }

  .match-card-title {
    font-size: 1em;
  }

  .match-card-score {
    font-size: 1.35em;
  }

  .results-table {
    min-width: 760px;
    font-size: 0.85em;
  }

  .results-table thead th {
    padding: 9px 7px;
  }

  .results-table tbody td {
    padding: 8px 7px;
  }

  .table-legend {
    justify-content: flex-start;
    gap: 10px;
    font-size: 0.85em;
  }

  div[data-testid="column"] {
    width: 100% !important;
    flex: 1 1 100% !important;
  }

  div[data-testid="stHorizontalBlock"] {
    flex-wrap: wrap;
  }
}            


</style>
""", unsafe_allow_html=True)

st.title("⚽ BI Champs - Tipovačka MS ve fotbale 2026")

st.markdown(f"""
<div class="match-card" style="border-left: 4px solid #2ca02c; text-align: center;">
    <p style="margin: 0; font-size: 1.05em;">
        <strong>📋 Bodování tipů:</strong>
        &nbsp;&nbsp; 🎯 přesný výsledek = <strong>{POINTS_EXACT} body</strong>
        &nbsp;|&nbsp; ✅ správný tip = <strong>{POINTS_OUTCOME} bod</strong>
        &nbsp;|&nbsp; ❌ netrefený tip = <strong>{POINTS_OTHER} bodů</strong>
    </p>
</div>
""", unsafe_allow_html=True)

match_data = fetch_world_cup_matches()
api_results = {
    match: info["score"]
    for match, info in match_data.items()
    if info.get("score")
}

match_emojis = {
    "MEX-JAR": "🇲🇽 vs 🇿🇦",
    "CZE-KOR": "🇨🇿 vs 🇰🇷",
    "CZE-JAR": "🇨🇿 vs 🇿🇦",
    "MEX-KOR": "🇲🇽 vs 🇰🇷",
    "CZE-MEX": "🇨🇿 vs 🇲🇽",
    "JAR-KOR": "🇿🇦 vs 🇰🇷",
}

# Odpočítávání do nejbližšího zápasu – používá components.html() pro funkční JS.
next_match = get_next_match(match_data)
if next_match:
    next_code, next_kickoff = next_match
    next_local = next_kickoff.astimezone(PRAGUE_TZ)
    next_label = match_emojis.get(next_code, next_code)
    next_date_str = f"{next_local.day}.{next_local.month}. {next_local.strftime('%H:%M')}"
    kickoff_ts = int(next_kickoff.timestamp())
    components.html(f"""
<style>
  body {{ margin: 0; font-family: sans-serif; }}
  .cd-card {{
    background: linear-gradient(135deg, #fff8f0, #fff3e0);
    border-radius: 10px;
    padding: 14px 20px 12px;
    border-left: 4px solid #e07b00;
    box-shadow: 0 2px 8px rgba(224,123,0,0.12);
    text-align: center;
  }}
  .cd-label {{ margin: 0 0 4px 0; font-size: 0.9em; color: #888; }}
  .cd-timer {{
    font-size: 2.2em;
    font-weight: 900;
    color: #e07b00;
    letter-spacing: 3px;
    font-variant-numeric: tabular-nums;
    margin: 0;
    font-family: monospace;
  }}
  .cd-match {{ margin: 6px 0 0 0; font-size: 1.05em; font-weight: 600; color: #333; }}
</style>
<div class="cd-card">
  <p class="cd-label">⏱️ Další zápas za</p>
  <p class="cd-timer" id="cd">--:--:--</p>
  <p class="cd-match">{next_label} &nbsp;·&nbsp; {next_date_str}</p>
</div>
<script>
  var target = {kickoff_ts} * 1000;
  function update() {{
    var diff = Math.max(0, target - Date.now());
    var h = Math.floor(diff / 3600000);
    var m = Math.floor((diff % 3600000) / 60000);
    var s = Math.floor((diff % 60000) / 1000);
    var el = document.getElementById('cd');
    if (!el) return;
    if (diff === 0) {{
      el.textContent = '🔴 PRÁVĚ TEĎ';
    }} else if (h >= 24) {{
      var d = Math.floor(h / 24);
      var rh = h % 24;
      el.textContent = d + 'd ' + String(rh).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
    }} else {{
      el.textContent = String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
    }}
  }}
  update();
  setInterval(update, 1000);
</script>
""", height=110)

results = api_results.copy()

# Výsledky zápasů – sekce pro ruční zadání (musí proběhnout PŘED tabulkou,
# aby results obsahovalo i manuálně zadané skóre).
if not api_results:
    st.markdown('<div class="section-header">🎯 Výsledky zápasů</div>', unsafe_allow_html=True)
    st.caption("Vyplň výsledky ručně. Nezaplněné zápasy se nebudou vyhodnocovat.")

    cols_input = st.columns(3)
    for i, match in enumerate(MATCH_COLUMNS):
        with cols_input[i % 3]:
            kickoff_str = format_kickoff(match_data.get(match, {}).get("kickoff"))
            kickoff_html = f'<p class="match-card-kickoff">🕒 {kickoff_str}</p>' if kickoff_str else ""
            st.markdown(f"""
            <div class="match-card">
                <p class="match-card-title">{match_emojis.get(match, match)}</p>
                {kickoff_html}
            </div>
            """, unsafe_allow_html=True)
            results[match] = st.text_input(
                f"Skóre {match}",
                value="",
                placeholder="2:1",
                label_visibility="collapsed",
            )

# Výsledky zápasů – karty (zobrazí se jen když jsou API výsledky).
if api_results:
    st.markdown('<div class="section-header">✅ Výsledky zápasů</div>', unsafe_allow_html=True)
    st.caption("Výsledky se automaticky stahují z football-data.org. Časy zápasů jsou ve středoevropském čase.")

    cols = st.columns(3)
    for i, match in enumerate(MATCH_COLUMNS):
        with cols[i % 3]:
            kickoff_str = format_kickoff(match_data.get(match, {}).get("kickoff"))
            kickoff_html = f'<p class="match-card-kickoff">🕒 {kickoff_str}</p>' if kickoff_str else ""
            st.markdown(f"""
            <div class="match-card">
                <p class="match-card-title">{match_emojis.get(match, match)}</p>
                <p class="match-card-score">{results.get(match, "?:?")}</p>
                {kickoff_html}
            </div>
            """, unsafe_allow_html=True)

# Tabulka Pořadí.
preview_evaluated = evaluate(df, results)
stats = analyze_tips(df, results)
played_matches = get_played_matches_count(results)

st.markdown('<div class="section-header">🏆 Pořadí</div>', unsafe_allow_html=True)
st.markdown(render_results_table(preview_evaluated, results), unsafe_allow_html=True)

st.markdown("""
<div class="table-legend">
    <span><span class="legend-swatch" style="background-color: #f0faf0;"></span>Přesný tip</span>
    <span><span class="legend-swatch" style="background-color: #fffbe8;"></span>Správný výsledek</span>
    <span><span class="legend-swatch" style="background-color: #fdf3f2;"></span>Netrefený tip</span>
    <span><span class="legend-swatch" style="background-color: #f1f1f1;"></span>Zápas ještě neproběhl</span>
</div>
""", unsafe_allow_html=True)


# Grafy statistik.
st.markdown('<div class="section-header">📈 Statistiky</div>', unsafe_allow_html=True)
render_charts(preview_evaluated, stats, results)


# AI Insight – za tabulkou Pořadí, generuje se automaticky dle výsledků.
st.markdown('<div class="section-header">🤖 AI Insight</div>', unsafe_allow_html=True)

if played_matches == 0:
    st.info("AI insight se zobrazí automaticky, jakmile bude odehraný alespoň jeden zápas.")
else:
    with st.spinner("🧠 Groq analyzuje výsledky..."):
        ai_text = generate_ai_insights(preview_evaluated, stats, played_matches, results)

    if ai_text:
        html = markdown.markdown(ai_text)
        st.markdown(
            f"""
            <div class="match-card" style="border-left: 4px solid #9c27b0;">
                {html}
            </div>
            """,
            unsafe_allow_html=True,
        )


with st.expander("📖 Jak to funguje? (vysvětlivky)"):
    st.markdown(f"""
**🎯 Bodování**
— Přesné skóre = **{POINTS_EXACT} body** &nbsp;|&nbsp; Správný výsledek (výhra/remíza/prohra) = **{POINTS_OUTCOME} bod** &nbsp;|&nbsp; Špatný tip = **{POINTS_OTHER} bodů**

**📐 Realismus** — Jak moc se tvoje tipy blíží 🤖 AI tipu (odbornému odhadu výsledků). 100 % = tipuješ přesně podle AI, nízké % = tipuješ netradiční výsledky.

**💥 Odvaha** — Doplněk realismu (100 % − realismus). Jak moc se tipy liší od AI tipu. Čím vyšší číslo, tím odvážnější a netradičnější tipy. Nízká odvaha = konzervativní tipér.

**⚽ Průměr gólů** — Kolik gólů průměrně čekáš v jednom zápase. Vyšší číslo = tiluješ otevřené, gólovější zápasy.

**🇨🇿 Bilance ČR** — Tipované góly ČR minus góly soupeřů. Kladné číslo = věříš českému týmu, záporné = jsi skeptik.

**🤖 AI Insight** — Automatický komentář od AI na základě aktuálního pořadí a statistik. Jen pro zábavu, na body nemá vliv.
""")
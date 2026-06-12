from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
import requests
import os

st.set_page_config(page_title="BI Tým MS Tipovačka", layout="wide", initial_sidebar_state="collapsed")

POINTS_EXACT = 3
POINTS_OUTCOME = 1
POINTS_OTHER = 0

MATCH_COLUMNS = ["MEX-JAR", "CZE-KOR", "CZE-JAR", "MEX-KOR", "CZE-MEX", "JAR-KOR"]

# Tipy jsou rovnou zapsané ve skriptu, není potřeba nahrávat XLSX.
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

TEAM_NAMES = {
    "MEX": ["mexico", "mexiko", "mex"],
    "JAR": ["south africa", "jihoafrická republika", "jihoafricka republika", "jar", "rsa"],
    "CZE": ["czech republic", "czechia", "česko", "cesko", "cze"],
    "KOR": ["south korea", "korea republic", "korea republic of", "jižní korea", "jizni korea", "kor"],
}


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


FOOTBALL_DATA_API_URL = "https://api.football-data.org/v4/competitions/WC/matches"
PRAGUE_TZ = ZoneInfo("Europe/Prague")


def get_football_data_token():
    """Read the football-data.org API token from Streamlit secrets or env var."""
    token = None
    try:
        token = st.secrets.get("FOOTBALL_DATA_API_TOKEN")
    except Exception:
        pass
    if not token:
        token = os.getenv("FOOTBALL_DATA_API_TOKEN")
    return token


def parse_utc_date(utc_date):
    """Parse an ISO 8601 UTC date string (e.g. '2026-06-15T18:00:00Z') into a datetime."""
    if not utc_date:
        return None
    try:
        return datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_kickoff(kickoff):
    """Format a UTC datetime as Czech local time (CET/CEST), e.g. '15.6. 20:00'."""
    if kickoff is None:
        return None
    local_dt = kickoff.astimezone(PRAGUE_TZ)
    return f"{local_dt.day}.{local_dt.month}. {local_dt.strftime('%H:%M')}"


@st.cache_data(ttl=60, show_spinner=False)
def fetch_world_cup_matches():
    """Fetch World Cup 2026 match info (score + kickoff time) from football-data.org
    (https://www.football-data.org/documentation/quickstart).

    Returns a dict keyed by our MATCH_COLUMNS codes, e.g.:
        {"MEX-JAR": {"score": "2:0", "kickoff": <datetime|None>, "status": "FINISHED"}}
    Matches that aren't found in the API response are omitted.
    """
    token = get_football_data_token()
    if not token:
        return {}

    try:
        headers = {"X-Auth-Token": token}
        response = requests.get(FOOTBALL_DATA_API_URL, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        matches = data.get("matches", [])

        match_data = {}
        for match in matches:
            home_name = match.get("homeTeam", {}).get("name", "")
            away_name = match.get("awayTeam", {}).get("name", "")

            full_time = match.get("score", {}).get("fullTime", {})
            home_score = full_time.get("home")
            away_score = full_time.get("away")

            status = match.get("status")
            kickoff = parse_utc_date(match.get("utcDate"))

            for match_code in MATCH_COLUMNS:
                home_code, away_code = match_code.split("-")

                reversed_sides = False
                if team_matches(home_code, home_name) and team_matches(away_code, away_name):
                    reversed_sides = False
                elif team_matches(away_code, home_name) and team_matches(home_code, away_name):
                    reversed_sides = True
                else:
                    continue

                score = None
                if status == "FINISHED" and home_score is not None and away_score is not None:
                    if reversed_sides:
                        score = f"{away_score}:{home_score}"
                    else:
                        score = f"{home_score}:{away_score}"

                match_data[match_code] = {
                    "score": score,
                    "kickoff": kickoff,
                    "status": status,
                }

        return match_data
    except Exception:
        # Ignore API errors silently - user can still enter results manually
        return {}


def evaluate(df, results):
    df = df.copy()
    point_cols = []

    for match in MATCH_COLUMNS:
        col = f"Body {match}"
        df[col] = df[match].apply(lambda tip: points_for_tip(tip, results.get(match, "")))
        point_cols.append(col)

    df["Celkem"] = df[point_cols].sum(axis=1)
    df = df.sort_values(["Celkem", "Jméno"], ascending=[False, True])
    df.insert(0, "Pořadí", range(1, len(df) + 1))
    return df


def to_excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Vyhodnocení")
    return output.getvalue()


def render_results_table(df, results):
    """Render the standings as a styled HTML table.

    Tip cells are color-coded based on points earned:
    - green  -> exact score (POINTS_EXACT)
    - yellow -> correct outcome only (POINTS_OUTCOME)
    - red    -> wrong tip (POINTS_OTHER)
    - grey   -> match not yet played / no result available
    """
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    row_classes = {1: "top1", 2: "top2", 3: "top3"}

    header_cells = '<th class="rank-col">Pořadí</th><th class="name-col">Jméno</th>'
    header_cells += "".join(f"<th>{match}</th>" for match in MATCH_COLUMNS)
    header_cells += '<th class="total-col">Celkem</th>'

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

        cells += f'<td class="total-cell">{int(row["Celkem"])}</td>'
        rows_html.append(f'<tr class="{row_class}">{cells}</tr>')

    return f"""
    <div class="table-wrapper">
        <table class="results-table">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{"".join(rows_html)}</tbody>
        </table>
    </div>
    """


df = pd.DataFrame(TIPS)

st.set_page_config(page_title="BI Tým - MS Fotbal 2026 Tipovačka", layout="wide", initial_sidebar_state="collapsed")

# Custom CSS styling
st.markdown("""
<style>
    .main {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 20px;
    }

    .match-input {
        background: var(--secondary-background-color);
        border-radius: 8px;
        padding: 16px;
        border: 2px solid rgba(128, 128, 128, 0.25);
        transition: all 0.3s ease;
    }
    
    .match-input:hover {
        border: 2px solid #1f77b4;
        box-shadow: 0 4px 12px rgba(31, 119, 180, 0.15);
    }
    
    .score-input {
        font-size: 20px;
        font-weight: bold;
        text-align: center;
        border: 2px solid rgba(128, 128, 128, 0.25);
        border-radius: 6px;
        padding: 12px;
    }
    
    h1 {
        color: var(--text-color);
        text-align: center;
        font-size: 2.5em;
        font-weight: 700;
        margin-bottom: 10px;
        text-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    h3 {
        color: #1f77b4;
        font-size: 1.3em;
        font-weight: 600;
        margin-top: 20px;
        border-bottom: 3px solid #1f77b4;
        padding-bottom: 8px;
    }
    
    .stDataFrame {
        border-radius: 8px !important;
        border: 1px solid rgba(128, 128, 128, 0.25) !important;
    }
    
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
        color: var(--text-color);
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
        color: var(--text-color);
        opacity: 0.6;
    }
    
    button {
        border-radius: 6px !important;
        font-weight: 600 !important;
    }

    .table-wrapper {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        margin-bottom: 10px;
        border: 1px solid rgba(128, 128, 128, 0.15);
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
        white-space: nowrap;
    }

    .results-table thead th.name-col {
        text-align: left;
    }

    .results-table tbody td {
        padding: 10px;
        text-align: center;
        border-bottom: 1px solid rgba(128, 128, 128, 0.15);
    }

    .results-table tbody tr:nth-child(even) {
        background-color: rgba(128, 128, 128, 0.06);
    }

    .results-table tbody tr:hover {
        background-color: rgba(31, 119, 180, 0.15);
    }

    .results-table tbody tr.top1 { background-color: rgba(255, 215, 0, 0.18) !important; }
    .results-table tbody tr.top2 { background-color: rgba(192, 192, 192, 0.2) !important; }
    .results-table tbody tr.top3 { background-color: rgba(205, 127, 50, 0.18) !important; }

    .results-table .rank-cell {
        font-weight: 700;
        font-size: 1.1em;
        white-space: nowrap;
    }

    .results-table .name-cell {
        text-align: left;
        font-weight: 600;
        color: var(--text-color);
        white-space: nowrap;
    }

    .results-table .score-cell {
        font-weight: 600;
        border-radius: 6px;
        white-space: nowrap;
    }

    .results-table .score-exact {
        background-color: #f0faf0;
        color: #2e7d32;
    }

    .results-table .score-outcome {
        background-color: #fffbe8;
        color: #b8860b;
    }

    .results-table .score-miss {
        background-color: #fdf3f2;
        color: #c0392b;
    }

    .results-table .score-pending {
        background-color: rgba(128, 128, 128, 0.15);
        color: var(--text-color);
        opacity: 0.6;
    }

    .results-table .total-cell {
        font-weight: 800;
        font-size: 1.15em;
        color: #1f77b4;
        white-space: nowrap;
    }

    .table-legend {
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        justify-content: center;
        margin: 10px 0 20px 0;
        font-size: 0.9em;
        color: var(--text-color);
        opacity: 0.75;
    }

    .table-legend .legend-swatch {
        display: inline-block;
        width: 14px;
        height: 14px;
        border-radius: 3px;
        margin-right: 6px;
        vertical-align: middle;
        border: 1px solid rgba(128, 128, 128, 0.25);
    }

    /* Dark-theme adjustments */
    @media (prefers-color-scheme: dark) {
        .main {
            background: linear-gradient(135deg, #1a1c24 0%, #2b2d3a 100%);
        }

        h1 {
            text-shadow: 0 2px 4px rgba(0,0,0,0.5);
        }

        .match-card,
        .table-wrapper {
            box-shadow: 0 2px 8px rgba(0,0,0,0.5);
        }

        .results-table .score-exact {
            background-color: #1b4d20;
            color: #b6f5b6;
        }

        .results-table .score-outcome {
            background-color: #5c4600;
            color: #ffe9a8;
        }

        .results-table .score-miss {
            background-color: #5c1f1a;
            color: #ffd0cc;
        }
    }
</style>
""", unsafe_allow_html=True)

st.title("⚽ BI Tým Tipovačka MS 2026")

st.markdown(f"""
<div class="match-card" style="border-left: 4px solid #2ca02c; text-align: center;">
    <p style="margin: 0; font-size: 1.05em;">
        <strong>📋 Bodování tipů:</strong>
        &nbsp;&nbsp; 🎯 přesný výsledek = <strong>{POINTS_EXACT} body</strong>
        &nbsp;|&nbsp; ✅ správný tip (výhra/remíza/prohra) = <strong>{POINTS_OUTCOME} bod</strong>
        &nbsp;|&nbsp; ❌ netrefený tip = <strong>{POINTS_OTHER} bodů</strong>
    </p>
</div>
""", unsafe_allow_html=True)

# Fetch match info (results + kickoff times) from API
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

# Results input section
if api_results:
    st.subheader("✅ Výsledky zápasů")
    st.caption("Výsledky jsou automaticky načítány z football-data.org. Časy zápasů ve středoevropském čase (SEČ/SELČ).")
    results = api_results

    # Display results in a nice format
    cols = st.columns(3)

    for i, match in enumerate(MATCH_COLUMNS):
        with cols[i % 3]:
            kickoff_str = format_kickoff(match_data.get(match, {}).get("kickoff"))
            kickoff_html = (
                f'<p class="match-card-kickoff">🕒 {kickoff_str}</p>'
                if kickoff_str else ""
            )
            st.markdown(f"""
            <div class="match-card">
                <p class="match-card-title">{match_emojis.get(match, match)}</p>
                <p class="match-card-score">{results.get(match, "?:?")}</p>
                {kickoff_html}
            </div>
            """, unsafe_allow_html=True)
else:
    st.subheader("🎯 Výsledky zápasů")
    st.caption("Zadej výsledky ručně. Prázdné zápasy se nehodnotí. Časy zápasů ve středoevropském čase (SEČ/SELČ).")

    cols = st.columns(3)
    results = {}

    for i, match in enumerate(MATCH_COLUMNS):
        with cols[i % 3]:
            kickoff_str = format_kickoff(match_data.get(match, {}).get("kickoff"))
            kickoff_html = (
                f'<p class="match-card-kickoff">🕒 {kickoff_str}</p>'
                if kickoff_str else ""
            )
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
                label_visibility="collapsed"
            )

evaluated = evaluate(df, results)

st.subheader("🏆 Pořadí")
st.markdown(render_results_table(evaluated, results), unsafe_allow_html=True)
st.markdown("""
<div class="table-legend">
    <span><span class="legend-swatch" style="background-color: #f0faf0;"></span>Přesný tip (3 body)</span>
    <span><span class="legend-swatch" style="background-color: #fffbe8;"></span>Správný výsledek - výhra/remíza/prohra (1 bod)</span>
    <span><span class="legend-swatch" style="background-color: #fdf3f2;"></span>Netrefený tip (0 bodů)</span>
    <span><span class="legend-swatch" style="background-color: #f1f1f1;"></span>Zápas ještě neproběhl</span>
</div>
""", unsafe_allow_html=True)

st.divider()

# Display stats
col1, col2, col3 = st.columns(3)

if len(evaluated) > 0:
    with col1:
        st.metric("🥇 Vítěz", evaluated.iloc[0]["Jméno"], f"{evaluated.iloc[0]['Celkem']} bodů")
    
    if len(evaluated) > 1:
        with col2:
            st.metric("🥈 Druhé místo", evaluated.iloc[1]["Jméno"], f"{evaluated.iloc[1]['Celkem']} bodů")
    
    if len(evaluated) > 2:
        with col3:
            st.metric("🥉 Třetí místo", evaluated.iloc[2]["Jméno"], f"{evaluated.iloc[2]['Celkem']} bodů")

st.divider()

st.divider()

# Download section
download_col1, download_col2 = st.columns(2)

with download_col1:
    st.download_button(
        "📥 Stáhnout XLSX",
        data=to_excel_bytes(evaluated),
        file_name="vyhodnoceni_ms_fotbal_2026.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with download_col2:
    st.download_button(
        "📥 Stáhnout CSV",
        data=evaluated.to_csv(index=False).encode("utf-8-sig"),
        file_name="vyhodnoceni_ms_fotbal_2026.csv",
        mime="text/csv",
    )
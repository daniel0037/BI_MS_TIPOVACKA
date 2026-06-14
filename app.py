from datetime import datetime
from zoneinfo import ZoneInfo
import os
import markdown
import pandas as pd
import requests
import streamlit as st


st.set_page_config(
    page_title="MS Fotbal 2026 - vyhodnocení tipů",
    layout="centered",
    initial_sidebar_state="collapsed",
)

POINTS_EXACT = 3
POINTS_OUTCOME = 1
POINTS_OTHER = 0

MATCH_COLUMNS = ["MEX-JAR", "CZE-KOR", "CZE-JAR", "MEX-KOR", "CZE-MEX", "JAR-KOR"]

TIPS = [
    {"Jméno": "ADAMBOREC", "MEX-JAR": "2:0", "CZE-KOR": "1:1", "CZE-JAR": "2:0", "MEX-KOR": "1:1", "CZE-MEX": "1:3", "JAR-KOR": "2:1"},
    {"Jméno": "PAVLÍNABOREC", "MEX-JAR": "3:0", "CZE-KOR": "1:1", "CZE-JAR": "1:0", "MEX-KOR": "2:0", "CZE-MEX": "0:3", "JAR-KOR": "1:2"},
    {"Jméno": "HELLOKITTY", "MEX-JAR": "2:2", "CZE-KOR": "3:0", "CZE-JAR": "1:0", "MEX-KOR": "2:1", "CZE-MEX": "1:1", "JAR-KOR": "1:3"},
    {"Jméno": "JINDROS1881", "MEX-JAR": "2:1", "CZE-KOR": "3:2", "CZE-JAR": "1:0", "MEX-KOR": "4:1", "CZE-MEX": "1:2", "JAR-KOR": "2:2"},
    {"Jméno": "KUBAMAN", "MEX-JAR": "4:1", "CZE-KOR": "1:1", "CZE-JAR": "2:1", "MEX-KOR": "3:0", "CZE-MEX": "0:2", "JAR-KOR": "1:2"},
    {"Jméno": "KRISTýNABOREC", "MEX-JAR": "3:1", "CZE-KOR": "2:2", "CZE-JAR": "3:1", "MEX-KOR": "3:1", "CZE-MEX": "1:3", "JAR-KOR": "1:3"},
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

EXPECTED_RESULTS = {
    "MEX": {"JAR": "2:0", "KOR": "1:1", "CZE": "2:0"},
    "CZE": {"JAR": "2:0", "KOR": "1:1", "MEX": "0:2"},
    "KOR": {"MEX": "1:1", "CZE": "1:1", "JAR": "2:0"},
    "JAR": {"MEX": "0:2", "CZE": "0:2", "KOR": "0:2"},
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


@st.cache_data(ttl=60, show_spinner=False)
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
    home_code, away_code = match_code.split("-")
    return EXPECTED_RESULTS.get(home_code, {}).get(away_code, "?:?")


def realism_score(tip, expected):
    tip_score = parse_score(tip)
    exp_score = parse_score(expected)

    if tip_score is None or exp_score is None:
        return 50

    if tip_score == exp_score:
        return 100

    if outcome(tip_score) == outcome(exp_score):
        return 70

    home_diff = abs(tip_score[0] - exp_score[0])
    away_diff = abs(tip_score[1] - exp_score[1])

    if home_diff + away_diff == 1:
        return 40

    return max(0, 50 - (home_diff + away_diff) * 10)


def analyze_tips(df_tips):
    stats = {}

    for _, row in df_tips.iterrows():
        name = row["Jméno"]

        total_goals = 0
        cze_goals = 0
        cze_goals_against = 0
        realism = []
        audacity_score = 0

        for match in MATCH_COLUMNS:
            tip_score = parse_score(row[match])
            if tip_score is None:
                continue

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
            exp_score = parse_score(expected)

            realism.append(realism_score(row[match], expected))

            if exp_score:
                audacity_score += abs(tip_score[0] - exp_score[0]) + abs(tip_score[1] - exp_score[1])

        stats[name] = {
            "total_goals": total_goals,
            "avg_goals": total_goals / len(MATCH_COLUMNS),
            "cze_balance": cze_goals - cze_goals_against,
            "avg_realism": sum(realism) / len(realism) if realism else 0,
            "audacity": audacity_score,
        }

    return stats


def generate_ai_insights(evaluated_df, stats_dict, played_matches):
    api_key = get_groq_api_key()

    if not api_key:
        st.error("❌ Groq API klíč není nastaven. Přidej GROQ_API_KEY do .streamlit/secrets.toml")
        return None

    standings_text = evaluated_df[["Pořadí", "Jméno", "Odehráno", "Celkem"]].to_string(index=False)

    stats_summary = ""
    for name, stat in list(stats_dict.items())[:9]:
        stats_summary += (
            f"- {name}: {stat['avg_goals']:.1f} gólů/zápas, "
            f"realismus {stat['avg_realism']:.0f} %, "
            f"odvaha {stat['audacity']}\n"
        )

    prompt = f"""
Jsi expert na fotbalovou analytiku a zábavný data storytelling.

Analyzuj firemní tipovací soutěž k MS ve fotbale 2026.

Aktuální tabulka:
{standings_text}

Počet odehraných zápasů: {played_matches}/{len(MATCH_COLUMNS)}

Statistiky tipů:
{stats_summary}

Napiš česky krátký AI insight:
- 1 krátký odstavec k aktuálním výsledkům a tabulce
- 3 odrážky k top 3
- Přidej nějaké zajímavosti o každém z dalších tipérů, ale buď přesný a drž se dat (nevycucávej z prstu)
- tón: vtipný, sportovní, přátelský
- používej emoji
- drž se pouze poskytnutých dat a buď přesný
- 1 vtip o datech nebo datové analytice na závěr
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
        return data["choices"][0]["message"]["content"]

    except Exception as e:
        st.error(f"❌ AI insight se nepodařilo vygenerovat: {e}")
        return None


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

    return f"""
    <div class="table-wrapper">
        <table class="results-table">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{"".join(rows_html)}</tbody>
        </table>
    </div>
    """


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

st.title("⚽ BI Champs Tipovačka MS ve fotbale 2026")

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

results = api_results.copy()

# AI Insight nad sekcí Výsledky zápasů.
preview_evaluated = evaluate(df, results)
stats = analyze_tips(df)
played_matches = get_played_matches_count(results)

st.subheader("🤖 AI Insight")

if played_matches == 0:
    st.info("AI insight se zobrazí, jakmile bude odehraný alespoň jeden zápas nebo zadáš výsledek ručně.")
else:
    if st.button("✨ Vygeneruj AI Insight", key="ai_insight_btn"):
        with st.spinner("Groq skládá komentář jak ze studia po zápase..."):
            ai_text = generate_ai_insights(preview_evaluated, stats, played_matches)

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

st.divider()

# Výsledky zápasů.
if api_results:
    st.subheader("✅ Výsledky zápasů")
    st.caption("Výsledky se automaticky stahují z football-data.org. Časy zápasů jsou ve středoevropském čase.")
else:
    st.subheader("🎯 Výsledky zápasů")
    st.caption("Vyplň výsledky ručně. Nezaplněné zápasy se nebudou vyhodnocovat.")

cols = st.columns(3)

for i, match in enumerate(MATCH_COLUMNS):
    with cols[i % 3]:
        kickoff_str = format_kickoff(match_data.get(match, {}).get("kickoff"))
        kickoff_html = f'<p class="match-card-kickoff">🕒 {kickoff_str}</p>' if kickoff_str else ""

        if api_results:
            st.markdown(f"""
            <div class="match-card">
                <p class="match-card-title">{match_emojis.get(match, match)}</p>
                <p class="match-card-score">{results.get(match, "?:?")}</p>
                {kickoff_html}
            </div>
            """, unsafe_allow_html=True)
        else:
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

# Po ručním zadání přepočítáme data.
evaluated = evaluate(df, results)
played_matches = get_played_matches_count(results)

st.subheader("🏆 Pořadí")
st.markdown(render_results_table(evaluated, results), unsafe_allow_html=True)

st.markdown("""
<div class="table-legend">
    <span><span class="legend-swatch" style="background-color: #f0faf0;"></span>Přesný tip</span>
    <span><span class="legend-swatch" style="background-color: #fffbe8;"></span>Správný výsledek</span>
    <span><span class="legend-swatch" style="background-color: #fdf3f2;"></span>Netrefený tip</span>
    <span><span class="legend-swatch" style="background-color: #f1f1f1;"></span>Zápas ještě neproběhl</span>
</div>
""", unsafe_allow_html=True)

st.divider()


st.subheader("📖 Vysvětlivky metrik")

st.markdown(f"""
### Bodování tipů

- **Přesný výsledek** = {POINTS_EXACT} body
Tip přesně odpovídá skutečnému skóre zápasu.

- **Správný výsledek zápasu** = {POINTS_OUTCOME} bod
Tip netrefil přesné skóre, ale správně určil výhru, remízu nebo prohru.

- **Netrefený tip** = {POINTS_OTHER} bodů
Tip neodpovídá ani výsledku zápasu.

---

### Realismus

Realismus ukazuje, jak moc se tipy hráče blíží očekávaným výsledkům podle předem nastavené síly týmů.

Výpočet pro každý zápas:

- **100 %** = tip přesně odpovídá očekávanému výsledku
- **70 %** = tip má stejný výsledek zápasu, tedy výhra/remíza/prohra
- **40 %** = tip se liší pouze o jeden gól celkem
- **0–50 %** = čím větší rozdíl oproti očekávání, tím nižší realismus

Celkový realismus hráče je průměr ze všech jeho tipů.

---

### Odvaha

Odvaha měří, jak moc se hráč ve svých tipech odchyluje od očekávaných výsledků.

Pro každý zápas se počítá rozdíl:

`|tip domácí - očekávání domácí| + |tip hosté - očekávání hosté|`

Tyto rozdíly se následně sečtou za všechny zápasy.

Čím vyšší hodnota, tím odvážnější a méně konzervativní tipování.

---

### Průměr gólů na zápas

Ukazuje, kolik gólů hráč průměrně očekává v jednom zápase podle svých tipů.

Vyšší hodnota znamená, že hráč tipuje otevřenější a gólovější zápasy.

---

### Bilance ČR

Bilance ČR ukazuje, jak optimisticky hráč tipuje český tým.

Počítá se jako:

`tipované góly ČR - tipované góly soupeřů ČR`

Vyšší hodnota znamená větší víru v český tým.
Nižší nebo záporná hodnota znamená opatrnější až skeptičtější pohled na české výsledky.

---

### AI Insight

AI Insight používá aktuální pořadí, počet odehraných zápasů a doplňkové metriky jako realismus, odvahu, průměr gólů nebo bilanci ČR.

Slouží pouze jako komentář a zábavná analytická nadstavba.
Body a pořadí se počítají výhradně podle skutečných výsledků zápasů.
""")
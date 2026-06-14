from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
import requests
import os

st.set_page_config(page_title="MS Fotbal 2026 - vyhodnocení tipů", layout="wide", initial_sidebar_state="collapsed")

POINTS_EXACT = 3
POINTS_OUTCOME = 1
POINTS_OTHER = 0

MATCH_COLUMNS = ["MEX-JAR", "CZE-KOR", "CZE-JAR", "MEX-KOR", "CZE-MEX", "JAR-KOR"]

# Tipy jsou rovnou zapsané ve skriptu, není potřeba nahrávat XLSX.
TIPS = [
    {"Jméno": "ADAMBOREC", "MEX-JAR": "2:0", "CZE-KOR": "1:1", "CZE-JAR": "2:0", "MEX-KOR": "1:1", "CZE-MEX": "1:3", "JAR-KOR": "2:1"},
    {"Jméno": "PAVLINABOREC", "MEX-JAR": "3:0", "CZE-KOR": "1:1", "CZE-JAR": "1:0", "MEX-KOR": "2:0", "CZE-MEX": "0:3", "JAR-KOR": "1:2"},
    {"Jméno": "HELLOKITTY", "MEX-JAR": "2:2", "CZE-KOR": "3:0", "CZE-JAR": "1:0", "MEX-KOR": "2:1", "CZE-MEX": "1:1", "JAR-KOR": "1:3"},
    {"Jméno": "JINDROS1981", "MEX-JAR": "2:1", "CZE-KOR": "3:2", "CZE-JAR": "1:0", "MEX-KOR": "4:1", "CZE-MEX": "1:2", "JAR-KOR": "2:2"},
    {"Jméno": "KUBAMAN", "MEX-JAR": "4:1", "CZE-KOR": "1:1", "CZE-JAR": "2:1", "MEX-KOR": "3:0", "CZE-MEX": "0:2", "JAR-KOR": "1:2"},
    {"Jméno": "KRISTINABOREC", "MEX-JAR": "3:1", "CZE-KOR": "2:2", "CZE-JAR": "3:1", "MEX-KOR": "3:1", "CZE-MEX": "1:3", "JAR-KOR": "1:3"},
    {"Jméno": "DANBOREC", "MEX-JAR": "2:0", "CZE-KOR": "1:2", "CZE-JAR": "1:1", "MEX-KOR": "1:1", "CZE-MEX": "2:2", "JAR-KOR": "0:2"},
    {"Jméno": "ALEX", "MEX-JAR": "3:1", "CZE-KOR": "2:2", "CZE-JAR": "2:1", "MEX-KOR": "2:0", "CZE-MEX": "1:3", "JAR-KOR": "2:1"},
    {"Jméno": "NASTA", "MEX-JAR": "3:0", "CZE-KOR": "1:2", "CZE-JAR": "1:0", "MEX-KOR": "1:0", "CZE-MEX": "0:2", "JAR-KOR": "0:2"},
    {"Jméno": "🤖 CLAUDE AI", "MEX-JAR": "2:0", "CZE-KOR": "1:1", "CZE-JAR": "2:0", "MEX-KOR": "1:1", "CZE-MEX": "0:2", "JAR-KOR": "0:2"},
]

TEAM_NAMES = {
    "MEX": ["mexico", "mexiko", "mex"],
    "JAR": ["south africa", "jihoafrická republika", "jihoafricka republika", "jar", "rsa"],
    "CZE": ["czech republic", "czechia", "česko", "cesko", "cze"],
    "KOR": ["south korea", "korea republic", "korea republic of", "jižní korea", "jizni korea", "kor"],
}

# Hodnocení síly týmů (0-100 bodů)
TEAM_STRENGTH = {
    "MEX": 78,  # Silný tým CONCACAF, hraje doma
    "KOR": 73,  # Silný asijský tým
    "CZE": 58,  # Střední kvalita evropského týmu
    "JAR": 45,  # Nejslabší tým skupiny
}

# Očekávané výsledky podle síly týmů (home_team code -> away_team code -> expected_result)
EXPECTED_RESULTS = {
    "MEX": {"JAR": "2:0", "KOR": "1:1", "CZE": "2:0"},
    "CZE": {"JAR": "2:0", "KOR": "1:1", "MEX": "0:2"},
    "KOR": {"MEX": "1:1", "CZE": "1:1", "JAR": "2:0"},
    "JAR": {"MEX": "0:2", "CZE": "0:2", "KOR": "0:2"},
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
        # Ignoruj chyby API tiše - user can still enter results manually
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_head_to_head_history():
    """Fetch recent matches between these teams from football-data.org"""
    token = get_football_data_token()
    if not token:
        return {}
    
    try:
        headers = {"X-Auth-Token": token}
        h2h_data = {}
        
        # Fetch completed matches from past World Cups/competitions
        response = requests.get(
            "https://api.football-data.org/v4/matches?status=FINISHED",
            headers=headers,
            timeout=10,
            params={"limit": 100}
        )
        response.raise_for_status()
        
        matches = response.json().get("matches", [])
        
        # Filter for matches between our teams
        for match in matches:
            home = match.get("homeTeam", {})
            away = match.get("awayTeam", {})
            home_name = normalize_text(home.get("name", ""))
            away_name = normalize_text(away.get("name", ""))
            
            home_code = None
            away_code = None
            
            for code in TEAM_NAMES:
                if team_matches(code, home_name):
                    home_code = code
                if team_matches(code, away_name):
                    away_code = code
            
            if home_code and away_code and home_code != away_code:
                match_key = f"{home_code}-{away_code}"
                full_time = match.get("score", {}).get("fullTime", {})
                home_score = full_time.get("home")
                away_score = full_time.get("away")
                
                if home_score is not None and away_score is not None:
                    utc_date = match.get("utcDate")
                    date_str = ""
                    if utc_date:
                        try:
                            dt = parse_utc_date(utc_date)
                            if dt:
                                date_str = dt.strftime("%d.%m.%Y")
                        except:
                            pass
                    
                    if match_key not in h2h_data:
                        h2h_data[match_key] = []
                    
                    h2h_data[match_key].append({
                        "date": date_str,
                        "score": f"{home_score}:{away_score}",
                        "home": home_code,
                        "away": away_code,
                    })
        
        return h2h_data
    except Exception:
        return {}


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


def get_expected_result(match_code):
    """Get expected result for a match based on team strength."""
    home_code, away_code = match_code.split("-")
    return EXPECTED_RESULTS.get(home_code, {}).get(away_code, "?:?")


def realism_score(tip, expected):
    """Calculate realism score (0-100) for a tip vs expected result.
    
    100 = exact match with expected
    70 = same outcome (W/D/L)
    40 = off by 1 goal
    0 = completely unrealistic
    """
    tip_score = parse_score(tip)
    exp_score = parse_score(expected)
    
    if tip_score is None or exp_score is None:
        return 50
    
    if tip_score == exp_score:
        return 100
    
    if outcome(tip_score) == outcome(exp_score):
        return 70
    
    # Check if off by small margin
    home_diff = abs(tip_score[0] - exp_score[0])
    away_diff = abs(tip_score[1] - exp_score[1])
    
    if home_diff + away_diff == 1:
        return 40
    
    return max(0, 50 - (home_diff + away_diff) * 10)


def analyze_tips(df_tips, results):
    """Analyze all tips and return various statistics."""
    stats = {}
    
    for _, row in df_tips.iterrows():
        name = row["Jméno"]
        total_goals = 0
        cze_goals = 0
        cze_goals_against = 0
        realism = []
        audacity_score = 0
        
        for match in MATCH_COLUMNS:
            tip = row[match]
            tip_score = parse_score(tip)
            
            if tip_score:
                total_goals += tip_score[0] + tip_score[1]
                
                # CZE analysis
                if "CZE" in match:
                    home_code, away_code = match.split("-")
                    if home_code == "CZE":
                        cze_goals += tip_score[0]
                        cze_goals_against += tip_score[1]
                    else:
                        cze_goals += tip_score[1]
                        cze_goals_against += tip_score[0]
                
                # Realism score
                expected = get_expected_result(match)
                realism.append(realism_score(tip, expected))
                
                # Audacity - how far from expected
                exp_score = parse_score(expected)
                if exp_score:
                    diff = abs(tip_score[0] - exp_score[0]) + abs(tip_score[1] - exp_score[1])
                    audacity_score += diff
        
        stats[name] = {
            "total_goals": total_goals,
            "avg_goals": total_goals / 6 if total_goals > 0 else 0,
            "cze_goals": cze_goals,
            "cze_goals_against": cze_goals_against,
            "cze_balance": cze_goals - cze_goals_against,
            "avg_realism": sum(realism) / len(realism) if realism else 0,
            "audacity": audacity_score,
        }
    
    return stats


def build_consensus(df_tips):
    """Build a consensus map of most-tipped scores for each match."""
    consensus = {}
    
    for match in MATCH_COLUMNS:
        score_counts = {}
        for _, row in df_tips.iterrows():
            tip = row[match]
            if pd.notna(tip):
                tip_str = str(tip).strip()
                score_counts[tip_str] = score_counts.get(tip_str, 0) + 1
        
        consensus[match] = score_counts
    
    return consensus


def head_to_head(df_tips):
    """Build head-to-head match data - who tips what for each game."""
    h2h = {}
    
    for match in MATCH_COLUMNS:
        h2h[match] = []
        for _, row in df_tips.iterrows():
            h2h[match].append({
                "name": row["Jméno"],
                "tip": str(row[match]).strip() if pd.notna(row[match]) else "?",
            })
    
    return h2h


def monte_carlo_simulation(df_evaluated, df_tips, results, num_simulations=1000):
    """Run Monte Carlo simulation to predict final standings.
    
    For each unfinished match, randomly pick from tips to simulate outcome.
    Returns probability of each person finishing in each position.
    """
    import random
    
    final_positions = {row["Jméno"]: {"1st": 0, "2nd": 0, "3rd": 0, "other": 0} for _, row in df_evaluated.iterrows()}
    
    # Find unfinished matches
    unfinished = [m for m in MATCH_COLUMNS if results.get(m) is None or parse_score(results.get(m)) is None]
    
    if not unfinished:
        # All matches finished - just return current standings
        for i, (_, row) in enumerate(df_evaluated.iterrows()):
            if i == 0:
                final_positions[row["Jméno"]]["1st"] = num_simulations
            elif i == 1:
                final_positions[row["Jméno"]]["2nd"] = num_simulations
            elif i == 2:
                final_positions[row["Jméno"]]["3rd"] = num_simulations
            else:
                final_positions[row["Jméno"]]["other"] = num_simulations
        return final_positions
    
    for _ in range(num_simulations):
        sim_results = results.copy()
        
        # For each unfinished match, randomly pick a tip from all tips
        for match in unfinished:
            all_tips = [str(row[match]).strip() for _, row in df_tips.iterrows() if pd.notna(row[match])]
            if all_tips:
                sim_results[match] = random.choice(all_tips)
        
        # Evaluate with simulated results
        sim_evaluated = evaluate(df_tips, sim_results)
        
        # Record positions
        for i, (_, row) in enumerate(sim_evaluated.iterrows()):
            name = row["Jméno"]
            if i == 0:
                final_positions[name]["1st"] += 1
            elif i == 1:
                final_positions[name]["2nd"] += 1
            elif i == 2:
                final_positions[name]["3rd"] += 1
            else:
                final_positions[name]["other"] += 1
    
    return final_positions


df = pd.DataFrame(TIPS)

st.set_page_config(page_title="MS Fotbal 2026 - vyhodnocení tipů", layout="wide", initial_sidebar_state="collapsed")

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

st.title("⚽ MS Fotbal 2026 - Vyhodnocení Tipů")

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

# Stažení informací o zápasech (výsledky + časy)
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

# Sekce pro zadávání výsledků
if api_results:
    st.subheader("✅ Výsledky zápasů (z API)")
    st.caption("Výsledky se automaticky stahují z football-data.org. Časy zápasů jsou ve středoevropském čase (SEČ/SELČ).")
    results = api_results

    # Zobrazení výsledků v přehledném formátu
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
    st.caption("Vyplň výsledky ručně. Nezaplněné zápasy se nebudou vyhodnocovat. Časy zápasů jsou ve středoevropském čase (SEČ/SELČ).")

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

# Zobrazení statistiky
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

# 📊 ANALÝZA TIPŮ
st.subheader("📊 Analýza a zajímavosti")

# Výpočet analýz
tips_df = df.copy()  # Použij původní tipy, ne vyhodnocené
stats = analyze_tips(tips_df, results)
consensus = build_consensus(tips_df)
h2h = head_to_head(tips_df)

# Řazení
sorted_by_goals = sorted(stats.items(), key=lambda x: x[1]["avg_goals"], reverse=True)
sorted_by_realism = sorted(stats.items(), key=lambda x: x[1]["avg_realism"], reverse=True)
sorted_by_audacity = sorted(stats.items(), key=lambda x: x[1]["audacity"], reverse=True)
sorted_by_cze_optimism = sorted(stats.items(), key=lambda x: x[1]["cze_balance"], reverse=True)

# Vytvoř sloupce pro analýzy
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["⚽ Průměrný počet gólů", "🎯 Realističnost tipů", "🚀 Nejodvážnější tipy", "🇨🇿 Vztah k Česku", "🗺️ Konsenzus", "🤝 Head-to-Head", "🎲 Monte Carlo"]
)

with tab1:
    st.write("#### Kdo tipuje nejvíce gólů?")
    analytics_html = '<div style="display: grid; gap: 10px;">'
    for i, (name, stat) in enumerate(sorted_by_goals, 1):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else "•"
        avg = stat["avg_goals"]
        analytics_html += f'<div class="match-card" style="padding: 12px;"><strong>{medal} {name}</strong>: <span style="color: #1f77b4; font-weight: bold;">{avg:.1f} gólů/zápas</span> (celkem {stat["total_goals"]})</div>'
    analytics_html += '</div>'
    st.markdown(analytics_html, unsafe_allow_html=True)

with tab2:
    st.write("#### Kdo se držel realit podle síly týmů?")
    st.caption("Jak moc se jednotlivé tipy shodují s očekávaným výsledkem podle síly týmů")
    analytics_html = '<div style="display: grid; gap: 10px;">'
    for i, (name, stat) in enumerate(sorted_by_realism, 1):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else "•"
        realism = stat["avg_realism"]
        bar_width = int(realism / 100 * 30)
        bar = "█" * bar_width + "░" * (30 - bar_width)
        analytics_html += f'<div class="match-card" style="padding: 12px;"><strong>{medal} {name}</strong>: {realism:.0f}% [{bar}]</div>'
    analytics_html += '</div>'
    st.markdown(analytics_html, unsafe_allow_html=True)

with tab3:
    st.write("#### Kdo tipuje nejodvážnější výsledky?")
    st.caption("Jak moc se jednotlivý tipy odchylují od očekávaných výsledků (vyšší číslo = větší překvapení)")
    analytics_html = '<div style="display: grid; gap: 10px;">'
    for i, (name, stat) in enumerate(sorted_by_audacity, 1):
        medal = ["🎭", "🎪", "🎨"][i-1] if i <= 3 else "•"
        audacity = stat["audacity"]
        analytics_html += f'<div class="match-card" style="padding: 12px;"><strong>{medal} {name}</strong>: Odvahy skóre <span style="color: #ff9800; font-weight: bold;">{audacity}</span></div>'
    analytics_html += '</div>'
    st.markdown(analytics_html, unsafe_allow_html=True)

with tab4:
    st.write("#### Kdo věří v Česko? 🇨🇿")
    st.caption("Koho tipuje ČR více gólů ve prospěch vs. proti")
    analytics_html = '<div style="display: grid; gap: 10px;">'
    for i, (name, stat) in enumerate(sorted_by_cze_optimism, 1):
        cze_g = stat["cze_goals"]
        cze_a = stat["cze_goals_against"]
        balance = stat["cze_balance"]
        emoji = "😊" if balance > 0 else "😟" if balance < 0 else "😐"
        emoji += " +" if balance > 0 else " " if balance >= 0 else " "
        analytics_html += f'<div class="match-card" style="padding: 12px;"><strong>{i}. {name}</strong> {emoji}{balance}: tipuje {cze_g} gólů pro ČR vs {cze_a} proti</div>'
    analytics_html += '</div>'
    st.markdown(analytics_html, unsafe_allow_html=True)

with tab5:
    st.write("#### 🗺️ Konsenzus skupiny – Která skóre se tipují nejčastěji?")
    st.caption("Která skóre se tipují nejčastěji a kde je skupina sjednocená")
    
    for match in MATCH_COLUMNS:
        match_emoji = {"MEX-JAR": "🇲🇽 vs 🇿🇦", "CZE-KOR": "🇨🇿 vs 🇰🇷", "CZE-JAR": "🇨🇿 vs 🇿🇦", 
                      "MEX-KOR": "🇲🇽 vs 🇰🇷", "CZE-MEX": "🇨🇿 vs 🇲🇽", "JAR-KOR": "🇿🇦 vs 🇰🇷"}.get(match, match)
        
        scores = consensus.get(match, {})
        if scores:
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            
            consensus_html = f'<div class="match-card" style="padding: 12px; border-left: 4px solid #ff9800;">'
            consensus_html += f'<p style="margin: 0 0 8px 0; font-weight: 600; color: var(--text-color);">{match_emoji} ({match})</p>'
            consensus_html += '<div style="display: flex; gap: 8px; flex-wrap: wrap;">'
            
            for score, count in sorted_scores[:5]:  # Top 5 nejvíce tipovaných
                pct = int(count / len(tips_df) * 100)
                consensus_html += f'<span style="background: rgba(31, 119, 180, 0.2); padding: 6px 12px; border-radius: 6px; font-weight: 600;"><strong>{score}</strong> ({count}x, {pct}%)</span>'
            
            consensus_html += '</div></div>'
            st.markdown(consensus_html, unsafe_allow_html=True)

with tab6:
    st.write("#### 🤝 Head-to-Head: Kdo tipuje co v jednotlivých zápasech?")
    st.caption("Porovnání tipů pro každý zápas – uvidíš, kdo tipuje stejně a kdo jinak")
    
    for match in MATCH_COLUMNS:
        match_emoji = {"MEX-JAR": "🇲🇽 vs 🇿🇦", "CZE-KOR": "🇨🇿 vs 🇰🇷", "CZE-JAR": "🇨🇿 vs 🇿🇦", 
                      "MEX-KOR": "🇲🇽 vs 🇰🇷", "CZE-MEX": "🇨🇿 vs 🇲🇽", "JAR-KOR": "🇿🇦 vs 🇰🇷"}.get(match, match)
        
        tips_for_match = h2h.get(match, [])
        
        h2h_html = f'<div class="match-card" style="padding: 12px; border-left: 4px solid #9c27b0;">'
        h2h_html += f'<p style="margin: 0 0 8px 0; font-weight: 600; color: var(--text-color);">{match_emoji}</p>'
        h2h_html += '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px;">'
        
        for tip_info in tips_for_match:
            h2h_html += f'<div style="background: rgba(156, 39, 176, 0.1); padding: 8px; border-radius: 6px; text-align: center; font-size: 0.85em;"><strong>{tip_info["name"]}</strong><br/><span style="color: #1f77b4; font-weight: bold; font-size: 1.1em;">{tip_info["tip"]}</span></div>'
        
        h2h_html += '</div></div>'
        st.markdown(h2h_html, unsafe_allow_html=True)

with tab7:
    st.write("#### 🎲 Monte Carlo Simulace: Jaká je šance na výhru?")
    st.caption("Predikce na základě dosavadních výsledků a tipů skupiny")
    
    if st.button("▶️ Spustit simulaci (1000 scénářů)", key="mc_sim"):
        with st.spinner("Simuluji 1000 možných průběhů zápasů..."):
            probabilities = monte_carlo_simulation(evaluated, df, results, num_simulations=1000)
        
        # Display probabilities
        mc_html = '<div style="display: grid; gap: 12px;">'
        for person in evaluated["Jméno"]:
            probs = probabilities.get(person, {})
            p1 = probs.get("1st", 0) / 10  # Convert to percentage
            p2 = probs.get("2nd", 0) / 10
            p3 = probs.get("3rd", 0) / 10
            
            mc_html += f'''<div class="match-card" style="padding: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <strong style="font-size: 1.1em;">{person}</strong>
                    <div style="display: flex; gap: 12px; font-size: 0.9em;">
                        <span>🥇 {p1:.0f}%</span>
                        <span>🥈 {p2:.0f}%</span>
                        <span>🥉 {p3:.0f}%</span>
                    </div>
                </div>
                <div style="margin-top: 8px; display: flex; gap: 4px; height: 20px; border-radius: 4px; overflow: hidden;">
                    <div style="flex: {p1}; background: #ffd700; display: flex; align-items: center; justify-content: center; font-size: 0.7em; color: white; font-weight: bold;" title="1st">{p1:.0f}%</div>
                    <div style="flex: {p2}; background: #c0c0c0; display: flex; align-items: center; justify-content: center; font-size: 0.7em; color: white; font-weight: bold;" title="2nd">{p2:.0f}%</div>
                    <div style="flex: {p3}; background: #cd7f32; display: flex; align-items: center; justify-content: center; font-size: 0.7em; color: white; font-weight: bold;" title="3rd">{p3:.0f}%</div>
                    <div style="flex: {100-p1-p2-p3}; background: #ddd;"></div>
                </div>
            </div>'''
        mc_html += '</div>'
        st.markdown(mc_html, unsafe_allow_html=True)
    else:
        st.info("Kliknutím na tlačítko spustíš simulaci a uvidíš pravděpodobnost výhry pro všechny.")

st.divider()

# 💭 Zajímavé pozorování (Emoji vtipy)
st.subheader("💭 Zajímavé pozorování & Vtípky")

interesting_facts = []

# Optimisté vs pesimisté
top_optimist = sorted_by_goals[0]
top_pessimist = sorted_by_goals[-1]
interesting_facts.append(
    f"🌞 **Optimista zápasu**: {top_optimist[0]} věří v gólovou přehlídku (⌀ {top_optimist[1]['avg_goals']:.1f} gólů/zápas), "
    f"zatímco {top_pessimist[0]} je fatalisté (jen ⌀ {top_pessimist[1]['avg_goals']:.1f} gólů/zápas)"
)

# Realista
top_realist = sorted_by_realism[0]
interesting_facts.append(
    f"📊 **Realista skupiny**: {top_realist[0]} se drží realit s {top_realist[1]['avg_realism']:.0f}% shodou se silou týmů"
)

# Největší hazardér
top_audacious = sorted_by_audacity[0]
interesting_facts.append(
    f"🚀 **Největší hazardér**: {top_audacious[0]} tipuje nejméně realistické výsledky (odklon {top_audacious[1]['audacity']} od očekávání)"
)

# Vztah k ČR
top_cze_optimist = sorted_by_cze_optimism[0]
top_cze_pessimist = sorted_by_cze_optimism[-1]
interesting_facts.append(
    f"🇨🇿 **Domácí patriot**: {top_cze_optimist[0]} věří v sílu ČR (bilance {top_cze_optimist[1]['cze_balance']:+d}), "
    f"naopak {top_cze_pessimist[0]} je skeptik ({top_cze_pessimist[1]['cze_balance']:+d})"
)

# Další analýzy
# Remíza specialista
remiza_counts = {}
for _, row in tips_df.iterrows():
    name = row["Jméno"]
    remiza_counts[name] = sum(1 for m in MATCH_COLUMNS if str(row[m]).count(":") == 1 and parse_score(row[m]) and parse_score(row[m])[0] == parse_score(row[m])[1])

if remiza_counts:
    remiza_expert = max(remiza_counts.items(), key=lambda x: x[1])
    interesting_facts.append(
        f"🤝 **Mistr remíz**: {remiza_expert[0]} tipuje {remiza_expert[1]} remíz (=) – věří v mírová řešení"
    )

# Největší rozdíly v tipech
max_diff_tipper = {}
for _, row in tips_df.iterrows():
    name = row["Jméno"]
    max_diff = 0
    for m in MATCH_COLUMNS:
        score = parse_score(row[m])
        if score:
            diff = abs(score[0] - score[1])
            max_diff = max(max_diff, diff)
    max_diff_tipper[name] = max_diff

if max_diff_tipper:
    biggest_diff = max(max_diff_tipper.items(), key=lambda x: x[1])
    interesting_facts.append(
        f"🎪 **Mistr překvapení**: {biggest_diff[0]} tipuje největší rozdíly (až {biggest_diff[1]}:0) – rád dramatiku"
    )

# Nejkonzistentnější (nejméně rozprasku)
consistency = {}
for _, row in tips_df.iterrows():
    name = row["Jméno"]
    all_tips = [parse_score(row[m]) for m in MATCH_COLUMNS if pd.notna(row[m])]
    if all_tips:
        goals = [t[0] + t[1] for t in all_tips]
        std_dev = (sum((g - sum(goals)/len(goals))**2 for g in goals) / len(goals)) ** 0.5
        consistency[name] = std_dev

if consistency:
    most_consistent = min(consistency.items(), key=lambda x: x[1])
    interesting_facts.append(
        f"🎯 **Mistr konzistence**: {most_consistent[0]} tipuje velmi podobné výsledky (nejstabilnější hráč)"
    )

# Průměrný tip skupiny vs outliers
avg_goals_group = sum(s['avg_goals'] for s in stats.values()) / len(stats) if stats else 0
outliers = [(name, stat['avg_goals']) for name, stat in stats.items() if abs(stat['avg_goals'] - avg_goals_group) > 0.5]

if outliers:
    outlier = max(outliers, key=lambda x: abs(x[1] - avg_goals_group))
    interesting_facts.append(
        f"📈 **Odchylec skupiny**: {outlier[0]} tipuje ⌀ {outlier[1]:.1f} gólů (skupiny ⌀ {avg_goals_group:.1f}) – osamělý vlk"
    )

for fact in interesting_facts:
    st.markdown(f"► {fact}")

st.divider()

# 📜 HISTORICKÁ UTKÁNÍ
st.subheader("📜 Historická utkání")
st.caption("Jak si tyto týmy vedly v minulosti – posledních pět vzájemných zápasů")

h2h_history = fetch_head_to_head_history()

if h2h_history:
    match_emojis = {
        "MEX-JAR": "🇲🇽 vs 🇿🇦",
        "CZE-KOR": "🇨🇿 vs 🇰🇷",
        "CZE-JAR": "🇨🇿 vs 🇿🇦",
        "MEX-KOR": "🇲🇽 vs 🇰🇷",
        "CZE-MEX": "🇨🇿 vs 🇲🇽",
        "JAR-KOR": "🇿🇦 vs 🇰🇷",
    }
    
    for match_code in MATCH_COLUMNS:
        history = h2h_history.get(match_code, [])
        
        if history:
            emoji = match_emojis.get(match_code, match_code)
            
            hist_html = f'<div class="match-card" style="padding: 12px; border-left: 4px solid #4caf50;">'
            hist_html += f'<p style="margin: 0 0 8px 0; font-weight: 600; color: var(--text-color);">{emoji}</p>'
            hist_html += '<div style="display: grid; gap: 6px;">'
            
            for h in history[-5:]:  # Zobraz posledních 5 zápasů
                hist_html += f'<div style="display: flex; justify-content: space-between; align-items: center; padding: 6px; background: rgba(76, 175, 80, 0.1); border-radius: 4px;">'
                hist_html += f'<span style="font-size: 0.85em; color: var(--text-color); opacity: 0.7;">{h["date"]}</span>'
                hist_html += f'<span style="font-weight: bold; color: #1f77b4;">{h["score"]}</span>'
                hist_html += '</div>'
            
            hist_html += '</div></div>'
            st.markdown(hist_html, unsafe_allow_html=True)
        else:
            match_emoji = match_emojis.get(match_code, match_code)
            st.info(f"{match_emoji} – Žádná historická utkání mezi těmito týmy v dostupných datech")
else:
    st.warning("📊 Historická data nejsou dostupná (API chyba nebo první setkání těchto týmů)")

st.divider()



with download_col1:
    st.download_button(
        "📥 Stáhnout Excel",
        data=to_excel_bytes(evaluated),
        file_name="evaluate_ms_fotbal_2026.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with download_col2:
    st.download_button(
        "📥 Stáhnout CSV",
        data=evaluated.to_csv(index=False).encode("utf-8-sig"),
        file_name="evaluate_ms_fotbal_2026.csv",
        mime="text/csv",
    )

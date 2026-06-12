# MS Fotbal 2026 - Vyhodnocení tipů

Streamlit aplikace pro vyhodnocení tipů na zápasy skupiny C/F (MEX, JAR/RSA,
CZE, KOR) na MS ve fotbale 2026. Pořadí se počítá podle bodovacího systému:

- **3 body** za přesný výsledek
- **1 bod** za správný výsledek zápasu (výhra/prohra/remíza)
- **0 bodů** jinak

## Instalace

```bash
pip install -r requirements.txt
```

## Konfigurace API tokenu (povinné pro automatické výsledky)

Aplikace se umí sama stahovat výsledky zápasů z API
[football-data.org](https://www.football-data.org/documentation/quickstart)
(endpoint `https://api.football-data.org/v4/competitions/WC/matches`).

Token se NEČTE z kódu, ale ze Streamlit secrets / proměnné prostředí:

1. Vytvoř soubor `.streamlit/secrets.toml` (přiložen rovnou hotový se
   skutečným tokenem - zkontroluj, že není v gitu / veřejném repu!)
   nebo zkopíruj `secrets.toml.example` a vyplň `FOOTBALL_DATA_API_TOKEN`.
2. Případně nastav proměnnou prostředí `FOOTBALL_DATA_API_TOKEN`.

Pokud token chybí, API není dostupné nebo nevrátí žádné dokončené zápasy z
požadované skupiny, aplikace přepne do režimu manuálního zadávání výsledků.

> ⚠️ Pozor na limity free tieru football-data.org (počet požadavků za
> minutu). Výsledky jsou proto cachované na 60 sekund
> (`@st.cache_data(ttl=60)`).

> 🔒 Soubor `.streamlit/secrets.toml` je v `.gitignore` - nikdy ho nenahrávej
> do veřejného repozitáře, obsahuje API token.

## Spuštění

```bash
streamlit run app.py
```

## Export

Aplikace umožňuje stáhnout vyhodnocené pořadí jako:

- XLSX (`vyhodnoceni_ms_fotbal_2026.xlsx`)
- CSV (`vyhodnoceni_ms_fotbal_2026.csv`)

# AI Forex Journal

A local journal app that compares a completed forex session with your strategy rules. Python retrieves market data and calculates indicators; OpenAI produces a draft analysis that you can review, edit, and save.

The frontend uses React and Vite. The backend uses FastAPI and a local SQLite database.

## Current features

- **Generate journal:** choose a session date, enter strategy rules and optional observations, then generate and edit a journal.
- **Saved journals:** reopen entries, edit their text, or restore the original draft in the editor and save it.
- **Strategy profiles:** save named rule sets, update them, and copy their rules into the generation form.
- **Market evidence:** inspect all six candles, including open/close times, open and close prices, candle change percentage, and indicators. Momentum displays five decimal places.

## Supported market data

| Setting | Current behavior |
| --- | --- |
| Instrument | EUR/USD |
| Candle timeframe | H4 (four hours) |
| Provider | OANDA practice API |
| Prices | Midpoint, unsmoothed candles |
| Session | 5:00 p.m. on the previous date through 5:00 p.m. on the selected date, America/New_York |
| Required session data | Six completed H4 candles |
| Indicator history | 300 earlier candles |
| Indicators | EMA20, SMA190, RSI14 with Wilder smoothing, and LazyBear Squeeze Momentum |
| Squeeze settings | Corrected formula; Bollinger Bands 20 / 2.0, Keltner Channels 20 / 1.5, true range enabled |

For example, a journal dated **2026-10-20** covers **2026-10-19 at 5:00 p.m. through 2026-10-20 at 5:00 p.m. New York time**. Daylight saving time is handled using that timezone.

Weekend dates and sessions whose closing cutoff has not passed are rejected. Holidays or missing provider data may also prevent a full session from being available. MACD is not included.

## Local setup

These commands assume macOS or Linux and that you start in the repository root. Setup has been used with Python 3.13 and Node.js 24. The installed Vite version requires Node.js 20.19+ on the 20.x line, or 22.12+.

You need Python 3.13, Node.js with npm, an OpenAI API key with API access, and an OANDA practice account with v20 API access and a token.

### 1. Install backend dependencies

```bash
cd backend
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If the backend virtual environment already exists, activate it and install dependencies as needed; there is no need to recreate it.

### 2. Configure the backend

From `backend`, create a local configuration file for a new installation:

```bash
cp -n .env.example .env
```

If you already have a configured `backend/.env`, keep it. The command above does not overwrite an existing file.

Edit `.env` and replace the credential placeholders:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `OPENAI_MODEL` | Model used for generation; the current application default is `gpt-6-luna` |
| `OANDA_API_TOKEN` | Your OANDA practice API token |
| `OANDA_ACCOUNT_ID` | Your OANDA practice account ID |
| `OANDA_API_URL` | Must be `https://api-fxpractice.oanda.com` for the current implementation |

The backend loads this file automatically. Restart the backend after changing its configuration. Keep real credentials in `.env`, which is ignored by Git; commit only the placeholder `.env.example`. The frontend does not need API keys or a Python virtual environment.

### 3. Start the backend

In a terminal, from the repository root:

```bash
cd backend
source .venv/bin/activate
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open [the API status page](http://127.0.0.1:8000/) or [the interactive API documentation](http://127.0.0.1:8000/docs). The database is initialized automatically on startup.

### 4. Start the frontend

In a second terminal, from the repository root:

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open [the journal app](http://127.0.0.1:5173/). On later runs, dependencies only need reinstalling when they change.

Keep both terminals running while using the app. The frontend currently calls `http://127.0.0.1:8000`; the backend allows frontend requests from localhost or 127.0.0.1 on port 5173. `--strictPort` prevents Vite from silently moving to another port.

## How generation and saving work

1. The frontend sends the selected date, strategy, and optional observations to the backend.
2. The backend fetches OANDA candles, validates the session, and calculates indicators using earlier history. It excludes candles that finish after the session cutoff.
3. `journal_grounding.py` builds a session-specific catalogue labeled `C1` through `C6`. The backend sends the user input, six session candles with indicators, summary/settings metadata, and catalogue to OpenAI. The 300 earlier candles are used for calculation but are not sent as individual candles.
4. OpenAI returns structured qualitative analysis with references to candles and fields. Python validates that structure and renders the quoted prices, indicators, and timestamps directly from the market snapshot.
5. A valid draft and its original evidence are staged in SQLite. Clicking **Save journal** creates a saved journal. Later text edits preserve the original draft, strategy, and market snapshot.

Reopening a saved journal uses its stored snapshot without fetching OANDA data or generating another AI response. Updating a strategy profile does not change the strategy stored in an older journal. Candle labels are generated for each session; they are not separate database candle IDs.

Grounding binds displayed evidence values to the referenced candles. It does not independently prove that every qualitative AI assessment is correct or that the chosen evidence fully supports a strategy rule. Review the draft and candle table before saving. User edits are saved separately from the original draft and are not checked by the generation-time grounding rules.

## Data storage

SQLite data lives at `backend/data/journal.db`. It contains saved journals, staged generated drafts, and strategy profiles. The database is local to this checkout and is ignored by Git; committing or pushing code does not back up your journals. To make a simple file backup, stop the backend and copy the database to a separate location.

Drafts do not appear in **Saved journals** until you click **Save journal**. Unsaved editor changes are held in the browser and can be lost on refresh. Older journals created before market snapshots were added remain readable but have no stored candle evidence.

## Automated checks

From the repository root, run the backend tests:

```bash
cd backend
./.venv/bin/python -B -m unittest discover -v
```

The current suite contains **56 tests**:

| File | Tests | Coverage |
| --- | ---: | --- |
| `test_market_data.py` | 14 | Session boundaries, candle validation, history cutoff, and provider errors |
| `test_journal_evidence.py` | 13 | Saving, immutable original evidence, repeated saves, and older database migration |
| `test_journal_grounding.py` | 19 | Candle references, rendered values/times, structured output, and rejected drafts |
| `test_strategy_profiles.py` | 10 | Profile creation, updates, validation, persistence, and journal independence |

These tests use dummy credentials, simulated provider responses, and temporary databases. They do not make live OANDA/OpenAI requests or change your saved journals. No running backend server or real `.env` is required. Some tests intentionally log an evidence-rejection message; a successful run ends with `Ran 56 tests` and `OK`.

From the repository root, check the frontend:

```bash
cd frontend
npm run lint
npm run build
```

The build writes generated frontend assets to `frontend/dist`. It does not start the backend or publish the app.

The separate `backend/check_oanda.py` and `backend/check_openai.py` scripts are optional **live connection checks**, not part of the automated suite. They use real credentials and contact the providers; the OpenAI check uses API tokens. The OANDA check currently uses the fixed session date 2026-10-20.

## Troubleshooting and limits

- **Cannot connect / Failed to fetch:** confirm the backend is running on port 8000 and open the frontend on port 5173.
- **Session not finished or incomplete:** choose a completed weekday session. Generation needs all six completed candles and enough earlier history.
- **OANDA access error:** check the practice account credentials and required practice API URL in `backend/.env`.
- **AI request failed:** check API access, the configured model, and the error shown by the app. Failed generation does not create a saved journal.
- **AI draft failed its evidence checks:** the generated response failed validation. No new draft was staged; you can try generating again.

This version supports local use on one computer, without user accounts or authentication. It reviews completed sessions; it does not place orders, provide live entry signals, or run strategy backtests. Historical availability depends on the provider, and the automated tests do not establish that live provider access is working.

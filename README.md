# AI Forex Journal

A local journal app that compares a completed forex session with your strategy rules. Python retrieves market data and calculates indicators; OpenAI produces a draft analysis that you can review, edit, and save.

The frontend uses React and Vite. The backend uses FastAPI and a local SQLite database.

## Current features

- **Generate journal:** choose a session date, enter strategy rules and optional observations, then generate and edit a journal.
- **Saved journals:** browse a month calendar, select a session date to see its saved entries, then reopen, edit, restore the original draft, or delete after confirmation. Green/red days show the saved EUR/USD session's positive/negative price change.
- **Strategy profiles:** save named rule sets, update them, copy their rules into the generation form, or delete a profile after confirmation.
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
| `OPENAI_MODEL` | Model used for generation; the current application default is `gpt-6.1-sol` |
| `OANDA_API_TOKEN` | Your OANDA practice API token |
| `OANDA_ACCOUNT_ID` | Your OANDA practice account ID |
| `OANDA_API_URL` | Must be `https://api-fxpractice.oanda.com` for the current implementation |

The backend loads this file automatically. Restart the backend after changing its configuration. Keep real credentials in `.env`, which is ignored by Git; commit only the placeholder `.env.example`. The frontend does not need API keys or a Python virtual environment.

Journal generation uses **GPT-6.1 Sol with medium reasoning** by default. When upgrading an existing installation, change only `OPENAI_MODEL=gpt-6.1-sol` in your existing `backend/.env`; copying a new `.env.example` does not update that file. Keep your API keys and OANDA settings. A model already exported in the backend terminal's environment takes precedence over `.env`.

The OpenAI request allows up to 8,000 combined reasoning and output tokens, with a 90-second client timeout and no automatic retries. These are starting limits, not a guarantee that every strategy will complete within them. Incomplete responses are rejected without staging a new draft. The grounding rules, indicators, and saved journals are unchanged by the model switch. Compare generated rule assessments against the market evidence; changing models does not itself establish improved accuracy.

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

The calendar groups entries by **journal session date**, not the date you saved them. Its percentage is `(session close - session open) / session open * 100`, using the stored EUR/USD H4 snapshot for the 5 p.m.–5 p.m. New York window. This is market price change, not trade profit or loss. If multiple journals share a date, the day uses the most recently saved usable snapshot; their percentages are never added together. Flat sessions and entries without usable snapshots stay neutral. Dates without saved journals have no percentage, and viewing the calendar makes no OANDA or OpenAI requests.

Use the month arrows or **Jump to month** to browse, **Today** to return to the current New York date, and **Latest saved date** to find your most recent journal session. Select a date to see all its entries, with pagination when there are more than 20. The calendar shows every saved date in the month, regardless of that list's page. Calendar days support arrow keys plus Home/End. **Refresh calendar** reloads the displayed month and date after changes in another browser tab or a failed request.

Use **Delete** beside an entry in Saved journals, or **Delete journal** in an open saved entry. The confirmation identifies the journal and warns that deletion cannot be undone. Deletion removes that journal's original draft, saved edits, and market snapshot. If it is open, its editor closes after deletion; other open drafts and strategy profiles are preserved. The calendar and entry list refresh while keeping the selected month and date. If deletion empties the current page, the list moves to the last remaining page. A failed request displays an error, and an entry already deleted in another tab is removed from the stale view when you confirm deletion.

Use **Delete** beside a strategy profile, or **Delete profile** in its editor. The confirmation names the saved profile and warns about unsaved edits if that profile is open. Deletion clears that profile's editor; edits to another profile are kept. Existing journals, staged drafts, and strategy text already copied into the generation form retain their rules. The deleted profile's name is removed from the form's loaded-profile label, and that name can be reused for a new profile. Failed deletion keeps the profile and editor available for retry; confirming deletion of an already deleted profile removes it from the stale view.

## Automated checks

From the repository root, run the backend tests:

```bash
cd backend
./.venv/bin/python -B -m unittest discover -v
```

The current backend suite contains **84 tests**:

| File | Tests | Coverage |
| --- | ---: | --- |
| `test_market_data.py` | 14 | Session boundaries, candle validation, history cutoff, and provider errors |
| `test_journal_evidence.py` | 13 | Saving, immutable original evidence, repeated saves, and older database migration |
| `test_journal_grounding.py` | 19 | Candle references, rendered values/times, structured output, rejected drafts, and the Sol/medium request sent by the SDK |
| `test_journal_deletion.py` | 9 | Deletion, stale requests, isolation, persistence, rollback, pagination, and browser access |
| `test_journal_calendar.py` | 10 | Monthly counts, date filtering, leap days, saved percentages, duplicate sessions, missing snapshots, validation, and deletion refresh |
| `test_strategy_profiles.py` | 10 | Profile creation, updates, validation, persistence, and journal independence |
| `test_strategy_profile_deletion.py` | 9 | Profile deletion, copied-rule preservation, stale edits, name reuse, rollback, persistence, concurrency, and browser access |

These tests use dummy credentials, simulated provider responses, and temporary databases. They do not make live OANDA/OpenAI requests or change your saved journals. No running backend server or real `.env` is required. Some tests intentionally log an evidence-rejection message; a successful run ends with `Ran 84 tests` and `OK`.

From the repository root, check the frontend:

```bash
cd frontend
node --test tests/journalCalendar.test.js
npm run lint
npm run build
```

The seven frontend calendar tests cover date placement, leap years, month/year navigation, New York date boundaries, and percentage formatting. The build writes generated frontend assets to `frontend/dist`. It does not start the backend or publish the app.

The separate `backend/check_oanda.py` and `backend/check_openai.py` scripts are optional **live connection checks**, not part of the automated suite. They use real credentials and contact the providers; the OpenAI check uses API tokens. The OpenAI check uses the configured model with medium reasoning and a smaller 2,048-token limit. It prints the requested and returned model, response status, and usage, and exits with an error for incomplete or empty replies. The OANDA check currently uses the fixed session date 2026-10-20.

## Troubleshooting and limits

- **Cannot connect / Failed to fetch:** confirm the backend is running on port 8000 and open the frontend on port 5173.
- **Session not finished or incomplete:** choose a completed weekday session. Generation needs all six completed candles and enough earlier history.
- **OANDA access error:** check the practice account credentials and required practice API URL in `backend/.env`.
- **AI request failed:** check API access, the configured model, and the error shown by the app. Failed generation does not create a saved journal.
- **AI draft failed its evidence checks:** the generated response failed validation. No new draft was staged; you can try generating again.

This version supports local use on one computer, without user accounts or authentication. It reviews completed sessions; it does not place orders, provide live entry signals, or run strategy backtests. Historical availability depends on the provider, and the automated tests do not establish that live provider access is working.

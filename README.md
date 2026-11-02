# AI Forex Journal

A local journal app that compares a completed forex session with your strategy rules. Python retrieves market data, calculates indicators, and evaluates the built-in four-factor strategy. OpenAI writes commentary around those results. Written strategies can also use the original AI review mode.

The frontend uses React and Vite. The backend uses FastAPI and a local SQLite database.

## Current features

- **Generate journal:** choose a session date, select the scored four-factor strategy or a written strategy, add optional observations, then generate and edit a journal.
- **Strategy scores:** inspect each candle's factor outcomes, bullish/bearish points and alignment, with v4 averaging all six candles and showing final-candle bias separately. Saved calculations remain separate from editable journal text.
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

The **Generate journal** form groups session settings, strategy rules, and optional observations into separate panels. Session settings show the fixed EUR/USD pair, 4-hour timeframe, and 5 p.m.–5 p.m. New York window. **Strategy evaluation** defaults to **Four-factor strategy v4 · Session average**. Its fixed definitions are loaded from the backend. **Written strategy · AI review** retains the editable text workflow without calculated points. **Saved strategies** opens Strategy profiles, where **Use in journal** copies the saved rules and evaluation method into the form. Written copies can be customized; scored rules remain fixed for their version. The rule and note fields show their existing 10,000-character limits.

Generation disables the form controls and shows a waiting message. Required-field and generation errors appear beside the Generate button, while your inputs remain available for correction or retry. A successful request opens the journal reading view below the form.

1. The frontend sends the selected date, strategy, optional observations, and selected `rule_set_id` to the backend. For a scored request, the backend replaces client-supplied rule text with the canonical definitions for that version.
2. The backend fetches OANDA candles, validates the session, and calculates indicators using earlier history. It excludes candles that finish after the session cutoff.
3. `journal_grounding.py` builds a session-specific catalogue labeled `C1` through `C6`. The market snapshot also retains two preceding completed trading candles (`previous_candles`, labeled `P-1` then `P0` in scored evidence). The `previous_candle` field remains an alias of P0 for earlier consumers. The remaining warmup candles are used for indicator calculation rather than sent individually to OpenAI.
4. For the scored strategy, `strategy_rules.py` evaluates all four factors on each candle and calculates points and bias. OpenAI receives the complete market snapshot, evidence catalogue, Python evaluation and a compact `summary_context` derived from the actual session candles. It returns four short commentary sections with references to calculated results. `scored_journal.py` rejects mismatched price direction, scoring method, overall bias or final-candle bias, as well as invalid references, invented figures and oversized responses. Python inserts the actual price change and official consensus figures. The AI cannot award points or override the calculated direction; its qualitative interpretation still needs review. For written strategies, the original grounded AI interpretation continues to select assessments and bias.
5. A valid draft, its original market evidence, and any rule evaluation are staged in SQLite. Clicking **Save journal** creates a saved journal. Later text edits preserve the original draft, strategy, market snapshot and calculated results.

Reopening a saved journal uses its stored snapshot without fetching OANDA data or generating another AI response. Updating a strategy profile does not change the strategy stored in an older journal. Candle labels are generated for each session; they are not separate database candle IDs.

The **Strategy profiles** page places the saved-profile library beside a larger rule editor. Each profile explicitly stores its evaluation method. Existing profiles retain their saved method and rule version. Select Four-factor strategy v4 and save to adopt the session average; v1, v2 and v3 remain selectable with their original rules and final-candle summaries. The selected profile is highlighted, character counts show the existing limits, and an unsaved-changes label distinguishes edits from saved rules. **New profile** and **Edit** move focus to the editor. On smaller screens the library and form stack vertically. Save feedback appears beside the form actions; switching tabs keeps your edits, and **Use in journal** copies only saved rules and their evaluation method.

Generated and saved journals share a reading view with a dated session header, market price summary, and clearly separated journal sections. Use **Edit** to change the original text and **Read** to preview it; switching modes does not save or rewrite the journal. **Save journal** saves a new draft, while **Save changes** updates an existing entry. **Restore AI draft** restores the original text in the editor and still requires saving. Opening a journal brings its header into view; **Back to calendar** returns to the selected saved date without discarding edits.

New scored journals use a short summary: **Session recap**, **Agreement and conflict**, **Directional consensus**, and **Concerns**. The prompt targets roughly 150–200 words including server-rendered facts; AI explanations have a combined 160-word maximum. The narrative distinguishes actual price movement, the selected rule version’s consensus, and any separate final-candle change. Detailed candle evidence, indicator values, factor outcomes and rules remain in their existing tables and disclosures rather than being repeated in the text. Short summaries use the full reading width without a section sidebar. Older saved or pending journals retain their original text; generate a new journal to use the new format. Written-strategy AI review keeps its existing grounded format.

Expand **Strategy & observations** to review the session inputs, or **View all six candles and indicators** for the market table. The table retains open/close time ranges, open and close prices, percentage changes, and five-decimal momentum values. On narrow screens the table scrolls within its panel. Older journals without snapshots keep their readable text. The reading view formats known journal headings and Markdown-style headings while displaying other content as plain text; it does not execute embedded HTML or turn journal content into links.

The scored mode calculates the official decisions deterministically. AI prose remains commentary and can still need review; it cannot replace the separate calculated-results panel. In written/AI mode, grounding binds evidence values but does not prove the AI's rule interpretation. User text edits are saved separately from the original draft and are not checked by the generation-time grounding rules.

## Four-factor strategy v4

Each factor awards up to its weight to at most one side per completed candle. All comparisons use unrounded values. The default scored preset is `four_factor_v4`. Per-candle rules match v3; the session summary now averages all six candles equally. EMA20 vs SMA190 is worth two points; each of the other three factors is worth at most one point. The momentum factor is reduced to half a point during a qualifying slowdown.

| Factor | Weight | Bullish condition | Bearish condition |
| --- | ---: | --- | --- |
| Two closes vs EMA20 | 1 | Current and previous completed trading candles each close strictly above their own EMA20 | Both close strictly below their own EMA20 |
| EMA20 vs SMA190 | 2 | EMA20 > SMA190 | EMA20 < SMA190 |
| RSI14 extremes | 1 | RSI14 ≤ 40 (strategy-defined oversold) | RSI14 ≥ 60 (strategy-defined overbought) |
| Momentum direction and pace | Up to 1 | Positive and rising: 1 point; 0.5 if slowing | Negative and falling: 1 point; 0.5 if slowing |

Equality, mixed consecutive closes, RSI strictly between 40 and 60, positive/falling momentum, and negative/rising momentum earn neither side a point. Zero or unchanged momentum is neutral. A sign crossing can meet the momentum rule only when both its sign and change requirements hold. The proposed ±0.0025/near-zero factor is not included.

Momentum pace uses exactly **three consecutive completed trading candles**, producing two deltas: `previous − older` and `current − previous`. When all three momentum values are positive and both deltas are positive, a smaller latest delta earns **0.5 bullish points**. When all three are negative and both deltas are negative, a smaller latest delta magnitude earns **0.5 bearish points**. For example, 0.00100 → 0.00180 → 0.00230 gives +0.00080 → +0.00050 and earns half a bullish point. The mirrored negative sequence earns half a bearish point. Slowing does not award an opposite-side point or establish a reversal.

Equal delta magnitudes retain the full point and display **Steady pace**; larger magnitudes display **Accelerating**. A newly qualifying directional move retains the full point if the preceding delta was zero or in the other direction. A zero touch or crossing anywhere in the three-value window displays **Zero-crossing reset** and resets the slowdown comparison; the base direction can still earn its point. Missing or nonconsecutive three-candle history makes the v3/v4 momentum factor unavailable, with no assumed full point. The regular weekend break is allowed, including daylight-saving transitions. Only current and past candles are used.

A numerical equality tolerance (`rel_tol=1e-9`, `abs_tol=1e-12`) avoids false slowdown labels caused by floating-point subtraction. This is not a market-noise filter: other decreases count, and a broader minimum-change threshold has not been introduced. The rule definition stores the lookback, reduced points, and tolerance. The result stores the original momentum values, both deltas, pace label, and awarded points. The table shows **Slowing** beside the half-point result; expanded evidence shows the deltas to five decimals. Tiny differences can therefore affect the rule while looking equal after display rounding.

The consecutive-close rule uses a rolling pair: a longer streak still earns only one point on each candle. A previous candle must directly precede the current candle, except for the regular Friday 5 p.m. to Sunday 5 p.m. New York market break. Missing or invalid predecessor context makes affected factors unavailable; no missing bars are invented.

For each candle, bullish and bearish totals are each shown out of **five possible points**, across **four factors**. Alignment is `weighted points / 5 × 100`, with neutral and unavailable factor counts shown separately. For example, bullish EMA/SMA and consecutive closes with bearish RSI and neutral momentum give 3 bullish points, 1 bearish point and 1 neutral factor: 60% bullish alignment and 20% bearish alignment. A bullish EMA/SMA condition (2), bullish consecutive closes (1), slowing bullish momentum (0.5), and neutral RSI produce 3.5/5 = 70% bullish alignment. The four-factor coverage count is separate from the five-point maximum; reduced-point factors are reported separately from neutral or unavailable factors. Net score is bullish minus bearish. With all four factors evaluated, the larger total sets the directional lean; an equal nonzero total is mixed and zero/zero is neutral. Incomplete coverage withholds the directional label. These percentages measure rule alignment, not a calibrated likelihood of future price movement.

Every session shows all six individual candle scores. In v4, **session-average bullish points** are the sum of C1–C6 bullish points divided by six; bearish points are averaged separately. Each candle has equal weight, including half-point momentum outcomes. The maximum average remains **5**, and alignment is average points divided by five, multiplied by 100. Net is the session's bullish-minus-bearish total divided by six. The larger average sets the overall lean; equal nonzero averages are mixed and zero/zero is neutral. Calculations and stored values stay unrounded; summary points, net and alignment display two decimals.

The smaller **Session-end bias** label reports **C6 only**, separately from the session average. For example, candle scores of 5/0, 5/0, 5/0, 5/0, 0/4 and 0/5 produce average bullish 3.33/5 (66.67%), average bearish 1.50/5 (30.00%), net +1.83 and a bullish session lean, while the session-end label is bearish. This preserves the late change in direction without giving the final candle extra weight. Price direction remains the observed session return.

Session coverage counts **24 factor checks** (four on each of six candles). Neutral and reduced-point outcomes are available evaluations, but any unavailable input makes the session average **Incomplete**. In that case average bullish/bearish points, net and alignment percentages are stored as null and displayed as unavailable, not zero; incomplete candles are never silently excluded from the denominator. Individual candle results remain visible, and C6 can still supply a session-end label when its own inputs are complete. The server sends both the session average and the separate session-end result to the AI, and renders their official values in the journal itself.

The v4 evaluation retains schema version 1 with `summary.method="session_average"`, session coverage metadata, and a separate `session_end` object. Existing final-candle summaries keep their original shape. The evidence disclosure shows the required current and preceding inputs; momentum, deltas and prices display five decimals. The Price change % column after Bias uses each candle’s stored open-to-close price change. Scores and raw inputs are stored with the full rule definition/version and are not recalculated when a journal is reopened.

Version 1 retains RSI 30/70 and one point per factor (four possible points). Version 2 retains RSI 40/60 and two-point EMA/SMA weighting, with full momentum points and no slowdown adjustment. Version 3 adds the momentum slowdown rule. All three older versions retain C6-only summaries. Existing profiles and saved journals are not automatically upgraded. Changing a profile to **v4 · Session average** affects future generations; stored v1/v2/v3 journals and pending drafts keep their original evaluation and method. The panel and journal renderer use the saved version, weights and fractional points. Short descriptions below factor badges and information icons in the headers use each journal's saved outcomes and definitions.

## Data storage

SQLite data lives at `backend/data/journal.db`. It contains saved journals, staged generated drafts, and strategy profiles. The database is local to this checkout and is ignored by Git; committing or pushing code does not back up your journals. To make a simple file backup, stop the backend and copy the database to a separate location.

Drafts do not appear in **Saved journals** until you click **Save journal**. Unsaved editor changes are held in the browser and can be lost on refresh. Older journals created before market snapshots were added remain readable but have no stored candle evidence.

Backend startup adds nullable score columns to saved journals and staged drafts, and a nullable rule-set identifier to strategy profiles. Existing journals and pending drafts remain readable, with no invented historical scores. Profile changes, deletion, and journal-text edits do not change an already saved rule evaluation.

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

The current backend suite contains **151 tests**:

| File | Tests | Coverage |
| --- | ---: | --- |
| `test_market_data.py` | 14 | Session boundaries, candle validation, history cutoff, and provider errors |
| `test_journal_evidence.py` | 13 | Saving, immutable original evidence, repeated saves, and older database migration |
| `test_journal_grounding.py` | 19 | Candle references, rendered values/times, structured output, rejected drafts, and the Sol/medium request sent by the SDK |
| `test_journal_deletion.py` | 9 | Deletion, stale requests, isolation, persistence, rollback, pagination, and browser access |
| `test_journal_calendar.py` | 10 | Monthly counts, date filtering, leap days, saved percentages, duplicate sessions, missing snapshots, validation, and deletion refresh |
| `test_strategy_profiles.py` | 10 | Profile creation, updates, validation, persistence, and journal independence |
| `test_strategy_profile_deletion.py` | 9 | Profile deletion, copied-rule preservation, stale edits, name reuse, rollback, persistence, concurrency, and browser access |
| `test_strategy_rules.py` | 16 | Versioned weights and RSI boundaries, exact comparisons, momentum sign/change, rolling pairs, predecessor context, weekend/DST continuity, missing data, final-candle bias and no future influence |
| `test_scored_journal.py` | 15 | Version upgrades, weighted rendering, canonical presets, AI result boundaries, immutable scores, profile mode changes, migrations, saved/reopened results and concise score rendering |
| `test_momentum_slowdown.py` | 14 | Three-candle deltas, half-points, mirrored bearish behavior, numeric equality, zero-crossing resets, missing history, weekend/DST continuity, old versions and no future influence |
| `test_journal_summary.py` | 8 | Short output, canonical market facts, mismatched directions/method rejection, incomplete averages, word limit, mixed/neutral results and old-text preservation |
| `test_session_average.py` | 14 | Equal averaging, late reversals, half points, missing data, mixed/neutral sessions, legacy methods, canonical AI inputs, profile upgrades and immutable saving |

These tests use dummy credentials, simulated provider responses, and temporary databases. They do not make live OANDA/OpenAI requests or change your saved journals. No running backend server or real `.env` is required. Some tests intentionally log an evidence-rejection message; a successful run ends with `Ran 151 tests` and `OK`.

From the repository root, check the frontend:

```bash
cd frontend
node --test tests/*.test.js
npm run lint
npm run build
```

The 12 frontend tests cover date placement, leap years, month/year navigation, New York date boundaries, percentage formatting, and preservation of journal text in the reading view. The build writes generated frontend assets to `frontend/dist`. It does not start the backend or publish the app.

The separate `backend/check_oanda.py` and `backend/check_openai.py` scripts are optional **live connection checks**, not part of the automated suite. They use real credentials and contact the providers; the OpenAI check uses API tokens. The OpenAI check uses the configured model with medium reasoning and a smaller 2,048-token limit. It prints the requested and returned model, response status, and usage, and exits with an error for incomplete or empty replies. The OANDA check currently uses the fixed session date 2026-10-20.

## Troubleshooting and limits

- **Cannot connect / Failed to fetch:** confirm the backend is running on port 8000 and open the frontend on port 5173.
- **Session not finished or incomplete:** choose a completed weekday session. Generation needs all six completed candles and enough earlier history.
- **OANDA access error:** check the practice account credentials and required practice API URL in `backend/.env`.
- **AI request failed:** check API access, the configured model, and the error shown by the app. Failed generation does not create a saved journal.
- **AI draft failed its evidence checks:** the generated response failed validation. No new draft was staged; you can try generating again.

This version supports local use on one computer, without user accounts or authentication. It reviews completed sessions; it does not place orders, provide live entry signals, or run strategy backtests. Historical availability depends on the provider, and the automated tests do not establish that live provider access is working.

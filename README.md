# AI Forex Journal

To use the journal from your phone, follow the [Render deployment guide](docs/render-deployment.md).

A local journal app that compares a completed forex session with your strategy rules. Python retrieves market data, calculates indicators, and evaluates the built-in four-factor strategy. OpenAI writes commentary around those results. Written strategies can also use the original AI review mode.

The frontend uses React and Vite. The backend uses FastAPI and a local SQLite database.

## Current features

- **Trades:** record a manual EUR/USD entry, optionally retain a saved setup's evidence, add one full exit, and keep your discipline self-review separate from the Python-calculated pip and R result.
- **Evaluate setup:** capture a proposed long/short EUR/USD H4 setup with manual support/resistance zones, freeze the available market evidence and current four-factor results, and request a separate grounded AI assessment. Saved setups reopen without fetching newer prices or regenerating AI.
- **Today:** follow the active New York session with automatic completed-candle updates, provisional strategy averages, pending candle slots, and a manually generated AI summary. Save a frozen intraday review into Saved journals.
- **Generate journal:** choose a session date, select the scored four-factor strategy or a written strategy, add optional observations, then generate and edit a journal.
- **Strategy scores:** inspect each candle's factor outcomes, bullish/bearish points and alignment, with the current four-factor preset averaging all six completed candles and showing the final candle’s bias separately. Saved calculations remain separate from editable journal text.
- **Saved journals:** browse a month calendar, select a session date to see its saved entries, then reopen, edit, restore the original draft, or delete after confirmation. Green/red days show the saved EUR/USD session's positive/negative price change.
- **Custom range journal:** choose inclusive start and end dates for up to 31 calendar days, review all completed H4 candles with the same four-factor rules as daily journals, and generate a short summary of the whole period.
- **Saved custom journals:** browse a separate date-range library, reopen the original calculations, edit or restore the summary, and delete after confirmation.
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
| Indicators | EMA20, SMA190, Wilder RSI14, SMA14 of RSI14, and LazyBear Squeeze Momentum |
| Squeeze settings | Corrected formula; Bollinger Bands 20 / 2.0, Keltner Channels 20 / 1.5, true range enabled |

For example, a journal dated **2026-10-20** covers **2026-10-19 at 5:00 p.m. through 2026-10-20 at 5:00 p.m. New York time**. Daylight saving time is handled using that timezone.

Daily journals reject weekend dates and sessions whose closing cutoff has not passed. Custom ranges skip weekend session dates and require the selected end date's 5 p.m. cutoff to have passed. Holidays or missing provider data may also prevent a full session from being available. MACD is not included.

## Today and intraday reviews

Use the left sidebar to move between daily journals, custom date ranges, and strategy profiles. On phones and narrower screens, **Menu** opens the sidebar as a drawer. Selecting a page closes the drawer; Escape, the close button, or the backdrop also dismiss it. Unsaved-change indicators remain visible beside their pages, and navigation waits for active save/generation actions to finish.

The **Today** page follows the current EUR/USD trading session using completed H4 candles and the same four-factor rules as daily journals. It checks the backend once per minute while that page and the browser are visible, and refreshes when you return. **Refresh data** requests another check. Keep the backend running; this is a visible-page refresh workflow, not a background service or a tick-by-tick price stream. OANDA marks each candle as complete or incomplete in its [candlestick definition](https://developer.oanda.com/rest-live-v20/instrument-df/).

Only completed candles contribute prices, indicators, and scores. All six slots remain visible: **Completed**, **Forming · score pending**, or **Upcoming · pending**. Before the first candle closes at 9 p.m. New York time, the page shows a waiting state and AI generation is disabled. Earlier candles initialize indicators and supply predecessor context, but do not earn points in the current session.

The **session-to-date average** gives each completed candle equal weight. For example, three bullish scores of 3, 4 and 3 produce 3.33/5 average bullish points and 66.67% rule alignment. Coverage remains **3 of 6 candles**, a separate measure. Pending candles are not zeros, and no outcome is forecast for them. Missing factor inputs on a completed candle withhold the average instead of dropping that candle. The latest completed candle's bias is separate from the provisional average. At six candles, the calculation matches the existing full-session average. Rule alignment is not a calibrated probability of future movement.

Session dates refer to the ending 5 p.m. New York cutoff. For example, Tuesday after 5 p.m. belongs to the session ending Wednesday. At the weekday 5 p.m. rollover, Today starts the next session; use normal daily generation to review the one that just finished. During the scheduled Friday 5 p.m.–Sunday 5 p.m. weekend closure, Today displays the latest Friday session and the next scheduled opening. DST is handled in New York local time. Holiday closures and provider delays are not treated as future pending slots: if a candle should already have closed but is absent, refresh fails visibly and any previous display is marked potentially outdated.

**Generate AI summary** (or **Refresh AI summary**) is an explicit action. Ordinary data polling makes no AI calls and does not create saved journals. The summary uses a server-owned snapshot of the displayed completed candles and scores. A background refresh cannot alter its input. A new candle or revised evidence marks the existing summary as using older data, without replacing its text or your edits. The summary's cutoff and coverage stay visible. The AI receives the coverage and cannot cite a pending candle or substitute a full-session method for a partial review.

**Save journal** saves that exact snapshot in the existing daily **Saved journals** library. Intraday entries are labeled with their cutoff and completed-candle count. Reopening, editing, restoring, or deleting them uses the existing daily-journal controls; their market evidence and scores never update automatically. Partial-session returns do not color a calendar day as though they were completed daily returns. A date with only partial entries still shows its entry count but has no full-session percentage; a completed saved snapshot can supply that day's percentage. Regenerating on Today creates a separate draft, not an overwrite of a saved review.

The backend shares successful Today polls through a 55-second in-memory cache, invalidated at candle/session boundaries. A manual refresh can use this same cache. Up to 64 immutable generation snapshots are retained for 30 minutes, and generation accepts only their server IDs plus optional notes. If the ID expires or the backend restarts, refresh Today and generate again. Existing generated/saved journals remain in SQLite. No new database tables, dependencies, or credential settings are needed for Today. Old daily and custom-range generation still require their full completed sessions.

## Custom date-range journals

Open **Custom range journal**, choose a start and end date, and optionally add observations. Both dates are included. For example, **October 19–23, 2026** includes five trading sessions: **October 18 at 5 p.m. through October 23 at 5 p.m. New York time**, with **30 H4 candles**. Weekend dates are skipped; if an endpoint is a weekend, the actual analysis bounds use the first and last included weekday. A weekend-only range is rejected. The form previews the actual coverage before generation.

The initial limit is **31 calendar days**, including both endpoints, to bound provider requests and AI input size. This is an application limit. Every included weekday must have all six completed H4 candles; partial holiday sessions, missing candles, and unfinished ranges are rejected rather than silently omitted. The selected end date's 5 p.m. New York cutoff must have passed even when it falls on a weekend.

Range generation currently uses **EUR/USD, H4, and the current built-in four-factor strategy**. Written-strategy mode and versioned strategy profiles remain available in daily generation. Indicators are calculated continuously from 300 warmup candles through the entire range, without resetting at daily boundaries. The two earlier completed candles support the first candle's consecutive-close, RSI-trend and momentum rules. Later days use the preceding candles in the range, including across regular weekend/DST breaks. Only data available by the range cutoff is used.

Every completed H4 candle has equal weight. Average bullish points are total bullish points divided by the number of range candles; bearish points are averaged separately, each out of five. Because each accepted day has six candles, this equals averaging the daily scores equally. Missing factor inputs withhold the overall average instead of dropping candles from the denominator. The final candle's **Range-end bias** remains separate. Alignment measures how strongly the chosen rules agree, not a probability of a future price move. **Range change** uses the first candle's open and last candle's close; it is not an average of daily returns.

The backend sends the full range snapshot, globally numbered candle evidence (`C1` through the final candle), all Python factor results, daily score summaries, and the official range average to OpenAI. The short journal uses **Range recap**, **Agreement and conflict**, **Directional consensus**, and **Concerns**. Its official figures and bias are rendered from Python results. The detailed tables show every range candle and scroll within bounded panels. The evaluation identifies this mode with `analysis_kind="custom_range"`, `rule_set.scope="custom_range"`, and `summary.method="range_average"`. The saved evaluation records the per-candle rule version in `rule_set.version`.

Click **Save journal** to add the result to **Saved custom journals**. That library lists date ranges and their stored market returns, with 20 entries per page. Opening an entry reuses its saved evidence without contacting either provider. Editing or restoring the text requires **Save changes**. The daily calendar and custom library have independent entries and deletion actions, while both use the existing SQLite database. Switching pages preserves current form inputs and unsaved journal edits; refreshing the page loses unsaved browser state.

## Interactive market chart

Daily journals, custom-range journals and Today include a three-panel chart using TradingView Lightweight Charts 5.3.0. The price panel overlays EMA20 and SMA190 on H4 candles. The other panels show RSI14 with its SMA14 smoothing and the saved LazyBear Squeeze Momentum histogram. Raw RSI14 is visible by default alongside the smoothed line. The RSI panel automatically fits the visible RSI data with a little edge padding. These display settings do not change the saved strategy thresholds or calculations. Chart values come from the market snapshot; the browser does not recalculate indicators or strategy scores.

Click or tap a candle, use the selected-candle dropdown or arrow buttons, or select a time in the strategy table. The details card shows prices, indicator readings, squeeze state and saved Python factor results. The matching strategy row is highlighted. Drag horizontally or use the zoom buttons/pinch gesture. **Session only** (or **Range only**) focuses the reviewed candles; **All history** restores the saved context. Each newly opened chart starts with all available history plus one zoom-out step for extra space. Today data refreshes preserve any zoom or pan changes you make afterward. A purple band marks the analyzed period. Time labels use America/New_York, including daylight saving time. RSI guides follow the saved rule version, and missing indicator values remain gaps.

New snapshots retain the last **60 completed warmup H4 candles** in an optional `chart_context` field. These are calculated in the existing indicator pass and require no additional OANDA request. They are for display only and are excluded from AI input and session/range scores. The two predecessor candles used for strategy rules remain unchanged. Saving preserves the chart history with the original evidence in SQLite; no database migration is needed. Older journals display their available saved history without fetching or recomputing it.

Today refreshes the chart alongside completed-candle data while preserving the chart's visible range. Forming and upcoming candles remain pending in the session slots. Before the first completed candle, the existing waiting state remains. The chart includes no provisional OHLC prices. Opening a chart or selecting a candle makes no OpenAI calls.

The chart code loads when a market review is opened. TradingView attribution and a link appear below the chart. Full candle and strategy tables remain available for keyboard access and detailed evidence.

## Trade setup evaluator

Open **Evaluate setup** in the sidebar:

1. Choose a proposed direction and either **Now** or a historical cutoff. Historical times use the device timezone shown beside the input.
2. Optionally **Load chart**, choose **Draw support** or **Draw resistance**, then click/tap two price boundaries on the price pane. Green/red bands fill the zone fields below. Edit exact prices and names there, or remove a draft zone. **Cancel drawing** (or Escape) cancels the active tool. Manual price entry remains available without a preview; up to eight zones are allowed, with five decimal places and equal prices for a single level.
3. Optionally **Pick origin … on chart** and select an H4 candle, or enter **Origin time** in the displayed device timezone, to analyze a zone's history. Drawing price boundaries does not infer its origin. Without an origin the band spans the displayed evidence and history remains unknown. H4/D1/W1 describes the chart on which you identified the zone, not an additional data feed. Add your chart observations below.
4. Optionally enter a **Trade plan**: planned entry, stop loss and take profit. Enter all three prices or leave all three blank. Long plans require stop < entry < target; short plans require target < entry < stop. Prices support five decimal places. **Capture setup** saves a fixed snapshot before any OpenAI request. It includes the completed H4 candles, all 300 warmup candles used in calculation, indicators/settings, strategy version/revision and results, source-code fingerprint, manual inputs, quote status, cutoff and retrieval timestamps. The saved plan card then shows Python's pip distances and reward-to-risk calculation.
5. **Generate AI assessment** interprets that snapshot. It presents support, conflicts, zone context, possible future conditions and missing confirmation. The existing strategy scores remain Python-owned and unchanged. A repeat assessment creates a separate record against the same snapshot; capture a new setup to use newer market data.
6. Reopen saved setups on the same page. Captures and completed/failed AI records cannot be edited. Corrections should be captured as a new setup. Use **Delete** on a saved setup or **Delete setup** in its opened view, then confirm **Delete permanently**, to remove that setup and all its assessments. The confirmation identifies the title, direction and evidence cutoff. Your current form, journals and strategy profiles are kept.

**Fixed chart preview:** loading the chart saves temporary server-owned evidence. Capture reuses those exact candles, indicator values, scores, strategy version and quote without fetching newer prices or recalculating the strategy. Zone geometry/history and optional trade-plan calculations are added from the supplied annotations. The browser sends inputs and a preview ID, never trusted market values. **Refresh chart** deliberately replaces the preview and keeps your draft zones and plan. Changing the mode, cutoff or quote option requires loading a new preview; editing the plan does not. Finalization time is recorded separately; annotations made after loading are labelled accordingly. Preview capture is rejected if the calculation code changed or the preview expired. The preview includes 300 earlier OHLC candles; indicator lines cover the recent 60 context candles and reviewed session.

**Optional trade plan:** `trade_plan.py` uses Decimal arithmetic and EUR/USD's 0.0001 pip size. Risk distance is `abs(entry - stop) / 0.0001`; potential reward is `abs(target - entry) / 0.0001`; reward-to-risk is reward divided by risk. A long plan at 1.10000 with stop 1.09800 and target 1.10400 has 20.0 pips of risk distance and 40.0 pips of potential reward, or 2.00:1. The equivalent short example uses stop 1.10200 and target 1.09600. Python also records each planned level's above/inside/below position relative to supplied zones; exact edges count as inside.

The plan, version `trade_plan_v1`, assumptions and calculated values are saved immutably with the setup. These are proposed price distances, not executed prices, monetary risk, position sizing or guaranteed fills. Spread, commission, financing and slippage are excluded. There is no minimum reward-to-risk rule and the ratio adds no strategy points. The AI must include the plan as context, cannot label it as a scoring factor, invent replacement levels or infer win probability from the ratio. Historical plans remain retrospective user annotations, never evidence that the levels were known or traded at the cutoff. Old snapshots stay unchanged; capture a new setup to add or revise a plan. No database migration, endpoint or dependency is added.

Only candles whose close is at or before the cutoff can affect prices, indicators or scores. Session-to-date averages and latest-candle results remain separate. Before the first current-session candle closes, the evaluator explicitly shows the previous completed session as context. Weekends use the most recent completed session. Historical captures are labelled reconstructions: today's provider history and zones entered later cannot prove exactly what was available or known then.

For **Now**, the optional read-only OANDA practice pricing request can add a tradeable bid/ask quote no older than 120 seconds at the evidence cutoff (chart load when using a preview). It stays frozen while you annotate; refresh the chart explicitly for a newer quote. Its midpoint is used only for zone proximity; it does not enter strategy calculations or represent an execution price. An unavailable, stale, malformed or future-dated quote falls back to the last completed H4 close. Historical captures never request a current quote.

Python computes above/inside/below relationships, nearest-edge distances in EUR/USD pips, last-close positions and candle-range overlaps. Zones and notes remain user observations. New snapshots also evaluate the candle rules below. A rule match records what happened at a particular close, not a forecast or ongoing confirmation. Suggested invalidation scenarios are conditional checks against supplied zone boundaries, not mandatory rules or automated exit instructions. No orders, backtest, win-probability estimate or discipline grading is included.

**Historical zone evidence:** new captures use `zone_history_v1`, `zone_patterns_v1`, and snapshot schema 4. `zone_history.py` examines the already-saved 300 warmup candles plus the completed session; it makes no extra OANDA request. Only whole H4 candles opening at or after the origin and closing at or before the cutoff are eligible. The origin remains a user annotation, not independently verified formation time or proof that the zone was known then.

A visit is a consecutive group of candles whose ranges overlap the zone, including equality at its edges. It is not a count of individual intrabar touches. Normal weekend closures, including DST weekends, preserve consecutive trading candles. Missing candles split groups and mark coverage partial; groups on either side of a gap might be the same real interaction. A group starting at the observation boundary is marked with an asterisk because it may have begun earlier.

The stored history includes observed groups, counts of closes above/inside/below, and events when the observed close position changes. A gap directly from below to above does not imply that the zone was touched. Followup movement is measured from the last overlap close across up to the next three completed non-overlapping candles, stopping at a new visit, unexpected gap or cutoff. Signed close change and the observed high/low excursions are price observations, not trade returns or confirmation labels. Ongoing visits have no followup yet; missing observations are never converted to zero.

Origins older than available history show **Partial history** with the actual observed window. No origin or no eligible completed candles shows unknown history rather than zero visits. The AI receives totals, coverage limits and the latest three visits/close-position changes per zone; complete event lists remain in the snapshot and UI. These facts remain context and add no four-factor points. The prompt is versioned separately as `setup_review_v4_trade_plan`.

**Rejection, breakout and retest rules:** `zone_patterns.py` uses exact drawn boundaries (zero buffer) and completed H4 candles only. Edge contact counts as a touch; an exact-edge close remains inside. There is no candle-colour, wick/body-ratio, volume or extra indicator requirement. Original zone labels remain fixed:

- **Bullish support rejection:** the previous close is above the upper edge; the next candle's range overlaps the zone and it closes above the upper edge again. Bearish resistance rejection mirrors this below the lower edge.
- **Bullish resistance breakout:** the previous close is inside/below and the next close is above the upper edge. Bearish support breakout mirrors this below the lower edge. One close is sufficient; a wick is not. Already-outside consecutive closes are not repeated breakout events. A gap in price does not prove intrabar contact.
- **Retest held:** on a later candle within the next six completed trading candles, the previous close is on the breakout side, the candle overlaps the broken zone, and it closes on that same side. The breakout candle itself cannot be its retest. An inside close keeps the attempt pending; recovery from inside alone is not a held retest and does not reset its clock.
- **Attempt invalidated:** before a hold, a completed close beyond the zone's opposite edge ends the attempt. An inside/edge close does not. Six completed candles without a hold means **Window ended without hold**, not invalidation or a trade loss. The sixth candle can qualify; the seventh cannot qualify for that attempt.

A held retest is a dated event, not a promise that price will stay on that side. Later movement does not rewrite its past result. Missing source candles interrupt pending attempts and block cross-gap pattern inference; normal weekend closures, including DST transitions, preserve trading-candle sequence. No origin or no adjacent completed pair yields unknown pattern evidence. Every event includes the prior/event candles, timestamps, direction and deterministic explanation; every breakout stores its retest-window outcome. Rule settings and source-code version are frozen with the setup. The preview and manual-capture flows use the same analyzer without altering four-factor calculations.

**Price-action rules** in Zone history shows the latest observed match, the latest retest attempt, all events with candle evidence, and clickable chart markers (REJ/BRK/RT). The AI gets bounded summaries of the latest three events/attempts per zone. Only a directional match on the latest completed candle can be a supporting/conflicting fact; older matches and invalidated attempts remain context. The AI may cite saved facts but cannot add pattern points or change labels. Existing snapshots remain unchanged and show their saved evidence; capture a new setup with an origin to add these rules. No database migration or new packages are needed for this refinement.

**Zone history** above the chart lets you select a zone, inspect visit groups and close-position changes, and jump to an event candle. **Zone window** fits the chart to that zone's observed history. Gold lines show the supplied boundaries over the observed window; markers show the history start and visit starts. Close-position markers are optional. Setup charts with dated zones can show all 300 saved earlier OHLC candles; saved indicator readings still cover the latest 60 context candles and reviewed session, with older readings left unavailable. Ordinary journal charts retain their existing history and behavior.

Existing saved setups remain unchanged. Their historical evidence is not recomputed on reopening or reassessment. Capture a new setup to add an origin or obtain history analysis. Zone history needs no additional packages.

The AI receives a bounded catalog of those facts, the saved strategy definition and observations. Strict structured output selects existing evidence/condition IDs; validation checks roles, duplicate/unknown IDs, missing conflicts/zone/plan context and incomplete strategy data. Python supplies displayed numbers. Numeric inventions, malformed/refused/incomplete responses are rejected. Qualitative wording is still an LLM interpretation and should be reviewed against the evidence; schema validation alone cannot prove every sentence's meaning.

The additive SQLite migration runs on backend startup and creates a consistent backup next to the configured database named `<database>.before-setup-v1-<id>.db` before its first run. It adds `setup_snapshots`, `setup_evaluations` and migration tracking, without rewriting saved journals. Snapshot hashes detect changed evidence; database triggers prevent evidence edits and deletion outside the explicit setup-removal transaction. Keep both the database and backup on the persistent Render disk. Backups have the same private data as the original database and are not served by the app.

The chart feature adds migration 2 on startup: a `setup_previews` table with hashes and a trigger preventing evidence updates. Previews expire after 24 hours; new loads prune expired rows and retain at most 50 previews. Captured setups contain their own permanent copy and survive preview cleanup. Preview creation does not call OpenAI or add a saved setup.

Setup deletion adds migration 3 on startup. One transaction removes the snapshot (including zones and the optional plan) and every assessment. A running assessment blocks deletion with HTTP 409; an interrupted pending attempt older than five minutes can be removed. Deletion and assessment reservation serialize in SQLite, and a late result cannot recreate a deleted record. A minimal `setup_deletions` record retains only setup ID, capture request ID and deletion time to reject delayed capture retries; no evidence, names or AI content is retained there. Repeating a successful DELETE returns 204. Unknown IDs return 404. Existing immutable-update guards remain. Independent chart previews follow their normal expiry; existing backups are not rewritten. No new dependencies are required.

The API provides `POST /setup-previews`, `POST/GET /setup-snapshots`, `DELETE /setup-snapshots/{id}`, `GET /setup-snapshots/{id}`, and `POST /setup-snapshots/{id}/evaluate`. Capture accepts an optional `preview_id`; omitting it retains the manual-input workflow. Write requests use client UUIDs for safe retries; overlapping AI attempts for the same snapshot are rejected, and interrupted attempts can be retried after five minutes. AI failures retain their saved evidence. The hosted app applies its existing authentication and same-origin write checks to these routes. Development continues to use the local API.

Implementation is separated into `setup_models.py` (inputs), `setup_market.py` (cutoffs and deterministic geometry), `trade_plan.py` (planned pip distances and zone positions), `setup_database.py` (durable records), `setup_ai.py` (schema/catalog/validation), `setup_api.py` (routes), and `SetupEvaluator.jsx` (UI). No new packages are required. Setup assessments use the configured OpenAI model with medium reasoning, no automatic retries, a 90-second timeout, and a 6,000-token budget.

Offline regression checks include historical/future boundaries, daylight saving time/weekends, unchanged scoring, quote validation, zone edges, immutable storage, migration backup, idempotency, failure recovery, AI references and the hosted access boundary. Chart checks cover drawing coordinates, origin selection, numeric edits, preview capture without a refetch, frozen live quotes, expiration/eviction, migration compatibility, client evidence injection, exact long/short plan arithmetic, invalid/partial plans, legacy retries and saved plan AI context:

```bash
cd backend
python -B -m unittest discover -s tests -t .
cd ../frontend
node --test tests/*.test.js
npm run lint
npm run build
```

## Manual trade log

Open a saved setup and choose **Record trade** to retain its strategy calculations, applicable strategy version, zones, market evidence and proposed plan with the trade. If there is a proposed plan, its prices prefill the form: verify the actual entry fill and initial stop/target you used. Entry time and reason must be entered explicitly. Alternatively, use **Trades → Record trade** for a manual entry without a market snapshot. This version supports EUR/USD H4, one entry and one full exit, with no order execution. Recording or reopening a trade makes no provider calls; historical reconstruction is an explicit OANDA action.

Record direction, actual entry price/time and your entry reason. Name, initial stop, initial target and support/resistance observations are optional. A missing stop or target remains missing; no level is inferred. Times are entered in your device's displayed timezone and stored as UTC. Future timestamps and exits before entry are rejected. Entry details and full exits are fixed after saving, so check them before submitting. Editing/deleting trades, partial exits, position sizing and automatic outcome detection are outside this first version.

For a linked trade, the backend copies the server-owned setup inside the same transaction as the trade save. The setup cutoff must be at or before entry; all retained candles and reference times must be at or before that cutoff. The entry copy is hashed, never refreshed, and survives deletion of the original setup. A live setup captured and finalized before entry is labeled **Setup captured before entry**. Historical reconstructions or setups saved after entry are labeled **Retrospective context** and do not establish what was known at entry. Manually entered reasoning and observations are self-reported and may have been logged later. AI assessments are not copied; this first version preserves the underlying setup evidence and proposed plan.

After the position is closed, enter the actual full exit price/time. Python calculates signed pips with Decimal arithmetic: `(exit - entry) / 0.0001` for a long trade, reversed for a short. R is signed pips divided by the original entry-to-stop distance in pips. For example, a long entry at 1.10000, initial stop at 1.09800 and actual exit at 1.09900 records **−10.0 pips / −0.50 R**. A missing initial stop leaves R unavailable. Actual exit fills can exceed a stop or target; results are never capped to planned levels. Pips and R describe price movement using entered fills; separate commissions, financing and fees are not deducted, and monetary P&L is not calculated.

**Trading discipline** is a separate self-review: Not reviewed, Followed my plan, or Deviated from my plan, with notes. No mandatory checklist has been defined yet, so the app does not infer compliance from strategy bias, score or outcome. A losing trade can correctly remain **Followed my plan**. Updated reviews append to the history; a stale browser cannot overwrite a newer review. AI discipline reviews can be added after this log contains useful evidence and personal rules have been defined.

An additive migration runs on startup and creates `trades`, `trade_exits`, `trade_reviews` and `trade_schema_migrations` in the existing SQLite database. Entries/exits are immutable, reviews append, and all mutations use transactions and request IDs to prevent duplicate saves. No existing tables, strategies, credentials or dependencies change. Hosted routes use the existing login and same-origin write protections. Keep the database on the configured persistent disk and include it in normal backups.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/trades` | Save an entry and optional independent setup copy |
| GET | `/trades?status=all&limit=20&offset=0` | List trades; status can also be open or closed |
| GET | `/trades/{id}` | Reopen saved entry, evidence, exit and review history |
| POST | `/trades/{id}/close` | Save one actual full exit and Python outcome |
| POST | `/trades/{id}/reviews` | Append a self-review using the expected review revision |

Offline tests cover long/short/flat and fractional results, missing stops, entry/exit validation, duplicate requests, concurrent setup deletion, snapshot preservation, future-data rejection, review conflicts, immutability, restart persistence, migration compatibility, hosted authentication and same-origin protections. Frontend checks cover setup handoff, input validation, timezone ordering and separation of outcome from discipline.

## Four-factor trade comparison

The **Trades** page compares the recorded long/short direction with Python's four-factor results. New trades linked to a setup save this comparison automatically, using the immutable entry copy. Older linked trades can choose **Compare saved setup**, even if the original setup has since been deleted. A trade's actual direction takes precedence over the setup's proposed direction. Bullish factors support long trades and conflict with short trades; bearish factors reverse that relationship. Neutral and unavailable remain distinct. No minimum score, pass/fail rule, discipline grade, win probability or new strategy points are introduced.

The comparison shows each factor's **latest completed H4 result**, its existing point reduction/reason, and separate supporting/conflicting averages across all reviewed session candles. A factor can support some candles and conflict on others. Every completed candle has equal weight; pending slots are excluded rather than counted as zero. An unavailable factor withholds that factor's averages; any unavailable input withholds the overall session average. The saved overall scoring method, version and weights remain intact, including legacy final-candle summaries. Per-candle reasons and the original market chart remain available.

**Evidence timing:** entry time, evidence cutoff, last completed candle and its age are shown separately. Python compares the last close with the scheduled H4 boundary at entry, including New York rollover, weekends and daylight saving. Older evidence is flagged when it stops before that boundary; this check is not a claim that a holiday/provider candle exists. Earlier-session context is explicitly labeled. Before the first H4 close, the previous completed session supplies context rather than six fictional current-session results.

**Reconstruct at entry** retrieves historical OANDA data using the exact immutable entry timestamp and the current four-factor version at reconstruction time. Only completed H4 candles ending at or before entry can affect indicators, scores or retained history; no current quote is requested. The saved comparison records its strategy version and is labeled retrospective. It cannot establish which rules, unrevised provider prices or discretionary observations were known at entry. No zones, trade plan, exit price, outcome or later review notes are supplied to this reconstruction. Original setup evidence and observations remain separate and unchanged.

The first successful reconstruction is retained; reopening or repeating the action reuses it without another provider request. Provider failure leaves the trade and original evidence unchanged and permits a retry. Missing history, incomplete candles and provider gaps fail visibly. Setup-based and reconstructed comparisons are independent selectable views, with an immutable copy of the reconstruction's market inputs, indicators and results. This phase provides deterministic comparison only; AI trade commentary and multi-trade reviews remain later work.

Migration **trade v2** adds `trade_strategy_analyses`, with one immutable record per trade/evidence source, a payload hash bound to the original entry-evidence hash, and update/delete guards. It leaves existing entries, exits, reviews and setup snapshots untouched. `POST /trades/{id}/strategy-analysis` accepts only a request UUID and `source` (`saved_setup` or `entry_time`); the server owns the recorded direction and cutoff. Long provider requests run outside database write transactions; concurrent completions store one result and cannot replace it. Existing hosted authentication and same-origin protections cover the endpoint.

Offline tests cover actual long/short direction, mixed session histories, missing versus neutral readings, reduced points, saved rule versions, future-data rejection, exact H4 cutoffs, rollover/weekend/DST timing, immutable reconstruction, old trades, source deletion, provider failure/retry, concurrent requests, request conflicts and authenticated same-origin access. Market and strategy calculations are unchanged.

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

The **Generate journal** form groups session settings, strategy rules, and optional observations into separate panels. Session settings show the fixed EUR/USD pair, 4-hour timeframe, and 5 p.m.–5 p.m. New York window. **Strategy evaluation** defaults to **Four-factor strategy v7 · Session average**. Its fixed definitions are loaded from the backend. **Written strategy · AI review** retains the editable text workflow without calculated points. **Saved strategies** opens Strategy profiles, where **Use in journal** copies the saved rules and evaluation method into the form. Written copies can be customized; scored rules remain fixed for their version. The rule and note fields show their existing 10,000-character limits.

Generation disables the form controls and shows a waiting message. Required-field and generation errors appear beside the Generate button, while your inputs remain available for correction or retry. A successful request opens the journal reading view below the form.

1. The frontend sends the selected date, strategy, optional observations, and selected `rule_set_id` to the backend. For a scored request, the backend replaces client-supplied rule text with the canonical definitions for that version.
2. The backend fetches OANDA candles, validates the session, and calculates indicators using earlier history. It excludes candles that finish after the session cutoff.
3. `journal_grounding.py` builds a session-specific catalogue labeled `C1` through `C6`. The market snapshot also retains two preceding completed trading candles (`previous_candles`, labeled `P-1` then `P0` in scored evidence). The `previous_candle` field remains an alias of P0 for earlier consumers. The remaining warmup candles are used for indicator calculation rather than sent individually to OpenAI.
4. For the scored strategy, `strategy_rules.py` evaluates all four factors on each candle and calculates points and bias. OpenAI receives the complete market snapshot, evidence catalogue, Python evaluation and a compact `summary_context` derived from the actual session candles. It returns four short commentary sections with references to calculated results. `scored_journal.py` rejects mismatched price direction, scoring method, overall bias or final-candle bias, as well as invalid references, invented figures and oversized responses. Python inserts the actual price change and official consensus figures. The AI cannot award points or override the calculated direction; its qualitative interpretation still needs review. For written strategies, the original grounded AI interpretation continues to select assessments and bias.
5. A valid draft, its original market evidence, and any rule evaluation are staged in SQLite. Clicking **Save journal** creates a saved journal. Later text edits preserve the original draft, strategy, market snapshot and calculated results.

Reopening a saved journal uses its stored snapshot without fetching OANDA data or generating another AI response. Updating a strategy profile does not change the strategy stored in an older journal. Candle labels are generated for each session; they are not separate database candle IDs.

The **Strategy profiles** page places the saved-profile library beside a larger rule editor. Each profile explicitly stores its evaluation method. Existing profiles retain their saved method and rule version. The evaluation selector offers only **Four-factor strategy v7 · Session average** and **Written strategy · AI review**. Existing v1/v2/v3/v4/v5/v6 profiles remain visible and retain their saved rules. Edit one and explicitly choose a current method before saving or reusing it; it is never silently converted. The backend retains legacy handling for existing clients and stored records, while its current preset catalogue lists only v7. The selected profile is highlighted, character counts show the existing limits, and an unsaved-changes label distinguishes edits from saved rules. **New profile** and **Edit** move focus to the editor. On smaller screens the library and form stack vertically. Save feedback appears beside the form actions; switching pages keeps your edits, and **Use in journal** copies only saved rules and their evaluation method.

Generated and saved journals share a reading view with a dated session header, market price summary, and clearly separated journal sections. Use **Edit** to change the original text and **Read** to preview it; switching modes does not save or rewrite the journal. **Save journal** saves a new draft, while **Save changes** updates an existing entry. **Restore AI draft** restores the original text in the editor and still requires saving. Opening a journal brings its header into view; **Back to calendar** returns to the selected saved date without discarding edits.

New scored journals use a short summary: **Session recap**, **Agreement and conflict**, **Directional consensus**, and **Concerns**. The prompt targets roughly 150–200 words including server-rendered facts; AI explanations have a combined 160-word maximum. The narrative distinguishes actual price movement, the selected rule version’s consensus, and any separate final-candle change. Detailed candle evidence, indicator values, factor outcomes and rules remain in their existing tables and disclosures rather than being repeated in the text. Short summaries use the full reading width without a section sidebar. Older saved or pending journals retain their original text; generate a new journal to use the new format. Written-strategy AI review keeps its existing grounded format.

Expand **Strategy & observations** to review the session inputs, or **View all six candles and indicators** for the market table. The table retains open/close time ranges, open and close prices, percentage changes, and five-decimal momentum values. On narrow screens the table scrolls within its panel. Older journals without snapshots keep their readable text. The reading view formats known journal headings and Markdown-style headings while displaying other content as plain text; it does not execute embedded HTML or turn journal content into links.

The scored mode calculates the official decisions deterministically. AI prose remains commentary and can still need review; it cannot replace the separate calculated-results panel. In written/AI mode, grounding binds evidence values but does not prove the AI's rule interpretation. User text edits are saved separately from the original draft and are not checked by the generation-time grounding rules.

## Four-factor strategy v7

Each factor awards up to its weight to at most one side per completed candle. All comparisons use unrounded values. The default scored preset is `four_factor_v7`. New v7 results use rule revision 1; the session summary averages all six candles equally. EMA20 vs SMA190 earns **1 directional point when its absolute gap is 60 pips or less**, including exactly 60, and **2 points when larger**; each of the other three factors is worth at most one point. The momentum factor is reduced to half a point during a qualifying slowdown.

| Factor | Weight | Bullish condition | Bearish condition |
| --- | ---: | --- | --- |
| Two closes vs EMA20 | 1 | Current and previous completed trading candles each close strictly above their own EMA20 | Both close strictly below their own EMA20 |
| EMA20 vs SMA190 | Up to 2 | EMA20 > SMA190: 1 point for a gap ≤60 pips; 2 for >60 | EMA20 < SMA190: 1 point for a gap ≤60 pips; 2 for >60 |
| RSI-based MA thresholds and trend | Up to 1 | MA ≤40 earns 1. Inside 40–60, three strictly rising readings earn 1; reduce to 0.5 when 56 ≤ MA <60 | MA ≥60 earns 1. Inside 40–60, three strictly falling readings earn 1; reduce to 0.5 when 40 < MA ≤44 |
| Momentum direction and pace | Up to 1 | Rising on either side of zero: 1 point; 0.5 if slowing | Falling on either side of zero: 1 point; 0.5 if slowing |

For EUR/USD, one pip is 0.0001, so 60 pips is an absolute price gap of 0.0060. The comparison uses the full stored indicator values, converted to decimal before subtracting to avoid binary subtraction artifacts at exactly 60. Display rounding does not decide the result. Equal EMA/SMA values earn zero; missing inputs are unavailable. The five-point maximum and alignment denominator stay fixed when EMA/SMA is reduced. The table labels the gap condition and shows its value in factor evidence; the information icon explains the saved rule. This revision applies to newly generated daily, Today and custom-range results.

In v6 and v7, **every RSI threshold and trend comparison uses SMA14 of RSI14**, stored as `rsi14_sma14`. This is a simple average of fourteen consecutive Wilder RSI14 readings, not RSI computed from smoothed prices. It includes the current completed candle and uses continuous warmup history across sessions and weekends. Values stay unrounded for scoring; both raw RSI14 and its MA display to two decimals. Missing readings are not replaced or skipped: a full fourteen-reading window is required. For ordinary history, the first MA needs 28 closes. The existing 300-candle warmup remains sufficient. Smoothing responds more slowly to changes and does not guarantee better forecasts.

RSI-based MA thresholds take priority based on the **current** completed candle: ≤40 earns one bullish point and ≥60 earns one bearish point, even if the RSI-based MA trend points the other way. Strictly between those thresholds, compare the two previous completed readings with the current one: `older < previous < current` earns up to one bullish point and `older > previous > current` earns up to one bearish point. Earlier readings may be outside the 40–60 band. Equal pairs or mixed directions earn no point. Invalid/missing current RSI-based MA is unavailable; missing or nonconsecutive earlier MA makes an in-band trend unavailable but does not prevent a valid current threshold decision. This is a three-reading trend, not confirmed swing highs/lows or price divergence. The single RSI factor is capped at one point. Saved `rsi_signal.source="rsi14_sma14"` identifies the smoothed series; `rsi_signal.basis` distinguishes thresholds from rising/falling/mixed trends, and the UI and AI explanations use that basis.

In v7, threshold proximity reduces only a confirmed trend point: **56 ≤ MA <60 and rising earns 0.5 bullish points**, while **40 < MA ≤44 and falling earns 0.5 bearish points**. Both require the same three strictly consecutive MA readings. Exactly 56 and 44 qualify; exactly 60 and 40 use the full threshold point instead. Falling MA near 60 and rising MA near 40 keep their full trend points. Mixed/equal readings earn zero, and missing history stays unavailable. The reduction never awards the opposite side a point. `rsi_signal.reduced` and `rsi_signal.proximity` record why; the UI shows “near overbought” or “near oversold” and the AI receives the authoritative result. All completed candles still contribute equally, using the unchanged five-point maximum. The reduction describes proximity, not confirmed reversal, momentum slowdown, or consolidation.

Squeeze ON is already available as volatility-compression context. It is not a fifth scored factor and does not identify breakout direction.

Momentum direction follows the latest delta, independent of its sign: positive/falling is bearish and negative/rising is bullish. Unchanged momentum is neutral. A move to exactly zero still earns the directional point and resets the pace comparison. The proposed ±0.0025/near-zero factor is not included.

Momentum pace uses exactly **three consecutive completed trading candles**, producing two deltas: `previous − older` and `current − previous`. When all three values stay strictly on the same side of zero and both deltas have the same direction, a smaller latest delta magnitude reduces that direction's point to **0.5**. This applies to all four sign/direction combinations. For example, 0.00300 → 0.00200 → 0.00150 has deltas −0.00100 → −0.00050 and earns half a bearish point; −0.00300 → −0.00200 → −0.00150 earns half a bullish point. Slowing does not award an opposite-side point or establish a reversal.

Equal delta magnitudes retain the full point and display **Steady pace**; larger magnitudes display **Accelerating**. A newly qualifying directional move retains the full point if the preceding delta was zero or in the other direction. A zero touch or crossing anywhere in the three-value window displays **Zero-crossing reset** and resets the slowdown comparison; the base direction can still earn its point. Missing or nonconsecutive three-candle history makes the v3/v4/v5/v6/v7 momentum factor unavailable, with no assumed full point. The regular weekend break is allowed, including daylight-saving transitions. Only current and past candles are used.

A numerical equality tolerance (`rel_tol=1e-9`, `abs_tol=1e-12`) avoids false slowdown labels caused by floating-point subtraction. This is not a market-noise filter: other decreases count, and a broader minimum-change threshold has not been introduced. The rule definition stores the lookback, reduced points, and tolerance. The result stores the original momentum values, both deltas, movement and pace labels, and awarded points. The table shows **Slowing** beside the half-point result; expanded evidence shows the deltas to five decimals. Tiny differences can therefore affect the rule while looking equal after display rounding.

The consecutive-close rule uses a rolling pair: a longer streak still earns only one point on each candle. A previous candle must directly precede the current candle, except for the regular Friday 5 p.m. to Sunday 5 p.m. New York market break. Missing or invalid predecessor context makes affected factors unavailable; no missing bars are invented.

For each candle, bullish and bearish totals are each shown out of **five possible points**, across **four factors**. Alignment is `weighted points / 5 × 100`, with neutral and unavailable factor counts shown separately. For example, with an EMA/SMA gap greater than 60 pips, bullish EMA/SMA and consecutive closes with bearish RSI and neutral momentum give 3 bullish points, 1 bearish point and 1 neutral factor: 60% bullish alignment and 20% bearish alignment. A bullish EMA/SMA condition with a gap greater than 60 pips (2), bullish consecutive closes (1), slowing bullish momentum (0.5), and neutral RSI produce 3.5/5 = 70% bullish alignment. With the same conditions but an EMA/SMA gap of 60 pips or less, the total is 2.5/5 = 50%. The four-factor coverage count is separate from the five-point maximum; reduced-point factors are reported separately from neutral or unavailable factors. Net score is bullish minus bearish. With all four factors evaluated, the larger total sets the directional lean; an equal nonzero total is mixed and zero/zero is neutral. Incomplete coverage withholds the directional label. These percentages measure rule alignment, not a calibrated likelihood of future price movement.

Every session shows all six individual candle scores. In v4 through v7, **session-average bullish points** are the sum of C1–C6 bullish points divided by six; bearish points are averaged separately. Each candle has equal weight, including reduced EMA/SMA and half-point momentum outcomes. The maximum average remains **5**, and alignment is average points divided by five, multiplied by 100. Net is the session's bullish-minus-bearish total divided by six. The larger average sets the overall lean; equal nonzero averages are mixed and zero/zero is neutral. Calculations and stored values stay unrounded; summary points, net and alignment display two decimals.

The smaller **Session-end bias** label reports **C6 only**, separately from the session average. For example, candle scores of 5/0, 5/0, 5/0, 5/0, 0/4 and 0/5 produce average bullish 3.33/5 (66.67%), average bearish 1.50/5 (30.00%), net +1.83 and a bullish session lean, while the session-end label is bearish. This preserves the late change in direction without giving the final candle extra weight. Price direction remains the observed session return.

Session coverage counts **24 factor checks** (four on each of six candles). Neutral and reduced-point outcomes are available evaluations, but any unavailable input makes the session average **Incomplete**. In that case average bullish/bearish points, net and alignment percentages are stored as null and displayed as unavailable, not zero; incomplete candles are never silently excluded from the denominator. Individual candle results remain visible, and C6 can still supply a session-end label when its own inputs are complete. The server sends both the session average and the separate session-end result to the AI, and renders their official values in the journal itself.

The v7 evaluation retains schema version 1 with `summary.method="session_average"`, session coverage metadata, and a separate `session_end` object. Existing final-candle summaries keep their original shape. The evidence disclosure shows the required current and preceding inputs; momentum, deltas and prices display five decimals. The Price change % column after Bias uses each candle’s stored open-to-close price change. Scores and raw inputs are stored with the full rule definition/version and are not recalculated when a journal is reopened.

Version 1 retains RSI 30/70 and one point per factor (four possible points). Version 2 retains RSI 40/60 and two-point EMA/SMA weighting, with full momentum points and no slowdown adjustment. Version 3 adds momentum slowdown. These three versions retain C6-only summaries. Version 4 retains its threshold-only RSI, sign-dependent momentum, session averaging and revision-2 EMA/SMA distance weighting. Older saved v4 results without a revision retain their original weights. Version 5 adds the raw-RSI trend fallback and both new momentum directions, keeping the five-point maximum and averaging behavior. Version 7 adds the RSI trend proximity reductions above; version 6 keeps full trend points. Version 6 changes only the RSI source to SMA14 of RSI14 for both checks. Its market snapshot uses schema version 4 and stores separate `rsi` and `rsi_ma` settings; scoring still uses evaluation schema version 1.

Existing profiles, saved journals and pending drafts are never automatically upgraded or recalculated. The selector offers v7 and Written strategy; older profiles remain readable and must explicitly switch to a current method before reuse in the UI. Existing clients can still request older daily rules. New Today and range generation uses v7. Calendar and entry-card averages accept saved v4–v7 results. The renderer, factor badges and help use each journal's stored version, outcomes and definitions.

## Data storage

SQLite data lives at `backend/data/journal.db`. It contains saved daily and custom-range journals, staged generated drafts, and strategy profiles. Custom ranges use the separate `range_journals` and `range_generated_drafts` tables, created automatically on backend startup. Daily and custom IDs can overlap because they refer to different tables and API routes. Existing daily entries, profiles, and pending drafts remain intact. The database is local to this checkout and is ignored by Git; committing or pushing code does not back up your journals. To make a simple file backup, stop the backend and copy the database to a separate location.

**Journal names:** After generation, enter an optional name (up to 120 characters) above the journal evidence, then save. To rename a saved daily, Today or custom-range journal, open it, edit **Journal name**, and choose **Save changes**. Clearing the name restores the journal-number label in saved lists. Names may repeat; IDs and dates still identify entries. Names are plain-text metadata, stored in a separate `title` column and never sent to the AI. Renaming preserves original drafts, evidence, scores and creation dates; it does not reorder the calendar source. Name edits use the same unsaved-change protections as text edits. Existing journals receive an empty name automatically on backend startup, and old pending drafts can still be saved.

Drafts do not appear in **Saved journals** until you click **Save journal**. Unsaved editor changes are held in the browser and can be lost on refresh. Older journals created before market snapshots were added remain readable but have no stored candle evidence.

Backend startup adds nullable score columns to saved journals and staged drafts, and a nullable rule-set identifier to strategy profiles. Existing journals and pending drafts remain readable, with no invented historical scores. Profile changes, deletion, and journal-text edits do not change an already saved rule evaluation.

The calendar groups entries by **journal session date**, not the date you saved them. Its percentage is `(session close - session open) / session open * 100`, using the stored EUR/USD H4 snapshot for the 5 p.m.–5 p.m. New York window. This is market price change, not trade profit or loss. If multiple journals share a date, the day uses the most recently saved usable snapshot; their percentages are never added together. Flat sessions and entries without usable snapshots stay neutral. Dates without saved journals have no percentage, and viewing the calendar makes no OANDA or OpenAI requests.

Each marked date also shows **Avg net** below the percentage: the saved session-average bullish points minus saved session-average bearish points, displayed to two decimals with a sign. The score comes from the **same journal as the percentage**; multiple journals are never averaged together, and a newer written-AI entry does not borrow an older entry’s score. Positive/negative day colors still represent market price change. Zero displays as `0.00`; `—` means no complete session-average score. Written-AI reviews, older final-candle methods, incomplete averages and partial Today snapshots do not supply a daily average. A fully completed Today snapshot can supply it. Older v4 averages remain valid with their recorded rule revision; viewing the calendar never recalculates them. Deleting the source entry selects the next usable snapshot for both fields. The **Selected Date** header repeats that same average and names its source journal. Each entry card also shows its own stored average net score, so entries for the same date can differ. Partial Today entries label their completed-candle average **so far**; they do not supply a full-day calendar average. Missing or incomplete calculated averages stay unavailable rather than becoming zero.

Use the month arrows or **Jump to month** to browse, **Today** to return to the current New York date, and **Latest saved date** to find your most recent journal session. Select a date to see all its entries, with pagination when there are more than 20. The calendar shows every saved date in the month, regardless of that list's page. Calendar days support arrow keys plus Home/End. **Refresh calendar** reloads the displayed month and date after changes in another browser tab or a failed request.

Use **Delete** beside an entry in Saved journals, or **Delete journal** in an open saved entry. The confirmation identifies the journal and warns that deletion cannot be undone. Deletion removes that journal's original draft, saved edits, and market snapshot. If it is open, its editor closes after deletion; other open drafts and strategy profiles are preserved. The calendar and entry list refresh while keeping the selected month and date. If deletion empties the current page, the list moves to the last remaining page. A failed request displays an error, and an entry already deleted in another tab is removed from the stale view when you confirm deletion.

Use **Delete** beside a strategy profile, or **Delete profile** in its editor. The confirmation names the saved profile and warns about unsaved edits if that profile is open. Deletion clears that profile's editor; edits to another profile are kept. Existing journals, staged drafts, and strategy text already copied into the generation form retain their rules. The deleted profile's name is removed from the form's loaded-profile label, and that name can be reused for a new profile. Failed deletion keeps the profile and editor available for retry; confirming deletion of an already deleted profile removes it from the stale view.

## Automated checks

From the repository root, run the backend tests:

```bash
cd backend
./.venv/bin/python -B -m unittest discover -s tests -t . -v
```

All automated backend tests live in `backend/tests/`. Run discovery from `backend` so the application modules and shared test helpers can be imported. To run one file, use its package name, for example:

```bash
./.venv/bin/python -B -m unittest -v tests.test_journal_calendar
```

The current backend suite contains **270 tests**:

| File | Tests | Coverage |
| --- | ---: | --- |
| `tests/test_market_data.py` | 14 | Session boundaries, candle validation, history cutoff, and provider errors |
| `tests/test_journal_evidence.py` | 13 | Saving, immutable original evidence, repeated saves, and older database migration |
| `tests/test_journal_grounding.py` | 19 | Candle references, rendered values/times, structured output, rejected drafts, and the Sol/medium request sent by the SDK |
| `tests/test_journal_deletion.py` | 9 | Deletion, stale requests, isolation, persistence, rollback, pagination, and browser access |
| `tests/test_journal_names.py` | 9 | Daily/range/Today naming, title validation and retries, migrations, unchanged evidence, duplicate names, isolated IDs, and per-entry full/provisional/zero/missing scores |
| `tests/test_journal_calendar.py` | 16 | Monthly counts, date filtering, leap days, saved percentages and average net scores, same-entry selection, zero/missing/invalid scores, historical revisions, partial sessions, pagination and deletion fallback |
| `tests/test_strategy_profiles.py` | 10 | Profile creation, updates, validation, persistence, and journal independence |
| `tests/test_strategy_profile_deletion.py` | 9 | Profile deletion, copied-rule preservation, stale edits, name reuse, rollback, persistence, concurrency, and browser access |
| `tests/test_strategy_rules.py` | 16 | Versioned weights and RSI boundaries, exact comparisons, momentum sign/change, rolling pairs, predecessor context, weekend/DST continuity, missing data, final-candle bias and no future influence |
| `tests/test_scored_journal.py` | 15 | Version upgrades, weighted rendering, canonical presets, AI result boundaries, immutable scores, profile mode changes, migrations, saved/reopened results and concise score rendering |
| `tests/test_momentum_slowdown.py` | 14 | Three-candle deltas, half-points, mirrored bearish behavior, numeric equality, zero-crossing resets, missing history, weekend/DST continuity, old versions and no future influence |
| `tests/test_journal_summary.py` | 8 | Short output, canonical market facts, mismatched directions/method rejection, incomplete averages, word limit, mixed/neutral results and old-text preservation |
| `tests/test_session_average.py` | 14 | Equal averaging, late reversals, half points, missing data, mixed/neutral sessions, legacy methods, canonical AI inputs, profile upgrades and immutable saving |
| `tests/test_custom_range.py` | 23 | Inclusive dates and limits, full-session coverage, continuous indicators, weekends/DST, equal range averaging, global candle references, AI validation, immutable saving, daily/custom isolation, deletion, pagination and startup preservation |
| `tests/test_rsi_ma.py` | 6 | Smoothing precision, warmup, missing readings, causal calculations and daily/Today/range consistency |
| `tests/test_hosted.py` | 4 | Hosted login for the UI and API, health checks, cross-origin write protection, persistence and required deployment settings |
| `tests/test_strategy_v7.py` | 13 | Near-threshold boundaries, strict trend checks, half-point totals across daily/Today/range, AI metadata, calendar scores and saved v6 preservation |
| `tests/test_strategy_v6.py` | 11 | MA versus raw RSI conflicts, thresholds, trends, missing settings/history, version compatibility, AI evidence and saved/calendar results |
| `tests/test_strategy_v5.py` | 17 | RSI threshold priority, strict trends, missing history, all momentum quadrants and slowdown, no future influence, range continuity, AI inputs, saved v4/v5 compatibility and calendar scores |
| `tests/test_ema_distance.py` | 11 | Inclusive 60-pip boundaries in both directions, full precision, missing inputs, fixed denominator, combined reductions, daily/range/Today reuse, AI inputs and immutable historical v4 revisions |
| `tests/test_today.py` | 19 | Empty/partial/full sessions, close boundaries, rollover, weekend/DST history, future-data exclusion, delayed candles, partial grounding and averages, cache expiry, AI snapshot consistency, immutable saving and calendar semantics |

These tests use dummy credentials, simulated provider responses, and temporary databases. They do not make live OANDA/OpenAI requests or change your saved journals. No running backend server or real `.env` is required. Some tests intentionally log an evidence-rejection message; a successful run ends with `Ran 270 tests` and `OK`.

From the repository root, check the frontend:

```bash
cd frontend
node --test tests/*.test.js
npm run lint
npm run build
```

The 39 frontend tests cover date placement, leap years, month/year navigation, New York date boundaries, percentage and signed average-net formatting, version-aware RSI/momentum badges, range validation and preview mapping, Today snapshot consistency/freshness and summary changes, current strategy choices and retired-profile handling, journal-name fallbacks and unsaved-name detection, and preservation of daily/range/intraday journal text. The build writes generated frontend assets to `frontend/dist`. It does not start the backend or publish the app.

The separate `backend/check_oanda.py` and `backend/check_openai.py` scripts are optional **live connection checks**, not part of the automated suite. They use real credentials and contact the providers; the OpenAI check uses API tokens. The OpenAI check uses the configured model with medium reasoning and a smaller 2,048-token limit. It prints the requested and returned model, response status, and usage, and exits with an error for incomplete or empty replies. The OANDA check currently uses the fixed session date 2026-10-20.

## Troubleshooting and limits

- **Cannot connect / Failed to fetch:** confirm the backend is running on port 8000 and open the frontend on port 5173.
- **Session not finished or incomplete:** choose a completed weekday session. Generation needs all six completed candles and enough earlier history.
- **Want an intraday review:** open Today. It scores the completed portion of the active session; daily and custom-range forms still require complete sessions.
- **Today refresh failed or is outdated:** check the backend and retry. An overdue candle may be delayed or absent due to an early market close. A generation snapshot can also expire after 30 minutes or a backend restart; refresh the page's data before generating again.
- **Custom range rejected:** use at most 31 calendar days, include a weekday, and wait until the selected end date's 5 p.m. New York cutoff. Every included weekday needs six completed candles; shorten or move a range that includes missing data or a shortened holiday session.
- **OANDA access error:** check the practice account credentials and required practice API URL in `backend/.env`.
- **AI request failed:** check API access, the configured model, and the error shown by the app. Failed generation does not create a saved journal.
- **AI draft failed its evidence checks:** the generated response failed validation. No new draft was staged; you can try generating again.

This version supports local use on one computer, without user accounts or authentication. It reviews completed sessions and the completed candles within an ongoing session; it does not place orders, provide live entry signals, or run strategy backtests. Historical availability depends on the provider, and the automated tests do not establish that live provider access is working.

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from fastapi.middleware.cors import CORSMiddleware
from datetime import date
from typing import Literal
import os
import json
import logging
from pathlib import Path
from uuid import UUID
from dotenv import load_dotenv
from openai import OpenAI, APIError
from contextlib import asynccontextmanager
from database import (
    init_db, store_generated_draft, save_generated_journal,
    fetch_journal, update_journal_text, delete_journal, fetch_journals, fetch_journal_calendar, DraftAlreadySavedError,
    fetch_strategy_profiles, fetch_strategy_profile, insert_strategy_profile,
    update_strategy_profile, delete_strategy_profile, DuplicateStrategyProfileError,
)
from market_data import MarketDataError, get_market_data
from journal_grounding import (
    JOURNAL_INSTRUCTIONS, InvalidJournalEvidence, build_evidence_catalog,
    render_journal, response_format,
)
from strategy_rules import RULE_SET_ID, ACTIVE_RULE_SET_IDS, RuleSetId, evaluate_strategy, rule_set_definition
from scored_journal import (SCORED_JOURNAL_INSTRUCTIONS, scored_response_format,
                            render_scored_journal, build_summary_context)

from date_range import (MAX_RANGE_DAYS, get_range_market_data, build_range_evidence_catalog,
                        evaluate_range_strategy, range_rule_definition)
from range_database import (init_range_db, store_range_draft, save_range_journal,
                            fetch_range_journal, fetch_range_journals, update_range_journal, delete_range_journal)
from today import get_today_view, load_today_snapshot

load_dotenv(Path(__file__).with_name(".env"))

client = OpenAI(timeout=90.0, max_retries=0)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_range_db()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

class JournalInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    pair: str = Field(min_length=1, max_length=20)
    journal_date: date
    timeframe: Literal["15m", "1h", "4h", "1d"]
    strategy: str = Field(min_length=1, max_length=10000)
    notes: str = Field(default="", max_length=10000)
    rule_set_id: RuleSetId | None = None

class RangeJournalInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    start_date: date
    end_date: date
    pair: Literal["EURUSD"] = "EURUSD"
    timeframe: Literal["4h"] = "4h"
    rule_set_id: Literal["four_factor_v4"] = "four_factor_v4"
    notes: str = Field(default="", max_length=10000)

class TodayJournalInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    snapshot_id: UUID
    notes: str = Field(default="", max_length=10000)

class JournalSaveInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    generation_id: UUID
    edited_draft: str = Field(min_length=1, max_length=20000)

class JournalUpdateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    edited_draft: str = Field(min_length=1, max_length=20000)

class StrategyProfileInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    rules: str = Field(min_length=1, max_length=10000)
    rule_set_id: RuleSetId | None = None

@app.get("/")
def home():
    return {"message": "Forex AI Journal API is running"}


@app.get("/market-data")
def read_market_data(
    journal_date: date = Query(..., description="Session end date in New York, YYYY-MM-DD"),
):
    try:
        return get_market_data(journal_date)
    except MarketDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@app.post("/journal/preview")
def preview_journal(entry: JournalInput):
    if entry.rule_set_id:
        entry = entry.model_copy(update={"strategy": rule_set_definition(entry.rule_set_id)["rules"]})
    return entry.model_dump(mode="json", exclude_none=True)

@app.post("/journal/generate")
def generate_journal(entry: JournalInput):
    normalized_pair = entry.pair.upper().replace("/", "").replace("_", "")
    if normalized_pair != "EURUSD" or entry.timeframe != "4h":
        raise HTTPException(
            status_code=422,
            detail="Market-backed journals currently support EUR/USD with 4-hour candles only.",
        )
    entry = entry.model_copy(update={"pair": "EURUSD"})
    market_data = read_market_data(entry.journal_date)
    if entry.rule_set_id:
        entry = entry.model_copy(update={"strategy": rule_set_definition(entry.rule_set_id)["rules"]})
    entry_data = entry.model_dump(mode="json", exclude_none=True)
    evaluation = None
    try:
        evidence_catalog = build_evidence_catalog(market_data)
        if entry.rule_set_id:
            evaluation = evaluate_strategy(market_data, entry.rule_set_id)
    except InvalidJournalEvidence as exc:
        logger.warning("Journal market evidence rejected: %s", exc)
        raise HTTPException(status_code=502, detail="The market data could not be prepared for journal evidence.") from None
    return _generate_draft(entry_data, market_data, evidence_catalog, evaluation)


def _generate_draft(entry_data, market_data, evidence_catalog, evaluation, *, custom_range=False):
    ai_input = {"entry": entry_data, "market_data": market_data, "evidence_catalog": evidence_catalog}
    if evaluation is not None:
        ai_input["rule_evaluation"] = evaluation
        ai_input["summary_context"] = build_summary_context(market_data, evaluation)
    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-6.1-sol"),
            instructions=SCORED_JOURNAL_INSTRUCTIONS if evaluation is not None else JOURNAL_INSTRUCTIONS,
            input=json.dumps(ai_input, allow_nan=False),
            text={"format": scored_response_format() if evaluation is not None else response_format()},
            reasoning={"effort": "medium"},
            # This budget includes reasoning tokens as well as the structured draft.
            max_output_tokens=8000,
            service_tier="default",
            store=False,
        )
    except APIError:
        raise HTTPException(
            status_code=502,
            detail=(
                "The AI request failed. Check your API connection, "
                "billing, and limits."
            ),
        ) from None

    if response.status != "completed":
        raise HTTPException(
            status_code=502,
            detail="The AI did not return a complete draft. Please try again.",
        )

    try:
        draft = (render_scored_journal(response.output_text, market_data, evaluation)
                 if evaluation is not None else render_journal(response.output_text, market_data, entry_data["strategy"]))
    except InvalidJournalEvidence as exc:
        logger.warning("AI journal evidence rejected: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=(
                "The AI draft failed its evidence checks. No new draft was saved. "
                "Please generate it again."
            ),
        ) from None

    store = store_range_draft if custom_range else store_generated_draft
    generation_id = store(entry_data, draft, market_data, evaluation)
    return {
        "generation_id": generation_id,
        "entry": entry_data,
        "draft": draft,
        "market_data": market_data,
        "rule_evaluation": evaluation,
    }

@app.post("/journals", status_code=201)
def save_journal(payload: JournalSaveInput):
    try:
        journal = save_generated_journal(str(payload.generation_id), payload.edited_draft)
    except DraftAlreadySavedError:
        raise HTTPException(
            status_code=409,
            detail="This draft was already saved. Open it from history to make further edits.",
        ) from None
    if journal is None:
        raise HTTPException(status_code=404, detail="Draft not found. Please generate a new journal.")
    return journal

@app.get("/journals")
def list_journals(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    journal_date: date | None = Query(default=None, description="Filter by the journal's session date"),
):
    return fetch_journals(limit=limit, offset=offset,
                          journal_date=journal_date.isoformat() if journal_date is not None else None)


@app.get("/journals/calendar")
def read_journal_calendar(
    month: str = Query(..., pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$", description="Calendar month, YYYY-MM"),
):
    try:
        return fetch_journal_calendar(month)
    except ValueError:
        raise HTTPException(status_code=422, detail="Choose a valid calendar month.") from None

@app.get("/journals/{journal_id}")
def read_journal(journal_id: int):
    journal = fetch_journal(journal_id)
    if journal is None:
        raise HTTPException(status_code=404, detail="Journal not found.")
    return journal

@app.patch("/journals/{journal_id}")
def update_journal(journal_id: int, payload: JournalUpdateInput):
    journal = update_journal_text(journal_id, payload.edited_draft)

    if journal is None:
        raise HTTPException(status_code=404, detail="Journal not found.")

    return journal


@app.delete("/journals/{journal_id}", status_code=204)
def remove_journal(journal_id: int):
    if not delete_journal(journal_id):
        raise HTTPException(status_code=404, detail="Journal not found.")
    return Response(status_code=204)


@app.get("/strategy-rule-sets")
def list_rule_sets():
    return {"items": [rule_set_definition(rule_id) for rule_id in ACTIVE_RULE_SET_IDS], "default_id": RULE_SET_ID}


@app.get("/strategy-profiles")
def list_strategy_profiles():
    return fetch_strategy_profiles()


@app.get("/strategy-profiles/{profile_id}")
def read_strategy_profile(profile_id: int):
    profile = fetch_strategy_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Strategy profile not found.")
    return profile


@app.post("/strategy-profiles", status_code=201)
def create_strategy_profile(payload: StrategyProfileInput):
    try:
        return insert_strategy_profile(payload.name, rule_set_definition(payload.rule_set_id)["rules"] if payload.rule_set_id else payload.rules, payload.rule_set_id)
    except DuplicateStrategyProfileError:
        raise HTTPException(
            status_code=409,
            detail="A strategy profile with that name already exists. Choose another name.",
        ) from None


@app.delete("/strategy-profiles/{profile_id}", status_code=204)
def remove_strategy_profile(profile_id: int):
    if not delete_strategy_profile(profile_id):
        raise HTTPException(status_code=404, detail="Strategy profile not found.")
    return Response(status_code=204)


@app.patch("/strategy-profiles/{profile_id}")
def edit_strategy_profile(profile_id: int, payload: StrategyProfileInput):
    try:
        profile = update_strategy_profile(profile_id, payload.name, rule_set_definition(payload.rule_set_id)["rules"] if payload.rule_set_id else payload.rules, payload.rule_set_id)
    except DuplicateStrategyProfileError:
        raise HTTPException(
            status_code=409,
            detail="A strategy profile with that name already exists. Choose another name.",
        ) from None
    if profile is None:
        raise HTTPException(status_code=404, detail="Strategy profile not found.")
    return profile


@app.get("/range-journal/options")
def range_journal_options():
    return {"max_calendar_days": MAX_RANGE_DAYS, "rule_set": range_rule_definition()}


@app.get("/today")
def read_today(response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return get_today_view()
    except MarketDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    except InvalidJournalEvidence:
        raise HTTPException(status_code=502, detail="Today's market evidence could not be validated.") from None


@app.post("/today/generate")
def generate_today_journal(entry: TodayJournalInput):
    try:
        view = load_today_snapshot(str(entry.snapshot_id))
        snapshot, evaluation = view["market_data"], view["rule_evaluation"]
        catalog = build_evidence_catalog(snapshot, allow_partial=True)
    except MarketDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    except InvalidJournalEvidence:
        raise HTTPException(status_code=502, detail="Today's market evidence could not be validated.") from None
    entry_data = {"pair": "EURUSD", "timeframe": "4h", "journal_date": view["journal_date"],
                  "rule_set_id": "four_factor_v4", "strategy": evaluation["rule_set"]["rules"], "notes": entry.notes}
    return _generate_draft(entry_data, snapshot, catalog, evaluation)


@app.post("/range-journal/generate")
def generate_range_journal(entry: RangeJournalInput):
    try:
        snapshot = get_range_market_data(entry.start_date, entry.end_date)
    except MarketDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    try:
        catalog = build_range_evidence_catalog(snapshot)
        evaluation = evaluate_range_strategy(snapshot)
    except InvalidJournalEvidence as exc:
        logger.warning("Range evidence rejected: %s", exc)
        raise HTTPException(status_code=502, detail="The market data could not support a complete custom range.") from None
    entry_data = entry.model_dump(mode="json")
    entry_data["strategy"] = evaluation["rule_set"]["rules"]
    return _generate_draft(entry_data, snapshot, catalog, evaluation, custom_range=True)


@app.post("/range-journals", status_code=201)
def save_custom_journal(payload: JournalSaveInput):
    try:
        journal = save_range_journal(str(payload.generation_id), payload.edited_draft)
    except DraftAlreadySavedError:
        raise HTTPException(status_code=409, detail="This custom draft was already saved. Open it from Saved custom journals to edit it.") from None
    if journal is None:
        raise HTTPException(status_code=404, detail="Custom draft not found. Generate a new custom journal.")
    return journal


@app.get("/range-journals")
def list_custom_journals(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    return fetch_range_journals(limit, offset)


@app.get("/range-journals/{journal_id}")
def read_custom_journal(journal_id: int):
    journal = fetch_range_journal(journal_id)
    if journal is None:
        raise HTTPException(status_code=404, detail="Custom journal not found.")
    return journal


@app.patch("/range-journals/{journal_id}")
def edit_custom_journal(journal_id: int, payload: JournalUpdateInput):
    journal = update_range_journal(journal_id, payload.edited_draft)
    if journal is None:
        raise HTTPException(status_code=404, detail="Custom journal not found.")
    return journal


@app.delete("/range-journals/{journal_id}", status_code=204)
def remove_custom_journal(journal_id: int):
    if not delete_range_journal(journal_id):
        raise HTTPException(status_code=404, detail="Custom journal not found.")
    return Response(status_code=204)

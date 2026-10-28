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
    fetch_journal, update_journal_text, delete_journal, fetch_journals, DraftAlreadySavedError,
    fetch_strategy_profiles, fetch_strategy_profile, insert_strategy_profile,
    update_strategy_profile, delete_strategy_profile, DuplicateStrategyProfileError,
)
from market_data import MarketDataError, get_market_data
from journal_grounding import (
    JOURNAL_INSTRUCTIONS, InvalidJournalEvidence, build_evidence_catalog,
    render_journal, response_format,
)

load_dotenv(Path(__file__).with_name(".env"))

client = OpenAI(timeout=90.0, max_retries=0)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
    model_config = ConfigDict(str_strip_whitespace=True)

    pair: str = Field(min_length=1, max_length=20)
    journal_date: date
    timeframe: Literal["15m", "1h", "4h", "1d"]
    strategy: str = Field(min_length=1, max_length=10000)
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
    return entry.model_dump(mode="json")

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
    entry_data = entry.model_dump(mode="json")
    try:
        evidence_catalog = build_evidence_catalog(market_data)
    except InvalidJournalEvidence as exc:
        logger.warning("Journal market evidence rejected: %s", exc)
        raise HTTPException(status_code=502, detail="The market data could not be prepared for journal evidence.") from None
    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-6.1-sol"),
            instructions=JOURNAL_INSTRUCTIONS,
            input=json.dumps({
                "entry": entry_data, "market_data": market_data, "evidence_catalog": evidence_catalog,
            }, allow_nan=False),
            text={"format": response_format()},
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
        draft = render_journal(response.output_text, market_data, entry.strategy)
    except InvalidJournalEvidence as exc:
        logger.warning("AI journal evidence rejected: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=(
                "The AI draft failed its evidence checks. No new draft was saved. "
                "Please generate it again."
            ),
        ) from None

    generation_id = store_generated_draft(entry_data, draft, market_data)
    return {
        "generation_id": generation_id,
        "entry": entry_data,
        "draft": draft,
        "market_data": market_data,
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
):
    return fetch_journals(limit=limit, offset=offset)

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
        return insert_strategy_profile(payload.name, payload.rules)
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
        profile = update_strategy_profile(profile_id, payload.name, payload.rules)
    except DuplicateStrategyProfileError:
        raise HTTPException(
            status_code=409,
            detail="A strategy profile with that name already exists. Choose another name.",
        ) from None
    if profile is None:
        raise HTTPException(status_code=404, detail="Strategy profile not found.")
    return profile

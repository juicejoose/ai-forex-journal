from uuid import UUID
import json
import logging
import os

from fastapi import APIRouter, HTTPException, Query, Response
from openai import APIError

from journal_grounding import InvalidJournalEvidence
from market_data import MarketDataError
from setup_models import SetupInput, SetupEvaluateInput, SetupPreviewInput
from setup_market import build_setup_snapshot, capture_preview
import setup_database as db
import setup_ai as ai

logger = logging.getLogger(__name__)


def setup_router(get_client):
    router = APIRouter(tags=["Setup evaluator"])

    def read(identifier):
        try:
            record = db.fetch_snapshot(identifier)
        except db.SetupConflict as exc:
            raise HTTPException(409, str(exc)) from None
        if record is None:
            raise HTTPException(404, "Setup snapshot not found.")
        return record

    def finish(identifier, **values):
        try:
            return db.finish_evaluation(identifier, **values)
        except db.SetupNotFound as exc:
            raise HTTPException(404, str(exc)) from None

    @router.post("/setup-previews", status_code=201)
    def create_preview(entry: SetupPreviewInput):
        request = entry.model_dump(mode="json", exclude={"request_id"})
        try:
            existing = db.find_preview_request(entry.request_id, request)
            if existing:
                return existing
            snapshot = build_setup_snapshot(SetupInput(**entry.model_dump(), direction="long"))
            return db.store_preview(entry.request_id, request, snapshot)
        except db.SetupConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except MarketDataError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
        except InvalidJournalEvidence:
            raise HTTPException(502, "The chart market evidence could not be validated.") from None

    @router.post("/setup-snapshots", status_code=201)
    def create_snapshot(entry: SetupInput):
        request = entry.model_dump(mode="json", exclude={"request_id"})
        if request.get("preview_id") is None:
            request.pop("preview_id", None)
        if request.get("trade_plan") is None:
            request.pop("trade_plan", None)
        # Preserve request identities from captures made before origin_at existed.
        for zone in request["zones"]:
            if zone.get("origin_at") is None:
                zone.pop("origin_at", None)
        try:
            existing = db.find_snapshot_request(entry.request_id, request)
            if existing:
                return {**existing, "evaluations": db.list_evaluations(existing["id"])}
            snapshot = capture_preview(entry, db.fetch_preview(entry.preview_id)) if entry.preview_id else build_setup_snapshot(entry)
            snapshot["catalog"] = ai.build_catalog(snapshot)
            return {**db.store_snapshot(entry.request_id, request, snapshot), "evaluations": []}
        except db.SetupConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except MarketDataError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
        except InvalidJournalEvidence:
            raise HTTPException(502, "The setup market evidence could not be validated.") from None

    @router.get("/setup-snapshots")
    def list_snapshots(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        try:
            return db.list_snapshots(limit, offset)
        except db.SetupConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @router.get("/setup-snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: UUID):
        return {**read(snapshot_id), "evaluations": db.list_evaluations(snapshot_id)}

    @router.delete("/setup-snapshots/{snapshot_id}", status_code=204)
    def delete_snapshot(snapshot_id: UUID):
        try:
            deleted = db.delete_snapshot(snapshot_id)
        except db.SetupConflict as exc:
            raise HTTPException(409, str(exc)) from None
        if not deleted:
            raise HTTPException(404, "Setup snapshot not found.")
        return Response(status_code=204)

    @router.post("/setup-snapshots/{snapshot_id}/evaluate")
    def evaluate(snapshot_id: UUID, entry: SetupEvaluateInput):
        record = read(snapshot_id)
        model = os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
        try:
            attempt, created = db.begin_evaluation(snapshot_id, entry.request_id, model, ai.PROMPT_VERSION)
        except db.SetupConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except db.SetupNotFound as exc:
            raise HTTPException(404, str(exc)) from None
        if not created:
            return attempt
        response = None
        try:
            response = get_client().responses.create(model=model, instructions=ai.INSTRUCTIONS,
                input=json.dumps(ai.ai_input(record["snapshot"]), allow_nan=False),
                text={"format": ai.response_format()}, reasoning={"effort": "medium"},
                max_output_tokens=6000, service_tier="default", store=False)
            if response.status != "completed":
                raise InvalidJournalEvidence("The AI response was incomplete.")
            result = ai.parse_assessment(response.output_text, record["snapshot"])
        except APIError:
            return finish(attempt["id"], error="The AI request failed. Your snapshot is saved; retry when the connection or API access is available.")
        except InvalidJournalEvidence:
            return finish(attempt["id"], error="The AI response was refused, incomplete, or failed its evidence checks. Your snapshot is saved.")
        except Exception as exc:
            logger.error("Unexpected setup assessment failure: %s", type(exc).__name__)
            return finish(attempt["id"], error="The assessment could not be completed. Your snapshot is saved.")
        return finish(attempt["id"], result=result,
            provider_model=getattr(response, "model", model), response_id=getattr(response, "id", None))

    return router

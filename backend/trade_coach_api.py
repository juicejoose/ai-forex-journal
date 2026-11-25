"""Manual, authenticated AI reviews; never invoked by chart polling."""
import json
import logging
import os
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query
from openai import APIError
from journal_grounding import InvalidJournalEvidence
from market_data import MarketDataError
from trade_calculations import TradeInputError
import trade_database as trades
from trade_api import execute
from trade_coach_models import CoachRequest
from trade_coach_market import build_snapshot
import trade_coach_database as db
import trade_coach_ai as ai

logger=logging.getLogger(__name__)


def coach_router(get_client):
    router=APIRouter(tags=['Trade coach'])

    @router.get('/trades/{identifier}/coach-reviews')
    def history(identifier:UUID,limit:int=Query(10,ge=1,le=30),offset:int=Query(0,ge=0)):
        return execute(db.listing,identifier,limit,offset)

    @router.get('/trades/{identifier}/coach-reviews/{review_id}')
    def read(identifier:UUID,review_id:UUID): return execute(db.fetch,identifier,review_id)

    @router.post('/trades/{identifier}/coach-reviews')
    def review(identifier:UUID,entry:CoachRequest):
        model=os.getenv('OPENAI_MODEL','gpt-6.1-sol')
        attempt,created=execute(db.reserve,identifier,entry,model,ai.PROMPT_VERSION)
        if not created:return attempt
        try:
            snapshot=build_snapshot(identifier,entry)
            snapshot['catalog']=ai.build_catalog(snapshot)
            db.freeze(attempt['id'],snapshot)
        except trades.TradeNotFound as exc:
            raise HTTPException(404,str(exc)) from None
        except (MarketDataError,TradeInputError,trades.TradeConflict) as exc:
            return execute(db.finish,attempt['id'],error=str(exc))
        except InvalidJournalEvidence:
            return execute(db.finish,attempt['id'],error='Market evidence could not be validated. Retry with fresh data.')
        except Exception as exc:
            logger.error('Coach capture failed: %s',type(exc).__name__)
            return execute(db.finish,attempt['id'],error='Coach evidence could not be captured. Start a new review to retry.')
        # No write transaction is held across either provider request.
        try:
            response=get_client().responses.create(model=model,instructions=ai.INSTRUCTIONS,
                input=json.dumps(ai.ai_input(snapshot),allow_nan=False),text={'format':ai.response_format()},
                reasoning={'effort':'medium'},max_output_tokens=6000,service_tier='default',store=False)
            if response.status!='completed':raise InvalidJournalEvidence('Incomplete coach response')
            result=ai.parse(response.output_text,snapshot)
        except APIError:
            return execute(db.finish,attempt['id'],error='The AI request failed. Its evidence is saved; start a new review to retry.')
        except InvalidJournalEvidence:
            return execute(db.finish,attempt['id'],error='The AI response was refused, incomplete or failed evidence checks. Its evidence is saved; start a new review to retry.')
        except Exception as exc:
            logger.error('Coach request failed: %s',type(exc).__name__)
            return execute(db.finish,attempt['id'],error='The coach request failed. Its evidence is saved.')
        return execute(db.finish,attempt['id'],result=result,provider_model=getattr(response,'model',model),response_id=getattr(response,'id',None))

    return router

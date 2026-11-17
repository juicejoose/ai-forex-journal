from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query
import trade_database as db
from trade_models import TradeInput, TradeCloseInput, TradeReviewInput, TradeAnalysisInput
from trade_calculations import TradeInputError
from market_data import MarketDataError
from journal_grounding import InvalidJournalEvidence

router=APIRouter(tags=['Trade log'])


def execute(action,*args):
    try: return action(*args)
    except db.TradeNotFound as exc: raise HTTPException(404,str(exc)) from None
    except db.TradeConflict as exc: raise HTTPException(409,str(exc)) from None
    except TradeInputError as exc: raise HTTPException(422,str(exc)) from None
    except MarketDataError as exc: raise HTTPException(exc.status_code,str(exc)) from None
    except InvalidJournalEvidence: raise HTTPException(502,'The entry-time market evidence could not be validated.') from None


@router.post('/trades',status_code=201)
def create(entry:TradeInput): return execute(db.create_trade,entry)


@router.get('/trades')
def listing(status:Literal['all','open','closed']='all',limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
    return execute(db.list_trades,status,limit,offset)


@router.get('/trades/{identifier}')
def read(identifier:UUID): return execute(db.fetch_trade,identifier)


@router.post('/trades/{identifier}/close')
def close(identifier:UUID,entry:TradeCloseInput): return execute(db.close_trade,identifier,entry)


@router.post('/trades/{identifier}/reviews')
def review(identifier:UUID,entry:TradeReviewInput): return execute(db.review_trade,identifier,entry)


@router.post('/trades/{identifier}/strategy-analysis')
def analysis(identifier:UUID,entry:TradeAnalysisInput): return execute(db.analyze_trade,identifier,entry)

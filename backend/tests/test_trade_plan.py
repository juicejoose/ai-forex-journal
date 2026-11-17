"""Manual planned levels: exact math, optional inputs and immutable AI context."""
import copy
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.test_setup_evaluator import snapshot, inputs, valid_assessment, main, ENVIRONMENT
from tests.test_custom_range import range_payload
from tests.test_today import Clock
from setup_models import SetupInput
from trade_plan import calculate_trade_plan
from journal_grounding import InvalidJournalEvidence
import setup_ai as ai
import setup_database as sd
import database as db
import market_data as md
import today


LONG = {'entry_price':'1.10000','stop_loss':'1.09800','take_profit':'1.10400'}
SHORT = {'entry_price':'1.10000','stop_loss':'1.10200','take_profit':'1.09600'}


def calculate(values=LONG, direction='long', zones=()):
    entry=SetupInput(**inputs(trade_plan=values,direction=direction))
    return calculate_trade_plan(entry.trade_plan,entry.direction,zones)


class TradePlanCalculationTests(unittest.TestCase):
    def test_long_and_short_distances_are_exact_and_ratio_uses_reward_over_risk(self):
        for values,direction in ((LONG,'long'),(SHORT,'short')):
            plan=calculate(values,direction)
            self.assertEqual(plan['risk_pips'],'20.0')
            self.assertEqual(plan['reward_pips'],'40.0')
            self.assertEqual(Decimal(plan['reward_to_risk']),Decimal(2))
            self.assertEqual(plan['reward_to_risk_display'],'2.00')
            self.assertEqual(plan['direction'],direction)
            self.assertIsNone(plan['minimum_reward_to_risk'])
        self.assertIsNone(calculate_trade_plan(None,'long',[]))

    def test_fractional_pips_repeating_ratios_and_tiny_rewards_do_not_round_to_zero(self):
        plan=calculate({'entry_price':'1.10003','stop_loss':'1.10000','take_profit':'1.10004'})
        self.assertEqual((plan['risk_pips'],plan['reward_pips']),('0.3','0.1'))
        self.assertEqual(plan['reward_to_risk_display'],'0.33')
        self.assertGreater(len(plan['reward_to_risk']),20)
        tiny=calculate({'entry_price':'1.10000','stop_loss':'1.09750','take_profit':'1.10001'})
        self.assertEqual(tiny['reward_to_risk_display'],'<0.01')
        self.assertGreater(Decimal(tiny['reward_to_risk']),0)

    def test_partial_nonfinite_zero_equal_and_reversed_prices_are_rejected(self):
        bad=[{}, {'entry_price':'1.1'}, {**LONG,'stop_loss':None}]
        for field in LONG:
            for value in ('NaN','Infinity','-1','0','100.00001','1.123456',True):
                bad.append({**LONG,field:value})
        bad += [{**LONG,'stop_loss':LONG['entry_price']},{**LONG,'take_profit':LONG['entry_price']},SHORT]
        for plan in bad:
            with self.subTest(plan=plan), self.assertRaises(ValidationError):
                SetupInput(**inputs(trade_plan=plan))
        with self.assertRaises(ValidationError): SetupInput(**inputs(direction='short',trade_plan=LONG))
        with self.assertRaises(ValidationError): SetupInput(**inputs(trade_plan={**LONG,'reward_to_risk':999}))

    def test_zone_positions_use_exact_edges_and_do_not_modify_zones(self):
        zones=[{'id':'Z1','label':'Support','kind':'support','lower':'1.098','upper':'1.099'},
               {'id':'Z2','label':'Resistance','kind':'resistance','lower':'1.104','upper':'1.105'}]
        original=copy.deepcopy(zones)
        plan=calculate(zones=zones)
        self.assertEqual((plan['zone_positions'][0]['entry_position'],plan['zone_positions'][0]['stop_position']),('above','inside'))
        self.assertEqual((plan['zone_positions'][1]['entry_position'],plan['zone_positions'][1]['target_position']),('below','inside'))
        self.assertEqual(zones,original)

    def test_plan_changes_never_change_market_data_patterns_or_strategy_scores(self):
        with patch.object(md, 'datetime', Clock), patch.object(today, 'datetime', Clock):
            base=snapshot()
            planned=snapshot(trade_plan=LONG)
        for key in ('market_data','source_candles','rule_evaluation','zones','reference_price'):
            self.assertEqual(base[key],planned[key],key)
        self.assertEqual(planned['schema_version'],4)
        self.assertEqual(planned['trade_plan']['version'],'trade_plan_v1')
        self.assertEqual(planned['observation_provenance'],'retrospective_user_input')

    def test_ai_must_acknowledge_plan_as_context_and_cannot_assign_it_strategy_support(self):
        snap=snapshot(trade_plan=LONG)
        fact=next(f for f in snap['catalog']['facts'] if 'trade_plan' in f['evidence'])
        self.assertEqual(fact['role'],'context')
        output=valid_assessment(snap)
        ai.parse_assessment(json.dumps(output),snap)
        output['context_facts'].remove(fact['id'])
        with self.assertRaises(InvalidJournalEvidence): ai.parse_assessment(json.dumps(output),snap)
        output=valid_assessment(snap)
        output['supporting_facts']=[fact['id']]
        with self.assertRaises(InvalidJournalEvidence): ai.parse_assessment(json.dumps(output),snap)
        output=valid_assessment(snap)
        output['trade_plan']={**LONG,'reward_to_risk':999}
        with self.assertRaises(InvalidJournalEvidence): ai.parse_assessment(json.dumps(output),snap)

    def test_eight_zones_plus_plan_fit_required_ai_context_and_absent_plan_stays_optional(self):
        zones=[{**inputs()['zones'][0],'label':f'Zone {i}'} for i in range(8)]
        snap=snapshot(zones=zones,trade_plan=LONG)
        output=valid_assessment(snap)
        self.assertEqual(len(output['context_facts']),10)
        ai.parse_assessment(json.dumps(output),snap)
        unplanned=snapshot()
        self.assertIsNone(unplanned['trade_plan'])
        self.assertFalse(any('trade_plan' in f['evidence'] for f in unplanned['catalog']['facts']))


class TradePlanAPITests(unittest.TestCase):
    def setUp(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(db,'DB_PATH',root/'journal.db'))
        self.enterContext(patch.dict(os.environ,ENVIRONMENT,clear=True))
        self.enterContext(patch.object(md,'_fetch_candles',return_value=range_payload()))
        db.init_db(); sd.init_setup_db()
        self.client=self.enterContext(TestClient(main.app))
        self.provider=self.enterContext(patch.object(main.client.responses,'create'))

    def capture(self,body):
        result=self.client.post('/setup-snapshots',json=body)
        self.assertEqual(result.status_code,201,result.text)
        return result.json()

    def test_plan_is_saved_idempotently_and_survives_reopen_without_provider_requests(self):
        body=inputs(trade_plan=LONG)
        saved=self.capture(body)
        sd.init_setup_db()
        with patch('setup_api.build_setup_snapshot',side_effect=AssertionError('Do not recalculate')):
            self.assertEqual(self.capture(body),saved)
            self.assertEqual(self.client.get('/setup-snapshots/'+saved['id']).json(),saved)
        self.assertEqual(saved['snapshot']['trade_plan']['reward_to_risk_display'],'2.00')
        changed={**body,'trade_plan':{**LONG,'take_profit':'1.10600'}}
        self.assertEqual(self.client.post('/setup-snapshots',json=changed).status_code,409)
        self.provider.assert_not_called()

    def test_preview_accepts_annotations_and_plan_without_refetching_or_mutating_its_evidence(self):
        body=inputs()
        selection={key:body[key] for key in ('request_id','mode','as_of','include_quote')}
        response=self.client.post('/setup-previews',json=selection)
        self.assertEqual(response.status_code,201,response.text)
        preview=response.json()
        with patch('setup_api.build_setup_snapshot',side_effect=AssertionError('No fresh market request')):
            saved=self.capture(inputs(direction='short',trade_plan=SHORT,preview_id=preview['id']))
        for key in ('source_candles','rule_evaluation','market_data','quote','reference_price','cutoff_at'):
            self.assertEqual(saved['snapshot'][key],preview['snapshot'][key],key)
        self.assertIsNone(sd.fetch_preview(preview['id'])['snapshot']['trade_plan'])
        self.assertEqual(saved['snapshot']['trade_plan']['direction'],'short')
        self.assertIn('finalized_at',saved['snapshot'])

    def test_invalid_and_injected_calculations_fail_before_capture(self):
        for change in ({'trade_plan':{}},{'trade_plan':SHORT},
                       {'trade_plan':{**LONG,'risk_pips':'0'}},{'risk_pips':'0'}):
            with patch('setup_api.build_setup_snapshot') as build:
                response=self.client.post('/setup-snapshots',json=inputs(**change))
                self.assertEqual(response.status_code,422,response.text)
                build.assert_not_called()
        self.assertEqual(self.client.get('/setup-snapshots').json()['total'],0)

    def test_legacy_no_plan_retry_retains_original_snapshot_and_null_is_equivalent_to_omitted(self):
        body=inputs()
        entry=SetupInput(**body)
        request=entry.model_dump(mode='json',exclude={'request_id','preview_id','trade_plan'})
        for zone in request['zones']: zone.pop('origin_at',None)
        old=snapshot()
        old.pop('trade_plan'); old['entry'].pop('trade_plan'); old['schema_version']=3
        stored=sd.store_snapshot(entry.request_id,request,old)
        with patch('setup_api.build_setup_snapshot',side_effect=AssertionError('Legacy evidence must stay frozen')):
            self.assertEqual(self.capture({**body,'trade_plan':None})['snapshot'],old)
            self.assertEqual(self.client.get('/setup-snapshots/'+stored['id']).json()['snapshot'],old)

    def test_assessment_receives_saved_plan_and_stores_validated_result(self):
        saved=self.capture(inputs(trade_plan=LONG))
        result=valid_assessment(saved['snapshot'])
        self.provider.return_value=SimpleNamespace(status='completed',output_text=json.dumps(result),model='offline-model',id='offline-response')
        response=self.client.post('/setup-snapshots/'+saved['id']+'/evaluate',json={'request_id':str(uuid4())})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'completed')
        sent=json.loads(self.provider.call_args.kwargs['input'])
        plan=next(f['evidence']['trade_plan'] for f in sent['facts'] if 'trade_plan' in f['evidence'])
        self.assertEqual(plan,saved['snapshot']['trade_plan'])
        self.assertEqual(self.client.get('/setup-snapshots/'+saved['id']).json()['evaluations'][0]['result'],result)

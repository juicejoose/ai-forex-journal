"""Replay completed H4 evidence without sending trades to an external provider."""
import unittest

from trade_coach_readout import build_readout


def factor(name, score):
    return {'name': name, 'factor_id': name, 'outcome': 'bullish' if score>0 else 'bearish' if score<0 else 'neutral',
            'bullish_points': max(0,score), 'bearish_points': max(0,-score)}


def candle(hour, scores):
    return {'close_time': f'2026-10-21T{hour:02}:00:00+00:00',
            'factors': [factor(name,score) for name,score in zip(('Closes','EMA/SMA','RSI','Momentum'),scores)]}


def replay(direction='long', rows=None, zones=(), fresh=True):
    entry = candle(1, (0,2,0,1))
    if rows is None:
        rows = [candle(5, (0,2,0,-0.5))]
    latest = rows[-1] if rows else entry
    net = sum(f['bullish_points']-f['bearish_points'] for f in latest['factors'])
    return build_readout({'entry_score':{'candle':entry},'full_trade':{'candles':rows},
                         'covers_latest_close':fresh,'latest_summary':{'net_score':net},
                         'trade':{'direction':direction},'data_through':latest['close_time'],'zones':zones})


def zone(name, events, status='covered'):
    return {'id':name,'label':name,'patterns':{'events':[
        {'kind':kind,'direction':direction,'id':f'{name}-{i}', 'close_time':candle(hour,())['close_time']}
        for i,(hour,kind,direction) in enumerate(events)],'status':status}}


class CoachReadoutTests(unittest.TestCase):
    def test_weighted_direction_and_price_action_can_disagree(self):
        resistance = zone('ceiling',[(5,'rejection','bearish')])
        long = replay(zones=[resistance])
        short = replay('short',zones=[resistance])
        self.assertEqual(long['strategy_alignment'],'supported')
        self.assertEqual(long['price_action']['status'],'opposes')
        self.assertEqual(short['strategy_alignment'],'contradicted')
        self.assertEqual(short['price_action']['status'],'supports')
        self.assertEqual(long['market_net_score'],1.5)
        self.assertEqual(short['market_net_score'],1.5)
        self.assertEqual(short['price_action']['matches'][0]['zone_label'],'ceiling')

    def test_ties_missing_and_stale(self):
        for scores in ((0,0,0,0),(-1,2,-1,0)):
            self.assertEqual(replay(rows=[candle(5,scores)])['strategy_alignment'],'balanced')
        snap = replay(fresh=False,zones=[zone('floor',[(5,'rejection','bullish')])])
        self.assertEqual(snap['strategy_alignment'],'insufficient_evidence')
        self.assertIsNone(snap['market_net_score'])
        self.assertEqual(snap['price_action']['status'],'unavailable')
        self.assertEqual(snap['price_action']['matches'],[])

    def test_prior_or_invalidated_zone_events_do_not_vote(self):
        self.assertEqual(replay()['price_action']['status'],'no_zones')
        untested = zone('ceiling',[],'not_requested')
        self.assertEqual(replay(zones=[untested])['price_action']['status'],'limited_history')
        earlier = zone('floor',[(1,'rejection','bullish'),(5,'retest_invalidated','bullish')])
        self.assertEqual(replay(zones=[earlier])['price_action']['status'],'no_match')
        both = replay(zones=[zone('floor',[(5,'retest_held','bullish')]),zone('ceiling',[(5,'rejection','bearish')]),untested])
        self.assertEqual(both['price_action']['status'],'mixed')
        self.assertTrue(both['price_action']['partial_coverage'])

    def test_factor_return_to_entry_weight_change_and_persistence(self):
        rows=[candle(5,(0,2,0,-1)),candle(9,(0,1,0,1)),candle(13,(0,1,0,1))]
        # A replay at an earlier cutoff only sees its prefix.
        early=replay(rows=rows[:1]);late=replay(rows=rows)
        self.assertEqual(early['factor_history'][3]['latest']['outcome'],'bearish')
        momentum=late['factor_history'][3]
        self.assertEqual(momentum['entry'],momentum['latest'])
        self.assertEqual(momentum['previous']['outcome'],'bearish')
        self.assertEqual(momentum['changed_at'],rows[1]['close_time'])
        self.assertEqual(momentum['consecutive_closes'],2)
        ema=late['factor_history'][1]
        self.assertEqual((ema['previous']['bullish_points'],ema['latest']['bullish_points']),(2,1))
        self.assertEqual(late['factor_history'][2]['consecutive_closes'],3)
        self.assertIsNone(late['factor_history'][2]['changed_at'])

    def test_before_first_close_has_no_new_match_or_persistence(self):
        before=replay(rows=[],zones=[zone('floor',[(1,'rejection','bullish')])])
        self.assertEqual(before['hold_closes'],0)
        self.assertEqual(before['price_action'],{'status':'awaiting_close','matches':[],'partial_coverage':False})
        self.assertTrue(all(item['consecutive_closes']==0 for item in before['factor_history']))

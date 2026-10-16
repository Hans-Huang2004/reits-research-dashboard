import copy
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from collectors.ndrc_matching import identity, match_recommendations

NOW=datetime(2026,10,16,12,tzinfo=ZoneInfo('Asia/Shanghai'))


def recommendation(**changes):
    row={'id':'NDRC_a','name':'示例产业园项目','applicant_region':'上海市','recommended_date':'2026-01-02','business_type':'待核实'}
    row.update(changes);return row


def event(**changes):
    row={'id':'SSE_abc','name':'华夏示例产业园封闭式基础设施证券投资基金','business_type':'首发','exchange':'上交所',
         'source_url':'https://www.sse.com.cn/reits/info/index_detail.shtml?audit_id=abc',
         'fund_id':'SSE_FUND_508001','fund_code':'508001','accepted_date':'2026-01-05','stage':'已受理','origin':'示例集团'}
    row.update(changes);return row


def snapshot(*events):
    return {'updated_at':'2026-10-16T09:00:00+08:00','events':list(events) or [event()],
            'funds':[{'id':'SSE_FUND_508001','name':'示例基金','stage':'已上市'}]}


def review(row=None, **link_changes):
    row=row or recommendation()
    link={'exchange_event_id':'SSE_abc','business_type':'首发','note':'官方招募书确认本次首发的原始权益人与园区资产。',
          'evidence':[{'url':'https://static.sse.com.cn/abc.pdf','page':12,'note':'首发园区资产及原始权益人定义'}]}
    link.update(link_changes)
    return {'reviews':{row['id']:{'identity':identity(row),'links':[link],'reviewed_at':NOW.isoformat()}}}


class NDRCMatchingTests(unittest.TestCase):
    def test_name_similarity_never_confirms(self):
        rows,audit=match_recommendations([recommendation()],snapshot(),overrides={'reviews':{}},now=NOW)
        self.assertEqual(rows[0]['match_status'],'candidate')
        self.assertEqual(rows[0]['relations'],[])
        self.assertEqual(audit['confirmed_relation_count'],0)

    def test_reviewed_link_binds_event_and_returns_exact_dates(self):
        original=[recommendation()];source=snapshot();before=copy.deepcopy((original,source))
        rows,audit=match_recommendations(original,source,overrides=review(),now=NOW)
        self.assertEqual(rows[0]['match_status'],'confirmed')
        self.assertEqual(rows[0]['business_type'],'首发')
        self.assertEqual(rows[0]['relations'][0]['days_to_acceptance'],3)
        self.assertEqual(rows[0]['relations'][0]['current_stage'],'已上市')
        self.assertEqual((original,source),before)
        self.assertEqual(audit['confirmed_exchange_event_count'],1)

    def test_new_acquisition_does_not_match_initial_event(self):
        row=recommendation(name='示例产业园新购入项目',business_type='新购入')
        rows,_=match_recommendations([row],snapshot(),overrides={'reviews':{}},now=NOW)
        self.assertEqual(rows[0]['match_status'],'unmatched')
        with self.assertRaisesRegex(ValueError,'initial filing'):
            match_recommendations([row],snapshot(),overrides=review(row),now=NOW)

    def test_distinct_acquisition_preserved_outside_expansion_population(self):
        row=recommendation(name='示例产业园新购入项目',business_type='新购入')
        acquisition=event(id='SZSE_new',business_type='新购入')
        source=snapshot();source['quality']={'scope_exclusions':[{'record':acquisition}]}
        config=review(row,exchange_event_id='SZSE_new',business_type='新购入')
        rows,audit=match_recommendations([row],source,overrides=config,now=NOW)
        self.assertEqual(rows[0]['relations'][0]['business_type'],'新购入')
        self.assertEqual(rows[0]['business_type'],'新购入')
        self.assertEqual(audit['exchange_business_types'],{'首发':1,'新购入':1})

    def test_review_requires_unchanged_recommendation_and_business_batch(self):
        config=review()
        with self.assertRaisesRegex(ValueError,'identity changed'):
            match_recommendations([recommendation(recommended_date='2026-01-03')],snapshot(),overrides=config,now=NOW)
        with self.assertRaisesRegex(ValueError,'business type changed'):
            match_recommendations([recommendation()],snapshot(event(business_type='扩募')),overrides=config,now=NOW)
        with self.assertRaisesRegex(ValueError,'missing'):
            match_recommendations([recommendation()],snapshot(event(id='SSE_other')),overrides=config,now=NOW)

    def test_evidence_is_required_and_must_be_official(self):
        for evidence in ([],[{'url':'https://example.com/a.pdf','note':'新闻'}]):
            with self.assertRaises(ValueError):
                match_recommendations([recommendation()],snapshot(),overrides=review(evidence=evidence),now=NOW)

    def test_acceptance_date_revision_requires_a_new_review(self):
        config=review(expected_accepted_date='2026-01-05')
        with self.assertRaisesRegex(ValueError,'acceptance date changed'):
            match_recommendations([recommendation()],snapshot(event(accepted_date='2026-01-06')),overrides=config,now=NOW)

    def test_negative_interval_requires_review_and_is_not_lead_time(self):
        source=snapshot(event(accepted_date='2025-12-10'))
        with self.assertRaisesRegex(ValueError,'chronology review'):
            match_recommendations([recommendation()],source,overrides=review(),now=NOW)
        rows,audit=match_recommendations([recommendation()],source,overrides=review(chronology_note='两侧官方日期均保留，未计入提前量。'),now=NOW)
        self.assertIsNone(rows[0]['relations'][0]['days_to_acceptance'])
        self.assertEqual(len(audit['chronology_exceptions']),1)

    def test_many_to_many_relations_do_not_collapse_records(self):
        a=recommendation();b=recommendation(id='NDRC_b',name='示例园区一期项目')
        config=review(a);config['reviews'][b['id']]={'identity':identity(b),'links':copy.deepcopy(config['reviews'][a['id']]['links'])}
        second=event(id='SSE_def')
        link=copy.deepcopy(config['reviews'][a['id']]['links'][0]);link['exchange_event_id']='SSE_def'
        config['reviews'][a['id']]['links'].append(link)
        rows,audit=match_recommendations([a,b],snapshot(event(),second),overrides=config,now=NOW)
        self.assertEqual([len(r['relations']) for r in rows],[2,1])
        self.assertEqual(audit['confirmed_relation_count'],3)
        self.assertEqual(audit['confirmed_exchange_event_count'],2)

    def test_reviewed_unmatched_alerts_on_new_candidate_event(self):
        row=recommendation();config={'reviews':{row['id']:{'identity':identity(row),'outcome':'unmatched','note':'此前无对应申报','reviewed_event_ids':['SSE_abc']}}}
        rows,_=match_recommendations([row],snapshot(),overrides=config,now=NOW)
        self.assertEqual(rows[0]['match_status'],'unmatched')
        rows,_=match_recommendations([row],snapshot(event(),event(id='SSE_new')),overrides=config,now=NOW)
        self.assertEqual(rows[0]['match_status'],'candidate')


if __name__=='__main__':unittest.main()

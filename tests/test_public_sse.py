"""Offline checks for SSE public REIT source interpretation and completeness."""
from datetime import datetime
import tempfile
import unittest
from collectors import public_sse as sse


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
    def get(self, path, params, label):
        return self.pages[params['pageHelp.pageNo']]


def page(rows, number=1, total=None, size=100, count=None):
    total = len(rows) if total is None else total
    return {'result':rows, 'pageHelp':{'total':total, 'pageNo':number,
        'pageSize':size, 'pageCount':max(1,(total+size-1)//size) if count is None else count}}


class PaginationTests(unittest.TestCase):
    def test_all_pages_reconcile_and_keep_ids(self):
        result, check = sse.fetch_pages(FakeClient({
            1:page([{'id':'a'},{'id':'b'}], total=3,size=2),
            2:page([{'id':'c'}],number=2,total=3,size=2),
        }), 'test', identity=lambda x:x['id'])
        self.assertEqual([r['id'] for r in result], ['a','b','c'])
        self.assertTrue(check['complete'])
        self.assertEqual(check['advertised_total'],3)

    def test_missing_page_rows_abort(self):
        with self.assertRaises(sse.CollectionError):
            sse.fetch_pages(FakeClient({1:page([{'id':'a'}],total=2)}),'test')

    def test_repeated_or_changed_pages_abort(self):
        for second in (page([{'id':'a'}],number=2,total=2,size=1),
                       page([{'id':'b'}],number=2,total=3,size=1)):
            with self.subTest(second=second),self.assertRaises(sse.CollectionError):
                sse.fetch_pages(FakeClient({1:page([{'id':'a'}],total=2,size=1),2:second}),
                    'test',identity=lambda x:x['id'])


class InterpretationTests(unittest.TestCase):
    def test_management_company_is_separate_from_individual_fund_managers(self):
        fund = sse.normalize_fund('508095', {}, {
            'FUND_NAME':'某基金','COMPANY_NAME':'某证券资产管理有限公司',
            'FUND_MANAGER':'王某、赵某、唐某'})
        self.assertEqual(fund['manager'],'某证券资产管理有限公司')
        self.assertEqual(fund['fund_managers'],'王某、赵某、唐某')

    def test_official_reits_type_is_not_inferred_from_name(self):
        event = sse.normalize_event({'BOND_NUM':'official-id','AUDIT_NAME':'无扩募文字的基金',
            'REITS_TYPE':'1','AUDIT_STATUS':'12','REITS_ASSET_TYPE':'0','PLAN_ISSUE_AMOUNT':'5'})
        self.assertEqual(event['business_type'],'扩募')
        self.assertEqual(event['official_status'],'注册生效')
        self.assertEqual(event['product_type'],'商业不动产REITs')
        self.assertEqual(event['registered_date'],'')
        self.assertNotIn('initial_raise_cny_100m',event)

    def test_future_offer_and_listing_are_not_completed(self):
        fund = sse.normalize_fund('508606',{}, {'FUND_NAME':'某封闭式商业不动产证券投资基金'},
            {'startDate':'2026-11-03','endDate':'2026-11-09','listingDate':'2026-11-20',
             'salePrice':'4.646','saleCopies':'7'},as_of='2026-10-15')
        self.assertEqual(fund['stage'],'获批待发行')
        self.assertEqual(fund['listing_date'],'')
        self.assertIsNone(fund['initial_raise_cny_100m'])
        self.assertAlmostEqual(fund['initial_offered_cny_100m'],32.522)

    def test_established_date_and_completed_listing_have_separate_meanings(self):
        fund = sse.normalize_fund('508001',{}, {'FUND_NAME':'某基金','ESTABLISH_DATE':'2021-06-07'},
            {'listingDate':'2021-06-21','salePrice':'8.72','saleCopies':'5'},as_of='2021-06-10')
        self.assertEqual(fund['stage'],'成立待上市')
        self.assertEqual(fund['listing_date'],'')
        self.assertAlmostEqual(fund['initial_raise_cny_100m'],43.6)

    def test_exact_official_name_linking_keeps_ambiguous_unlinked(self):
        events=[{'name':'某基金','business_type':'首发','origin':'原始权益人','fund_code':''},
                {'name':'更名之前','business_type':'扩募','origin':'某权益人','fund_code':''}]
        funds=[{'code':'508001','name':'某基金','aliases':['某基金'],'origin':'','source_url':'https://official'}]
        sse.link_exact_fund_names(events,funds)
        self.assertEqual(events[0]['fund_code'],'508001')
        self.assertEqual(events[1]['fund_code'],'')
        self.assertEqual(funds[0]['origin'],'原始权益人')

    def test_unique_completed_expansion_requires_time_and_identity_evidence(self):
        event={'id':'SSE_1','fund_code':'508000','business_type':'扩募',
               'official_status_code':'12','accepted_date':'2022-09-29','updated_date':'2023-03-31'}
        batch={'fund_code':'508000','business_type':'扩募','completed_listing_date':'2023-06-16',
               'start_date':'2023-05-25','end_date':'2023-06-01','official_fund_stage':'2','source_url':'https://www.sse.com.cn/reits/listing/issue/'}
        sse.mark_unique_completed_expansions([event],[batch])
        self.assertEqual(event['completion_date'],'2023-06-16')
        self.assertEqual(event['completion_evidence']['matching_registered_filings'],1)
        ambiguous=dict(event)
        ambiguous.pop('completion_date');ambiguous.pop('completion_evidence')
        sse.mark_unique_completed_expansions([ambiguous,dict(ambiguous,id='SSE_2')],[batch])
        self.assertNotIn('completion_date',ambiguous)


if __name__ == '__main__':
    unittest.main()

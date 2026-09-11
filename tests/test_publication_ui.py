import json
import unittest

import test_listing_draft_ui as draft_ui
from integrated_ebay.publication_service import PublicationService


class PublicationUiTests(unittest.TestCase):
    setUp = draft_ui.ListingDraftUiTests.setUp
    tearDown = draft_ui.ListingDraftUiTests.tearDown
    app = draft_ui.ListingDraftUiTests.app
    button = staticmethod(draft_ui.ListingDraftUiTests.button)

    def prepare(self):
        draft_id = self.service.create(self.product_id, actor_id='Setup', price=30)
        self.service.generate(draft_id, expected_revision=1, actor_id='Setup')
        self.service.update(draft_id, dict(condition_name='Used', condition_id='3000', category_id='31388',
            publication_input_json=json.dumps(dict(sku='UI-PUBLISH', country_of_origin='JP', weight_g=500,
                length_cm=20, width_cm=10, height_cm=5, purchase_price=1000, exchange_rate=150,
                ebay_fee_rate=17.5, shipping_yen=500, shipping_carrier='Japan Post', shipping_service='EMS',
                specifics_reviewed=True))), expected_revision=2, actor_id='Setup')
        self.service.transition(draft_id, 'READY_FOR_REVIEW', expected_revision=3, actor_id='Setup')
        return draft_id

    def test_approve_then_explicit_mock_publish_and_registration(self):
        draft_id = self.prepare()
        app = self.app()
        app.text_input(key='ai_draft_actor').set_value('Human')
        next(w for w in app.checkbox if w.label.startswith('保存済みの本文')).check().run(timeout=60)
        self.button(app, '承認').click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertTrue(self.button(app, 'Mockで公開').disabled)
        publisher = PublicationService(self.factory)
        self.assertEqual('APPROVED', publisher.get(draft_id)['status'])
        next(w for w in app.checkbox if w.label.startswith('ローカル検証DBへのMock登録')).check().run(timeout=60)
        self.button(app, 'Mockで公開').click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        result = publisher.get(draft_id)
        self.assertEqual('PUBLISHED', result['status'])
        with self.factory() as c:
            row = dict(c.execute('SELECT * FROM listings WHERE id=?', (result['listing_id'],)).fetchone())
        self.assertEqual(self.product_id, row['product_id'])
        self.assertEqual(2212.5, row['profit_yen'])
        self.assertTrue(self.button(app, '下書きを保存').disabled)

    def test_new_review_fields_editable_and_missing_category_blocks(self):
        draft_id = self.prepare()
        app = self.app()
        app.text_input(key='ai_draft_actor').set_value('Human')
        self.assertTrue({'SKU','HS Code','HTS Code','仕入元URL','予定配送会社','予定配送サービス'} <= {w.label for w in app.text_input})
        next(w for w in app.text_input if w.label.startswith('Category ID')).set_value('')
        self.button(app, '下書きを保存').click().run(timeout=60)
        self.button(app, 'レビュー待ちにする').click().run(timeout=60)
        next(w for w in app.checkbox if w.label.startswith('保存済みの本文')).check().run(timeout=60)
        self.button(app, '承認').click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertTrue(any('Category ID' in e.value for e in app.error))
        self.assertIsNone(PublicationService(self.factory).get(draft_id))

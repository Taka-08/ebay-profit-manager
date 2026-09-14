import json
import unittest
from unittest.mock import patch

import test_publication_ui as fixtures
from integrated_ebay.approval_migration import initialize_approval_storage
from integrated_ebay.approval_service import ApprovalService


class ApprovalUiTests(unittest.TestCase):
    setUp = fixtures.PublicationUiTests.setUp
    tearDown = fixtures.PublicationUiTests.tearDown
    app = fixtures.PublicationUiTests.app
    button = staticmethod(fixtures.PublicationUiTests.button)
    prepare = fixtures.PublicationUiTests.prepare

    def seed(self):
        did = self.prepare()
        self.service.transition(did, 'APPROVED', expected_revision=4, actor_id='Fixture', reviewed=True)
        initialize_approval_storage(self.factory)
        return did

    def publish_from_ui(self):
        self.seed()
        app = self.app()
        app.text_input(key='ai_draft_actor').set_value('Reviewer')
        self.button(app, '公開提案を承認キューへ').click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertNotIn('Mockで公開', {w.label for w in app.button})
        app.text_input(key='approval_actor').set_value('Human')
        next(w for w in app.checkbox if w.label=='提案内容を人間が確認しました').check().run(timeout=60)
        self.button(app, '提案を承認').click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertIn('選択中の状態: APPROVED', [w.value for w in app.caption])
        selected = app.selectbox(key='approval_selected')
        self.assertFalse(any('PENDING' in option for option in selected.options))
        self.assertTrue(self.button(app, 'Mock実行').disabled)
        next(w for w in app.checkbox if w.label=='第6段階専用データへのMock/Dry-run保存を確認しました').check().run(timeout=60)
        self.button(app, 'Mock実行').click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertIn('選択中の状態: SUCCEEDED', [w.value for w in app.caption])
        return app

    def test_mismatched_approval_can_cancel_repropose_and_reapprove_in_ui(self):
        did = self.seed()
        service = ApprovalService(self.factory)
        r = service.propose_create(did, actor_id='Human', idempotency_key='stale-ui')
        service.approve(r['approval_request_id'], actor_id='Human', reviewed=True, expected_version=1)
        self.service.update(did, {'title':'New reviewed title'}, expected_revision=5, actor_id='Editor')
        app = self.app()
        app.text_input(key='approval_actor').set_value('Human')
        next(w for w in app.checkbox if w.label=='第6段階専用データへのMock/Dry-run保存を確認しました').check().run(timeout=60)
        self.button(app, 'Mock実行').click().run(timeout=60)
        self.assertTrue(any('承認済みpayloadと現在の下書きが一致しません' in w.value for w in app.error))
        self.assertNotIn('実行結果を照合（再送なし）', {w.label for w in app.button})
        self.button(app, '提案を取り消す').click().run(timeout=60)
        self.assertEqual('CANCELLED', service.get(r['approval_request_id'])['status'])
        app.text_input(key='ai_draft_actor').set_value('Human')
        self.button(app, 'レビュー待ちにする').click().run(timeout=60)
        next(w for w in app.checkbox if w.label.startswith('保存済みの本文・状態')).check().run(timeout=60)
        self.button(app, '承認').click().run(timeout=60)
        self.button(app, '公開提案を承認キューへ').click().run(timeout=60)
        fresh = next(row for row in service.list() if row['status']=='PENDING')
        app.selectbox(key='approval_selected').select(fresh['approval_request_id']).run(timeout=60)
        app.text_input(key='approval_actor').set_value('Human')
        next(w for w in app.checkbox if w.label=='提案内容を人間が確認しました').check().run(timeout=60)
        self.button(app, '提案を承認').click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertEqual('APPROVED', service.get(fresh['approval_request_id'])['status'], [w.value for w in app.error])

    def test_ui_create_approve_execute_and_link(self):
        app = self.publish_from_ui()
        r = ApprovalService(self.factory).list()[0]
        self.assertEqual('SUCCEEDED', r['status'])
        self.assertEqual(self.product_id, r['product_id'])
        self.assertTrue(r['external_listing_id'].startswith('MOCK-'))
        self.assertIn('承認・実行', {t.label for t in app.tabs})

    def test_ui_change_edit_approve_comparison_and_end_confirmation(self):
        app = self.publish_from_ui()
        app.selectbox(key='proposal_action').select('UPDATE_PRICE').run(timeout=60)
        next(w for w in app.number_input if w.label=='提案価格').set_value(35.0)
        next(w for w in app.text_input if w.label=='変更理由').set_value('Cost changed')
        self.button(app, '変更提案を保存').click().run(timeout=60)
        service = ApprovalService(self.factory)
        pending = next(r for r in service.list() if r['status']=='PENDING')
        app.selectbox(key='approval_selected').select(pending['approval_request_id']).run(timeout=60)
        next(w for w in app.number_input if w.label=='提案価格' and w.key.startswith('approval_')).set_value(36.0)
        next(w for w in app.checkbox if w.label=='提案内容を人間が確認しました').check().run(timeout=60)
        self.button(app, '編集して承認').click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertEqual(36, json.loads(service.get(pending['approval_request_id'])['approved_payload_json'])['changes']['price'])
        mapping = service.listings()[0]
        end = service.propose_change(mapping['marketplace_listing_id'], 'END_LISTING', {}, reason='End reason',
            source_status='Supplier unavailable', actor_id='Human', idempotency_key='ui-end')
        app.run(timeout=60)
        app.selectbox(key='approval_selected').select(end['approval_request_id']).run(timeout=60)
        next(w for w in app.checkbox if w.label=='提案内容を人間が確認しました').check().run(timeout=60)
        self.assertTrue(self.button(app, '提案を承認').disabled)
        next(w for w in app.checkbox if w.label=='このMock出品を終了することを最終確認しました').check().run(timeout=60)
        self.button(app, '提案を承認').click().run(timeout=60)
        self.assertTrue(self.button(app, 'Mock実行').disabled)
        self.assertEqual([], list(app.exception))

    def test_ui_reject_and_missing_actor(self):
        did = self.seed()
        service = ApprovalService(self.factory)
        r = service.propose_create(did, actor_id='AI', idempotency_key='ui-reject')
        app = self.app()
        self.button(app, '提案を却下').click().run(timeout=60)
        self.assertTrue(any('操作者名' in e.value for e in app.error))
        app.text_input(key='approval_actor').set_value('Human')
        self.button(app, '提案を却下').click().run(timeout=60)
        self.assertEqual('REJECTED', service.get(r['approval_request_id'])['status'])
        self.assertEqual([], list(app.exception))

    def test_unmigrated_ui_does_not_apply_stage6(self):
        app = self.app()
        self.assertTrue(any('DB基盤は未適用' in w.value for w in app.warning))
        with self.factory() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='approval_requests'").fetchone())

    def test_rejected_create_can_be_proposed_again(self):
        self.seed()
        app = self.app()
        app.text_input(key='ai_draft_actor').set_value('Human')
        self.button(app, '公開提案を承認キューへ').click().run(timeout=60)
        app.text_input(key='approval_actor').set_value('Human')
        self.button(app, '提案を却下').click().run(timeout=60)
        self.button(app, '公開提案を承認キューへ').click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        rows = ApprovalService(self.factory).list()
        self.assertEqual(2, len(rows))
        self.assertEqual({'PENDING','REJECTED'}, {r['status'] for r in rows})

    def test_turso_configured_ui_allows_only_mock_and_keeps_legacy_empty(self):
        self.seed()
        with patch.object(self, 'seed'), patch('app_database.remote_database_is_configured', return_value=True):
            app = self.publish_from_ui()
            self.assertEqual([], list(app.exception))
            self.assertTrue(any('通常の出品・送料・利益データは変更しません' in w.value for w in app.caption))
        with self.factory() as c:
            self.assertEqual(0, c.execute('SELECT COUNT(*) FROM listings').fetchone()[0])
            self.assertIsNone(c.execute('SELECT listing_id FROM marketplace_listings').fetchone()[0])

    def test_production_mode_ui_is_disabled(self):
        self.seed()
        with patch('integrated_ebay.approval_ui.execution_mode', return_value='PRODUCTION'):
            app = self.app()
            self.assertTrue(any('Sandbox・Productionは実行できません' in w.value for w in app.warning))

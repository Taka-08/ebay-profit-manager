# 第5段階: 承認・公開フロー（ローカル / Mock）

## 実装範囲と安全境界

第4段階の下書き・履歴・商品マスター・登録Serviceを継続利用する。
今回の公開は外部通信のないMockだけ。本番eBay API、OAuth、Sandbox API、
Outbox Worker、仕入先監視、価格変更、在庫停止は実装していない。

- 承認だけでは公開も出品管理登録も実行しない。Outboxも作らない。
- Mock公開はローカルDBで明示的にチェックを入れた場合のみ有効。
- Turso接続が設定されている場合はUIとServiceの両方でMock公開を拒否する。
- LIVE / SANDBOXのProviderは生成できず、Secretsの追加だけでは有効にならない。
- 操作者名は監査用の自己申告。ログイン認証や承認者の本人確認ではない。
- 既存94件・既存送料スナップショットは変更しない。本番の追加Migration反映状況は末尾に記載。

## 処理フロー

1. 商品マスターから下書きを作成し、既存のローカル生成で内容を準備する。
2. 人間が本文、Category、Condition、Item Specifics、販売条件、SKU、原産国、
   HS/HTS、重量・寸法、仕入費用、配送条件を編集・保存する。
3. DRAFTから明示的にREADY_FOR_REVIEWへ進み、確認チェックと承認操作を行う。
4. 必須項目、数値、在庫、SKU、既存公開情報を検証する。失敗時は承認しない。
5. 承認したrevision全体を`approved_snapshot_json`へ固定保存し、公開予約を作る。
6. 人間が別の「Mockで公開」操作を実行する。状態と在庫を再確認してPUBLISHINGへ進む。
7. Providerから`MOCK-...` IDを取得する。実際のeBay Item IDやURLではない。
8. 既存`ListingRegistrationService`を共有トランザクションで呼び出す。
   同じproduct_idのlistings登録、公開結果保存、監査ログを一括コミットする。
9. UIを再描画し、PUBLISHED、Mock ID、出品管理ID、公開日時を表示する。

利益再計算には出品管理の既存`calculate_expected_values`を渡す。
承認済み版の新規登録内容だけを計算し、既存商品の計算は更新しない。
既存の`shipping_breakdown_json`文字列はそのまま保存する。
送料スナップショットがない場合は既存DB仕様の空文字を使い、NULLは書き込まない。
仕入価格・仕入元URL・生成プロンプト等はProvider用データに渡さない。

## 状態・二重公開防止

既存listing_draftsのCHECK制約を作り直さないため、下書きの状態と公開の状態を分離した。
UIでは公開情報があれば、その状態を表示・絞り込みに使用する。

- 下書き: DRAFT / READY_FOR_REVIEW / APPROVED / REJECTED / ARCHIVED。
- 公開: APPROVED / PUBLISHING / PUBLISHED / FAILED / CANCELLED。
- 編集・再生成は承認を解除する。未送信の公開予約はCANCELLEDとして履歴に残す。
- 公開開始後の版は編集・再生成・承認解除を禁止する。
- 第4段階で既に承認されていた下書きは自動で公開可能にはしない。第5段階で再レビューが必要。
- `BEGIN IMMEDIATE`で公開権の取得と状態更新を直列化する。
- 有効な公開予約はproduct_id、listing_draft_id、SKUごとに1件（CANCELLEDを除く）。
- `idempotency_key = publish:MOCK:<draft_id>:<approved_revision>`を一意に保持する。
- `(mode, ebay_item_id)`にも一意制約を持つ。
- 既にPUBLISHEDなら同じ結果を返し、Providerやlistingsへ二重に送らない。

これは現在のローカル/Mock処理の保証であり、未接続のeBay APIに対する
exactly-once保証ではない。外部eBay出品済み情報の完全な検出もまだできない。

## 失敗・再試行

- 確定した失敗はFAILED、エラーコード・内容・発生日時・試行回数を保存する。
- 下書き、商品、承認版は削除しない。再試行でも同じidempotency_keyを使う。
- タイムアウト等で結果が不明なら`reconcile_required=1`とし、再送を止める。
- Provider成功後にローカルDB保存が失敗した場合はPUBLISHINGを残す。
  部分的なlistings登録はロールバックし、明示的な結果照合で復旧する。
- Mockの照合はキーから同じIDを決定的に再現するシミュレーション。
  実eBayに問い合わせているわけではない。
- 再試行回数は`max(attempt_count - 1, 0)`。過去のエラーはAudit Logにも残る。

## DB / Migration

追加Migration: `0004_listing_publications`。ローカルの検証DBにのみ適用した。
初回ローカル検証完了時点では本番未適用。後日の承認済み反映記録は末尾を参照。

- `listing_drafts.publication_input_json TEXT NOT NULL DEFAULT '{}'`を追加。
- `listing_publications`テーブルを追加。
- 主な列: publication_id、listing_draft_id、product_id、approved_revision、mode、status、
  sku、marketplace、currency、final_price、quantity、idempotency_key、approved_snapshot_json、
  listing_payload_json、ebay_item_id、listing_url、listing_id、approved_by、attempt_count、
  reconcile_required、error_code、error_message、failed_at、created_at、updated_at、published_at。
- 部分一意index: product_id / listing_draft_id / sku（status <> CANCELLED）。
- index: `(status, updated_at)`。一意制約: idempotency_key、`(mode, ebay_item_id)`。
- 既存listingsへの列追加・行更新・product_idバックフィルは行わない。
- schema_migrationsに記録し、二重実行しない。

SQLiteとローカルlibSQLに同じMigration・Serviceテストを適用する。
実Tursoのネットワーク接続・本番Migrationは今回の確認範囲外。

## Audit Log

既存`audit_logs`を利用し、操作者・日時・before/afterを保存する。

- `listing_draft.ai_generated`
- `listing_draft.updated`
- `listing_draft.approved`
- `listing_draft.rejected`
- `publication.cancelled`
- `publication.started`
- `publication.succeeded`
- `publication.failed`
- `listing.registered`

公開系ログにはproduct_id、listing_draft_id、idempotency_key、modeも含める。

## 第5段階のファイル

変更済みの本体:

- `ebay_listing_manager/streamlit_app.py`: 既存の利益計算関数を下書き画面へ渡す1か所。
- `integrated_ebay/draft_service.py`: 承認検証・版固定・状態遷移・承認解除。
- `integrated_ebay/listing_draft_ui.py`: 既存下書き画面へ承認入力・公開パネルを接続。
- `integrated_ebay/migrations.py`: 0004登録。
- `integrated_ebay/services.py`: 登録Serviceで呼出元トランザクションを共有可能にする。

新規の本体:

- `integrated_ebay/publication_migration.py`
- `integrated_ebay/publication_repository.py`
- `integrated_ebay/publication_provider.py`
- `integrated_ebay/publication_validation.py`
- `integrated_ebay/publication_service.py`
- `integrated_ebay/publication_ui.py`

既存テストの更新:

- `tests/test_integrated_foundation.py`
- `tests/test_product_catalog.py`
- `tests/test_listing_drafts.py`
- `tests/test_listing_draft_ui.py`

新規テスト・検証:

- `tests/test_listing_publications.py`
- `tests/test_publication_ui.py`
- `tests/manual/run_stage5_regression.py`
- `tests/manual/publication_preview.py`
- `tests/manual/verify_publication_layout.cjs`
- 本ドキュメント。

FedEx関連、rootの`streamlit_app.py`、`shipping_rates.json`、既存設計文書の差分は
今回より前の作業として保持し、第5段階の変更には含めない。

## 検証手順と記録

`tests/manual/run_stage5_regression.py`は一時ワークスペースへDBを隔離し、
Turso環境変数とSecrets読込みを無効化する。161件の対象テストを検出する。
検証ログは`.tmp_stage5/regression.log`、集計は`.tmp_stage5/regression.json`。

公開テストはSQLite / ローカルlibSQLの双方で94件の合成既存レコードを用意し、
Migration前に一時DBをバックアップする。Migration・新規登録後に既存全行と
送料JSONが一致し、product_idがNULLのままであることを検証する。
合成94件の検証と本番94件の再照合は区別する。本番には接続していない。

ブラウザ検証は新規の`.tmp_stage5/preview/resume_final2`DBと127.0.0.1:8515の
新しいサーバーを使用。外部HTTPをブロックし、Chrome / WebKitそれぞれ
1440 / 390 / 414 / 360pxで承認からMock登録まで操作する。
入力欄の横はみ出し、固定ヘッダーとの重なり、ボタンの寸法、JS例外を確認する。
記録は`.tmp_stage5/screenshots/results.json`と同フォルダのPNG。

### 最終結果（2026-09-11）

- 全回帰テスト: **161 / 161成功、失敗0、エラー0、スキップ0**。所要189.667秒。
- 内訳: 既存117件 + 公開Service/DB42件 + 公開UI2件。
- Chrome / WebKit × 1440 / 390 / 414 / 360px: **8 / 8成功**。
- 全条件で編集・レビュー・承認・Mock公開・出品管理登録・公開後の編集禁止を確認。
- 固定ヘッダー下端60pxに対しタイトル上端はPC約105px、スマホ約103.8px。
  タイトル重なりなし。入力欄の横はみ出し0、JS例外0。
- Mock公開ボタンはPC40px、スマホ46pxの高さ。スマホで画面内に収まる。
- ブラウザ検証DB: products 8件 / publications 8件 / listings 8件。
  全8件が同じproduct_id・SKUで紐付き、Mock IDとpublished_atを保持。Outbox 0件。
- 検証DBの`integrity_check=ok`、外部キー違反0、0004の履歴1件。
- 94件の合成既存レコードの全行・送料JSON・NULL product_id保持テストも成功。
- 中断時の回帰テスト1件・WebKit操作のタイムアウトは再検証で解消。
  機能コードを変更せず通過した。中断時ログも別名で保持した。
- 第5段階の変更済み追跡ファイルに`git diff --check`のエラーなし。
- FedEx関連7ファイル、既存統合設計文書、Cloud Secretsのハッシュは前回記録と一致。
- HEADは`139ab7e10f565df39098054b910c3ce1dc48de8d`のまま。Stage5は未Commit・未Push。

ローカル/Mockの第5段階は検証完了。本番への適用可否は、下記の承認・バックアップ・
実Turso確認を経て判断する。実eBayへの出品準備が完了したという意味ではない。

## 本番反映・実eBay接続の運用チェックリスト

1. ユーザーの明示承認前に本番DB変更・Push・Deployをしない。
2. 承認後もまず最新本番バックアップと復元手順を確保し、既存94件・送料JSONの
   比較基準を取得する。ローカルテストDBのバックアップで代用しない。
3. 0004適用・二重実行防止・既存全行不変を本番で確認する。
   アプリ起動時にもMigrationが実行される構造なので、バックアップ・承認前に
   Pushだけを先行しない。
4. 第5段階ファイルだけをCommit対象に選ぶ。FedExの未コミット変更を混ぜない。
5. 既存Cloud両アプリへの反映と実接続・画面を確認する。新しい環境は作らない。
6. 本番承認操作の権限・認証を設計する。自己申告の操作者名だけで実出品を許可しない。
7. eBay OAuth・スコープ・Inventory等の実Provider、カテゴリ/Condition/必須Specifics、
   画像、配送/返品/支払ポリシー、在庫ロケーション、公開条件を公式APIで検証する。
8. 実APIのOffer ID/Item ID保存・結果照合・通信結果不明時の復旧をSandboxで検証する。
   Mockの決定的ID生成を実際の照合処理として流用しない。
9. Mockの承認版や公開結果をLIVEへ自動転用せず、本番用内容を再確認・再承認する。
10. 実eBayへの送信はさらに明示的な承認後に行う。第6段階には自動で進まない。

## 承認済み本番反映の準備記録（2026-09-11）

- ユーザーによる第5段階のみの本番Migration・Commit・Push・既存Cloud反映の承認を受領。
- 11:58 JSTに本番全体をSQL/SQLiteへバックアップ。SQLite/libSQL復元・全行一致・
  Migration予行演習・二重実行防止を確認した。
- 11:59 JSTに本番へ0004のみ追加。既存94件・送料JSON・全94件NULLのproduct_idは完全一致。
- 本番向けクリーンHEADに第5段階21ファイルだけを重ねた構成で149/149テスト成功。
  作業ツリー161件との差12件は、今回反映しないFedEx未コミット実装用のテスト。
- バックアップ・復元手順・個別レコードの検証証跡はGit管理外のrecovery_backupsに保管。
- 実eBay公開・Secrets変更・第6段階は対象外。CloudでもMock登録は無効のまま。
- Push・Cloud・本番画面の最終結果は作業完了報告で確定する。

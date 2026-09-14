# 第6段階: 承認・実行基盤

## 範囲と安全境界

既存の第5段階承認版・公開前検証・公開payload組立、Outbox、Auditを再利用する。
新規出品、価格変更、数量変更、出品終了、本文改訂の提案を保存し、人間の承認で
固定payloadをOutboxへ登録する。承認ボタンでは実行しない。
実行は明示的なService呼び出しのみ。自動Worker、仕入先監視、スクレイピングはない。

- `MOCK`: SQLite/Tursoの第6段階専用表に疑似出品・冪等実行結果を保存する。eBay通信なし。
- `DRY_RUN`: 承認・キュー・履歴のみ保存。公開・疑似出品・既存listings登録はしない。
- `SANDBOX` / `PRODUCTION`: interfaceのみ。全APIメソッドはDISABLEDで停止する。
- デフォルトはMOCK。`EBAY_EXECUTION_MODE`を環境変数、またはSecretsの`ebay`節から取得する。
- 接続先にかかわらずMock/Dry-runのみ許可する。Providerは組み込みMockの厳密な型チェックで限定する。
- Turso接続時の自動/ローカル用初期化は引き続き拒否する。本番Migrationは別途バックアップ・承認が必要。
- 本番Migration、Commit、Push、Cloud反映、OAuth、実出品は未実施。

## ファイル

新規:
- `integrated_ebay/approval_migration.py`: 追加型スキーマとローカル限定の明示初期化
- `integrated_ebay/approval_repository.py`: 承認要求・履歴の保存
- `integrated_ebay/approval_service.py`: 提案、承認、取消、Outbox実行、失敗・照合
- `integrated_ebay/ebay_api.py`: 共通Provider、永続Mock、無効なSandbox/Production/OAuth境界
- `integrated_ebay/approval_ui.py`: 承認・実行タブ、比較、編集、確認チェック
- `tests/test_approval_execution.py`, `tests/test_approval_ui.py`: 関連自動テスト
- `tests/manual/approval_preview.py`, `tests/manual/run_stage6_regression.py`: 隔離検証
- 本文書

既存への変更:
- `integrated_ebay/migrations.py`: 明示指定したmigration集合を適用する引数を追加。既定の4件は変更しない。
- `integrated_ebay/publication_service.py`: 第6段階適用DBでの旧公開経路の迂回防止。
- `integrated_ebay/listing_draft_ui.py`: 承認済み下書きから公開提案への連携。
- `ebay_listing_manager/streamlit_app.py`: 既存タブを保持して承認・実行タブを追加。

## Migration

`0005_approval_execution`。既存テーブルのALTER、行UPDATE、削除、バックフィルなし。

|追加テーブル|役割|
|---|---|
|approval_requests|product/draft/publicationとの関係、提案・固定payload、承認者、状態、版、エラー、試行数、冪等キー|
|approval_execution_attempts|要求IDと試行番号を複合主キーにした実行履歴|
|marketplace_listings|product/draft/approval/Mock Item ID/SKU/marketplace/疑似公開日時、現在のMock状態。listing_idはNULL|
|ebay_mock_listings|Provider側の疑似出品状態|
|ebay_mock_receipts|冪等キーに対する処理種別・payloadハッシュ・確定結果|

要求のidempotency_key、Mock結果のidempotency_key、外部出品ID、publication IDを一意にする。
商品・モードごとの有効CREATE要求は部分一意indexで1件に制限する。
既存listings.product_idのnullable定義と、過去のshipping_breakdown_jsonは変更しない。
未適用の0005内だけでmarketplace_listings.listing_idをnullableにした。既存テーブルへのALTERはない。
旧定義を適用した検証用DBを流用せず、新しい一時DBで検証する。本番0005は未適用。

ローカル初期化は、隔離DBへのfactoryで`initialize_approval_storage(factory)`を明示呼び出しする。
UI起動だけで第6段階Migrationは実行されない。本番では未適用表示になる。

## 処理フロー

1. 商品マスターから既存のAI下書きを作成・編集し、第5段階の必須検証と人間レビューを通す。
2. 公開提案を作成する。CREATEには承認済みpublication IDを固定し、私的仕入情報を送信payloadから除外する。
3. 承認・実行画面で確認。UPDATE_PRICEは旧/新価格・差額・変化率、数量は旧/新数量を表示。
4. PENDINGのみ編集・承認・却下が可能。編集して承認では保存が成功した版を承認する。
5. APPROVEDとOutbox登録を同一トランザクションで保存。ENDには終了理由と明示確認を固定する。
6. 実行時にモード、承認状態、キューの要求ID/payloadハッシュ、対象版を確認し、短いトランザクションでEXECUTINGを確保。
7. DBトランザクション外で永続Mock Providerを呼ぶ。CREATEも第6段階専用の冪等キーで処理する。
8. 結果・連携データ・実行履歴・Audit・Outbox完了を保存する。通常listingsは増やさない。

2026-09-14の追加指示により、Mockから第5段階のpublish/reconcile/ListingRegistrationServiceを呼ばない。
publicationはAPPROVEDのまま保持し、Mock成功状態・Item IDは第6段階側だけに保存する。
既存の公開前検証を読み取りで再利用し、現在の下書き版・商品・在庫も確認する。
第5段階の通常登録経路をTursoで解放しない。0005適用後の旧publish経路の迂回も拒否する。

UPDATE/REVISE/ENDはMock現在値だけを更新する。既存listingsの販売価格・状態・送料・利益は履歴として保持する。
数量0とENDは独立した操作であり、自動変換しない。既存の実商品・第5段階の旧Mock出品を自動取り込みしない。

## 固定版と再試行

- 承認連打は同じ要求を返す。実行連打・並行実行は状態claimと一意制約で防ぐ。
- Providerの冪等結果はプロセス再起動後もDBから復元する。単なるメモリ内の実行済み集合ではない。
- 編集後も旧approved_payloadを変更しない。実行前に下書き不一致を検出したらAPPROVAL_MISMATCHで送信を止める。
- 不一致は結果不明ではない。取消 → 下書きを再レビュー・承認 → 新規提案 → 再承認へ戻れる。
- 明確な未実行失敗は同じ固定payloadで再試行できる。現在値が変わった提案は取消・再提案が必要。
- 結果不明ならFAILED/reconcile_requiredを保存し、自動再送を拒否。保存済み結果を照合する。
- receiptがない結果不明状態は自動解除しない。誤った再送を防ぐため調査を要する。
- 保存障害後は同じ要求の確定Mock receiptから専用連携データだけ復旧する。下書きが後で編集されても上書きしない。

Auditはproposal.created、approval.approved/rejected/edited/cancelled、ebay.execution.queued/started/succeeded/failed、
listing.mock_published/updated/endedを保存する。actor_typeはhuman/ai/systemを区別する。
画面の操作者名は自己申告であり、本人確認済みIDではない。実API解放前に認証・権限との結合が必要。

## OAuth・実APIを有効化する前の残作業

環境別`EBAY_SANDBOX_*` / `EBAY_PRODUCTION_*`のCLIENT_ID、CLIENT_SECRET、REFRESH_TOKEN、ACCESS_TOKEN、
REDIRECT_NAMEを読み込める設定モデルのみ追加した。値はrepr・UI・ログに出さず、今回読み込み/変更/取得しない。
OAuth認証、リフレッシュ通信は無効。単にproduction設定へ変えても動作しない。

固定payloadは内部の共通DTOであり、そのままeBay APIに送信できる公式wire形式ではない。
Inventory API adapter、inventory item/offer ID管理、business policies、merchant location、画像・Category/Specifics検証、
権限・認証、レート制限、API別の重複照合、Sandbox実通信試験を別途承認後に実装する必要がある。

公式資料:
- https://developer.ebay.com/develop/guides/sell/authorization
- https://www.developer.ebay.com/api-docs/sell/static/inventory/publishing-offers.html
- https://developer.ebay.com/api-docs/sell/static/inventory/managing-offers.html

## 検証と保全

検証ログはGit対象外の`.tmp_stage6`。既存テストの出力を上書きしない。
一時DBの94件fixtureで全行・送料JSON・NULL product_idの不変を検証する。SQLiteとローカルlibSQLで実行する。
本番Tursoには接続しない。本番94件の再取得やMigrationは今回のローカル検証と区別する。
FedEx差分・rootの利益計算UI・料金JSON・Secretsは既存SHA256と比較する。

## 本番反映前の停止点・ロールバック

TursoでのMock許可・専用データへの隔離はユーザー承認済み。ただし今回の追加修正はローカル検証まで。
本番バックアップ取得、Migration、Commit、Push、Cloud反映は、検証報告後の別途承認まで実施しない。

本番反映を承認された場合の事前手順:
1. 更新操作を停止し、接続先を確認。反映直前の全テーブル・全行・schema・sequenceを新規バックアップする。
2. SQLite/ローカルlibSQLの別コピーへ復元し、整合性、94件、全行、送料JSON、product_id、ハッシュを比較する。
3. コピーに0005を適用し、追加5表・index・一意制約・再実行無変更を確認する。
4. 保全確認と明示承認後に限り本番へ0005を適用。前後比較に異常があればCommit/Pushへ進まない。
5. 第6段階のファイルだけ選択。FedEx差分は除外し、既存アプリへ反映・読み取り検証する。

Migration中の失敗はトランザクションrollback。アプリの問題だけなら第6段階Commitをrevertし、追加表は残す。
データ復元が必要な場合、異常状態も保全し、別の復旧用DBへ直前バックアップを復元・全件照合する。
本番DBを削除したりSQLを直接流して上書きしたりしない。切替・Secrets変更・復旧デプロイにも別途承認を得る。
過去の第5段階バックアップは現時点の本番復元点の代用にしない。

## 追加修正前の確認記録（2026-09-14）

- 停止前の全回帰: 223件成功、失敗0、スキップ0（`.tmp_stage6/full.json`）。今回不要な全再実行はしない。
- 最終修正版の関連検証: 46件成功、失敗0、スキップ0（`.tmp_stage6/test_approval_all.json`）。
  SQLite 20件 + ローカルlibSQL 20件 + Streamlit UI 6件。
- UIの再承認テストで確認者名が空欄だと拒否されたため、再入力する実操作に合わせて再検証し成功。
- 取消 → 元下書きの再承認 → 再提案 → 再承認、およびServiceでの再公開・1件だけの登録を確認。
- 旧承認payload保持、未送信のAPPROVAL_MISMATCH表示、取消可能、二重承認・並行実行・未知結果照合を確認。
- 新しい一時DBを使用した127.0.0.1:8676のプレビューでPC1440 / 390 / 414 / 360pxを確認。
  全幅でページ横はみ出しなし。スマホ操作ボタン高さ46px。PCタイトル文字上端105px、固定ヘッダー下端60px。
  414pxでAPPROVED→SUCCEEDED、390pxでPENDING→CANCELLEDの同期、360pxで編集欄・既存AI画面を確認。
  選択欄は不変のIDを表示し、直下に最新状態を表示する。可変状態名の選択ラベルキャッシュを避ける。
- ブラウザでの実行対象は一時DBのMockのみ。検証サーバー停止・画面幅設定解除済み。
- 保護対象9ファイルは既存SHA256と一致。FedEx差分、shipping_rates.json、利益計算UI、Secretsを保持。
- ローカル94件fixtureの全行・送料JSON・NULL product_id保持を検証。本番DBは今回未接続・未変更。
  本番の現在件数の再取得はしていない。既存本番バックアップのSQLite/SQLのSHA256は元のmanifestと一致。
- HEAD / origin/mainは22f9994c00764e9e6ad0da03a711421c482ddc0fのまま。ステージ済み差分なし。
- 本番Migration、Commit、Push、Cloud反映、eBay通信、OAuth、Secrets変更、第7段階は実施していない。

上記は今回の保存先分離前の検証履歴。追加修正版の結果は後段の記録を参照。

## 追加修正版の最終検証（2026-09-15）

### 修正範囲

- `ebay_api.py`: 接続先ではなくMOCK/DRY_RUNで許可。SANDBOX/PRODUCTION/OAuthは通信しない。
- `approval_service.py`: 組み込みMockのみ受理。公開前検証を読み取りで再利用し、Mockから通常登録を呼ばない。
  CREATE/変更/終了/照合は第6段階専用表と、その承認要求に対応するAudit/Outboxだけに保存する。
- `approval_ui.py`: Turso設定だけでは無効にしない。専用保存の確認文言とMock表示を維持する。
- `publication_service.py`: 第6段階適用時の旧publish迂回を拒否。通常登録のTurso禁止は解除していない。
- `approval_migration.py`: 未適用0005の新規表`marketplace_listings.listing_id`をnullableに変更。
  Mock保存値はNULL。既存listingsや既存カラムを変更するMigrationは追加していない。
- `tests/test_approval_execution.py`, `tests/test_approval_ui.py`: Turso設定下のMock許可・既存表書込拒否・通信禁止等を追加。
- `tests/manual/approval_preview.py`: 偽Turso設定と強制ローカル接続を分離した検証環境。
- `tests/manual/run_stage6_regression.py`: 以前のログを上書きしない日時別出力。
- 本文書。9月15日の再開後はアプリコード・テストを再変更せず、残りの表示検証と本記録のみ追加。

### 自動テスト

全回帰265件成功、失敗0、エラー0、スキップ0。
ログ: `.tmp_stage6/mock_boundary_20260914-133406-643707/full.log` / `full.json`。
停止中に完了していた結果を確認して引き継ぎ、9月15日に再実行していない。

内訳: 第6段階86件（SQLite26、ローカルlibSQL26、Turso設定ありのローカルlibSQL26、Streamlit UI8）
+ 既存回帰179件。実Tursoネットワークへの試験ではなく、既存互換ラッパーと実libSQLエンジンを使う隔離試験。

- 未承認実行拒否、二重承認、並行実行、冪等receipt、失敗/再試行/未知結果照合を確認。
- APPROVAL_MISMATCH、取消/再提案/再承認/Mock実行、承認版保持を確認。
- テスト中はsocket/DNS/HTTP、Sandbox/Production、OAuth、旧publish/reconcile、通常登録を禁止し、
  Mockの新規・価格・数量・改訂・終了がこれらを呼ばず成功することを確認。
- 既存表のINSERT/UPDATE/DELETEを拒否するトリガーを一時DBに設定して検証。
  94件fixtureの全行、送料JSON、NULL product_id、既存商品/在庫/下書き/公開承認版を保持。
- 本番モードや外部Provider/Mock偽装サブクラスは受理しない。Turso用初期化ガードも維持。

### 表示と操作

前回の390/414px成功結果を保持し、停止していた一時DBを再開して360/1440pxを完了。
検証URLは`127.0.0.1:8677`、DBは`.tmp_stage6/preview/remote-mock-20260914-1335/`配下のみ。
Turso設定を模したUIでも接続関数はこのローカルDBに固定。本番Cloudにはアクセスしていない。

|幅|結果|
|---|---|
|1440px|承認画面・PENDING状態・Mock明示・ボタン配置正常。タイトル文字上端77px、固定ヘッダー下端60px。横幅1440px内|
|390px|前回確認済み。APPROVEDからCANCELLEDが即時反映。ページ横幅390px、ボタン高さ46px|
|414px|前回確認済み。数量変更を承認してMock実行しSUCCEEDEDを表示。ページ横幅414px|
|360px|編集/保存→APPROVAL_MISMATCHで未実行停止→取消→再レビュー/再承認→再提案→承認→Mock成功まで確認|

360pxの選択中表示とカードがFAILED/CANCELLED/APPROVED/SUCCEEDEDに同期。
入力・ボタンの横はみ出しなし。ボタン幅327.625px・高さ46px。
タイトル文字上端78.796875px、固定ヘッダー下端60px。新規アプリ例外なし。
一時DBの最終値: 通常listings 0件（増加なし）、Mock専用連携2件、通常listing_id非NULL 0件、
Mock receipt3件、承認要求CANCELLED2/PENDING1/SUCCEEDED3、integrity_check=ok。

### 保全と停止点

- 本番Tursoへ未接続・未変更。今回の94件検証は一時fixtureであり、本番行の再取得・再照合は実施していない。
- FedEx差分、root利益計算UI、shipping_rates.json、Secrets等の保護対象9ファイルが既存SHA256と一致。
- HEAD/main/origin/mainは`22f9994c00764e9e6ad0da03a711421c482ddc0f`。ステージ済み差分なし。
- 新しいCommit/Push、最新本番バックアップ、本番Migration、Cloud反映、実eBay/OAuth、第7段階は未実施。
- ローカル/Mockの追加修正検証は完了。本番反映の事前手順へ進めるが、最新バックアップ・復元試験・
  本番Migration・Cloud確認は別途承認後に実施する。実eBay経路を有効にしてよいという意味ではない。

## 最終記録の確定

利用制限からの再開後、上記265件の完了ログとPC/390/414/360pxの検証記録を引き継ぎ、
テスト・ブラウザ検証は再実行していない。追加のアプリコード修正は不要。
検証サーバーPID19188は終了済み。画面幅オーバーライドは前回解除済み。
今回の追記対象は本文書のみ。アプリコード、DB、保護対象ファイル、Secretsは変更していない。
HEADは22f9994のまま、ステージ済み変更なし。第6段階の変更と既存FedEx差分は未コミットのまま保持。

判定: 第6段階のローカル/Mock実装・追加修正・検証は完了。本番反映そのものは未実施。
本番Tursoのネットワーク挙動や本番Cloudでの動作確認を完了したという意味ではない。

次回、明示承認を得てから行う作業:
1. 本番接続先、実際の既存件数、第6段階限定のGit差分を確認する。
2. 最新の本番バックアップを取得し、別の一時DBへ復元・照合する。
3. コピー上で0005の予行演習、再適用時の無変更、既存全行・送料JSON・product_id保持を確認する。
4. 本番へ0005のみ適用し、件数・全行・スナップショット・既存IDが一致することを検証する。
5. 第6段階のファイルだけCommit/Pushする。FedEx差分・Secrets・送料JSONは含めない。
6. 既存Streamlitアプリへの反映を確認し、Mock限定の起動・接続・画面検証を行う。

異常があれば次へ進まず停止する。上記は未実行の手順であり、今回の承認範囲に含めない。
本番eBay/OAuth/production有効化、第7段階には進まない。

## 本番反映の事前検証・Migration記録（2026-09-15）

以下は上記ローカル検証後、ユーザーの本番反映承認を受けて実施した記録。

- 反映前HEAD/main/origin/mainは22f9994。両既存Cloudアプリの正常起動を確認。
- 本番Tursoは94件、product_idは全94件NULL、0001〜0004適用済み。
- 最新バックアップ: `recovery_backups/turso_prod_pre_0005_20260914T230706Z/`。
  SQLiteとSQL dump、全テーブル件数・ハッシュ・復元手順をGit対象外に保存。
  SQLite/ローカルlibSQLへ独立復元し、全行・schema・sequenceの完全一致と整合性を確認。
- コピー上で0005をSQLite/libSQLそれぞれ1回適用。2回目は未実行、既存全表・94件・送料JSON・product_id不変。
- FedEx差分を除いたHEADベースの本番候補で253件成功、失敗0、エラー0、スキップ0。
  第6段階86件と既存回帰167件。作業ツリーの265件との差12件は未反映FedEx用テスト。
- 候補のバイト比較はGitのCRLF/LF変換で不一致だったため、Git正規化後のblobで照合。
  root利益計算UI・送料JSON・既存料金生成処理はHEADと一致。FedEx差分の混入なし。
- 本番0005適用後: 既存94件の全行、送料JSON、全NULLのproduct_id、既存全表・sequence・schemaが一致。
  schema_migrationsは既存4件を保持して0005を1件追加。第6段階5表は空。
- 保護対象9ファイルは保存済みSHA256と一致。Secrets/送料JSON/FedEx差分は変更していない。
- 実eBay通信、OAuth、Production有効化、通常listingsへのMock追加は実施していない。

Commit/Push/Cloud確認と本番Mock操作の最終結果は、別途本番反映報告で確定する。
本番の商品マスター・下書きは0件だったため、Mock確認用の新規検証データ作成をユーザーへ確認中。
既存94件の変更やproduct_id付与によってテスト対象を作成しない。

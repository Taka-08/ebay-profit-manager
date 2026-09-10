# 第4段階: AI出品下書き（ローカル実装）

## 再開時の確認

未コミットのファイルを保ったまま続行した。下書き基盤・履歴・生成Service・ローカルProvider・失敗/競合保護・Outbox非生成は完成済み。SQLite/ローカルlibSQLの36件は成功済みだったため、作り直していない。

再開時に実行中だった全回帰テストの終了結果を回収し、115件成功（既存75件 + 第4段階40件）、失敗0件を確認。残りは依存ファイルの整合、実ブラウザによるスマホ確認、最終報告だった。FedEx関係の既存未コミット変更には手を加えていない。

## 1. 変更したファイル

- `integrated_ebay/migrations.py`: 0003を登録。0001/0002の定義・実行処理は変更なし。
- `integrated_ebay/product_master_ui.py`: product_idを引き継ぐ遷移ボタン。
- `ebay_listing_manager/streamlit_app.py`: 既存タブに「AI出品」を追加。
- `requirements.txt`, `ebay_listing_manager/requirements.txt`: Streamlit下限を1.63に統一。ネイティブの選択タブSession State APIを使用するため。実際の検証環境も1.63。
- `tests/test_integrated_foundation.py`, `tests/test_product_catalog.py`: 全migration数の期待値を3に追加。既存の非破壊・登録テストは維持。

## 2. 新規ファイル

- `integrated_ebay/draft_migration.py`
- `integrated_ebay/draft_repository.py`
- `integrated_ebay/draft_service.py`
- `integrated_ebay/ai_listing.py`
- `integrated_ebay/listing_draft_ui.py`
- `integrated_ebay/prompts/ebay_listing_v1.txt`
- `tests/test_listing_drafts.py`
- `tests/test_listing_draft_ui.py`
- `tests/manual/listing_draft_preview.py`
- `tests/manual/verify_listing_draft_layout.cjs`
- 本書

## 3-6. Migration・テーブル・履歴

3. Migration: `0003_listing_drafts`。適用先はテスト用SQLite/ローカルlibSQLのみ。本番へは未適用。
4. 追加テーブル: `listing_drafts`, `listing_draft_revisions`。products/listingsへの新規カラム追加・UPDATE・バックフィルなし。
5. `listing_drafts`: `listing_draft_id`は`ldr_`+UUID4、`product_id`はNOT NULLの外部キー。marketplace/site/status、title/description、category/conditionのID・名称、price/currency/quantity、item_specifics/shipping_profile/generation_input/generation_output/review_notesのJSON、ai_model/prompt_version、作成者・時刻、承認者・時刻、revision/last_actor_typeを保持。価格・数量はNULL可。商品×更新日時、状態×更新日時のindexを追加。
6. 1商品に複数draft可。生成・編集・状態変更ごとにrevisionを増やし、版全体を履歴へINSERT。`(listing_draft_id, revision)`が履歴の主キー。更新前後はaudit_logsにも記録。古い版で編集/承認した場合は競合エラー。AI処理は書込transactionの外で行い、生成終了時に版を再確認する。

## 7-9. Provider・Prompt

7. `AIProvider` Protocol → `AIListingGenerator` → `ListingDraftService` → Repository。UIにAI通信処理は置いていない。別のProviderをServiceへ注入できる。
8. `LocalDeterministicProvider`を実装。外部LLMではなく、確認できた文字情報を決定的に整形するフォールバック。UIにも「ローカル生成モード（外部AI未接続）」と明示。テストでは戻り値・例外を差し替えたFakeとしても検証する。
9. Prompt: `ebay_listing_v1`。独立したテキストファイルと設定dataclassで版を管理。モデル名・入力・出力・Prompt版は各履歴に残る。

## 10-18. 入出力と情報の扱い

10. 入力: 商品名/SKU/JAN/EAN/UPC/ブランド/型番/カテゴリ/メモ/原産国/HS/HTS/重量/梱包寸法/仕入価格/仕入通貨、仕入先一覧・URL、画像メタデータ、在庫情報、選択した価格・通貨・送料スナップショット。現在の商品マスターを読み取るだけで更新しない。
11. 出力: 英語Title、構造化した英語Description、ローカルCategory候補、未確認ConditionとNew/Used候補、Item Specifics、確認メモ。
12. 値ごとに`value/confidence/source/needs_review`を保持。欠落情報はnull・unknown・要確認。商品マスター由来であっても外部検証済みを意味しない。梱包寸法を商品本体サイズ、型番をMPNと決めつけない。
13. Titleは設定値80文字以内、ブランド・商品名・型番の順で単語単位で収める。根拠のないRare/Authenticを追加しない。非英語名称は翻訳したふりをせず英語名確認を求める。[eBay公式のタイトル制限](https://developer.ebay.com/api-docs/user-guides/static/trading-user-guide/listing-title.html)
14. DescriptionはOverview / Condition / Specifications / Included items / Shipping origin / Notes。プレーンテキストのみ。仕入価格・仕入先URL・内部メモを商品説明へ流用しない。発送元Japanは生成policyで管理し、原産国とは分ける。
15. 商品マスターに現物状態がないため、Conditionは未確定。候補New/Usedは確認用であり、自動確定しない。傷・動作・使用感・欠品は人間がDescriptionへ追記する。
16. Item SpecificsはBrand/Model/原産国/商品識別コードを参照。素材・付属品・互換性・MPN・本体サイズ等の不足はnull。JSONを編集可能。
17. `ImageInputAdapter` + `MetadataImageAdapter`。URL/storage_key/file_name等のみ保持。画像解析・BLOB保存・外部ストレージ導入なし。ユーザーが明示的にプレビューを選んだ場合だけブラウザがHTTPS画像を表示する。サーバーは画像を取得しない。
18. 仕入先URLはスナップショットに保持するだけ。自動取得・スクレイピング・監視なし。

## 19-26. 画面・連携・承認

19. 商品マスター詳細の「AI出品下書きを作成」で同じproduct_idをAI出品タブへ渡す。商品・在庫情報は共有のProductCatalogServiceを利用する。
20. 同じproduct_idを持つ保存済みeBay出品を選択した場合、その`listing_price_usd`（旧名称、商品通貨建て）と`currency_code`、`shipping_breakdown_json`を複写。新しい為替・送料で再計算しない。未紐付けの旧商品を推測で結び付けない。未登録の利益計算結果を直接渡す新経路は作っていない。
21. 商品選択、入力元確認、生成、Title/Description/Category/Condition/Item Specifics/Price/Quantity/送料profile/確認メモの編集、保存、再生成、レビュー待ち、承認、却下、アーカイブ、履歴閲覧が可能。
22. 選択商品の下書きを状態別に絞り込み。商品名・Title・状態・作成/更新日時・最終AI/人間操作・承認者をPC表/スマホカードで表示する。
23. 承認はREADY_FOR_REVIEWの保存済み版に限定。確認チェック・操作者名・必要項目・正の価格/数量を確認し、実在庫を再取得して数量を検証。DROPSHIP数量は自動決定せず人間が入力。承認後に編集/再生成すると承認は解除。却下/アーカイブは物理削除ではない。アーカイブ版は編集せず新しいdraftを作る。
24. 生成/編集/承認/却下はOutboxを作成しない。eBay API・OAuth・外部アクションなし。承認は公開可能性の保証ではなく内部レビュー済み状態。
25. audit_logsに`listing_draft.created/ai_generated/updated/approved/rejected/archived`を記録。生成actor_type=ai、作成/編集/状態変更=human。操作者名は申告値で、認証済みIDではない。AI生成を要求した人も入力履歴に残す。
26. 768px以下は縦積み、一覧はカード、操作ボタンは46px以上。文字色はテーマを継承。AI画面に限定して選択欄・数値ステッパーの内部ボタンを全幅CSSから除外。

## 27-29. Secrets・互換性

27. 本番/ローカルSecretsを変更していない。APIキー値をコード・ログ・出力へ追加していない。
28. 今回のローカル生成にAPIキーは不要。利用可能なAIキーが確認できなかったため実LLM接続は未実装。今後は別Provider内で既存の環境変数/Secrets読込方式を使い、明示的な設定・データ送信範囲の確認後に接続する。
29. Python 3.12、Streamlit 1.63、SQLiteおよびlibsql 0.1.11のローカルDBで検証。既存RemoteCompatibleConnectionを使用。Tursoネットワーク接続・本番への適用可否は今回未検証。

## 30-32. テスト

30. 全回帰: `unittest discover tests`相当を、本番Turso環境値を空にし、DBのSecrets読込を無効化して実行。既存75件、第4段階Service/DB36件（SQLite18 + ローカルlibSQL18）、Streamlit AppTest4件、計115件成功の結果を回収した。追加修正後はAppTestを6件に拡充して再実行。外部AI APIは不使用。
31. 最終的なユニークテスト数は117件成功（既存75 + Service/DB36 + AppTest6）。115件の全回帰と、その後のUI6件の実行結果を合わせた数であり、117件を単一コマンドで再実行したという意味ではない。完成済みの基盤36件を不要に再実行していない。
32. 最終未解決失敗数は0件。テスト詳細にはmigration再実行、94件の模擬データ、全行/送料JSONの保持、Audit失敗rollback、生成timeout/不正JSON/部分応答、同時編集競合、在庫不足承認拒否、Outbox非生成を含む。追加したGBP画面テストは当初、模擬出品の必須日付等が不足して失敗したため、fixtureのみを修正して6件すべて再成功した。

ブラウザ実表示の最終結果と追加検証は本書末尾に記載する。

## 33-36. 既存データ・本番保護

33. 既存の計算式、為替、送料、関税、出品登録・CRUDの処理は変更していない。共通migration登録と出品管理のタブ/遷移だけ拡張。未コミットのFedEx修正は別件として保持している。
34. 本番94件は読み直し・再計算・UPDATEしていない。今回の非破壊自動検証は**94件の模擬データ**であり、本番全行を改めて照合したという意味ではない。
35. 本番DB接続・0003適用・既存行の変更・バックフィルは実行していない。
36. Git commit/Push・Cloud Deploy・Secrets変更は実行していない。

## 37-39. 制約と次の段階

37. 未解決/意図的に未実装: 実LLM、画像認識、自動翻訳、正規eBayカテゴリ/Condition照合、VeRO完全検査、認証された承認者ID、公開処理。在庫は承認時の妥当性確認であり、予約や自動同期は行わない。複数draftが同じ在庫を参照できるため、第5段階の公開時には再確認/予約が必要。
38. **ローカル下書き機能として検証済み。ただし、そのまま無確認で本番へ反映してよいとはしない。** 本番反映前に承認、DBバックアップ、0003差分確認、検証用Tursoでの適用、Streamlit依存更新、公開環境でのアクセス権限を確認する。通常アプリ起動時には既存のmigrationランナーが0003を実行するため、本番接続設定のままこの作業版を起動しないこと。
39. 第5段階の前に: 既存94件保護を含む本番適用手順、アカウント/操作者認証・承認権限、実Providerと情報送信許可、商品属性/Condition/カテゴリ/配送ポリシーの検証、在庫予約、承認版とOutbox冪等性、Sandbox eBay API、監査・再試行・公開失敗時の復旧方針を決める。今回はいずれも実装していない。

## ローカル検証の再現

`tests/manual/listing_draft_preview.py`は実際の出品管理エントリポイントを使う検証専用ランチャー。DBは`.tmp_stage4/preview`内に限定し、それ以外のDBパスを拒否する。環境のTurso設定/DB Secretsを使わず、直接SQLiteへ接続する。模擬商品1件だけを初回作成する。通常の起動スクリプトの代わりに検証時だけ使用する。

```powershell
streamlit run tests/manual/listing_draft_preview.py --server.address 127.0.0.1 --server.port 8514
node tests/manual/verify_listing_draft_layout.cjs
```

ブラウザ検証にはPlaywrightとChromium（またはChrome）/WebKitが必要。スクリーンショットと測定JSONはGit対象外の`.tmp_stage4/screenshots`へ出力する。コード内のDB初期化はこの模擬環境限定であり、本番商品は読み込まない。

## 最終ブラウザ検証結果

- Chromium（インストール済みChrome）とWebKit 26.5の2エンジン。
- 1440×1000、390×844、360×800、768×1024の4画面幅。
- ライト/ダークの2テーマ。合計16条件すべて成功。
- 商品マスターからAI出品への選択タブ遷移と、同じ商品のTitle表示を各条件で確認。
- 可視入力/ボタンの横はみ出し0、ページの横幅超過0、JavaScript pageerror 0。
- スマホ/タブレット幅ではカード表示、PC表非表示、承認ボタン高46px。PCでは表表示を維持。
- スクリーンショット32枚と`results.json`を`.tmp_stage4/screenshots`に保存。PC明色とWebKitスマホ暗色を目視でも確認。
- 初回に選択欄の開閉ボタンが全幅になる問題を検出し、AI画面内だけのCSSで修正。旧モジュールのキャッシュを避けるため、検証サーバーを再起動して16条件を再検証した。
- これはWindows上のブラウザエンジン検証。実機iPhone Safari/Android端末での確認や、本番Cloud画面の確認を行ったという意味ではない。
- その後の小修正（保存済みGBPの入力初期表示、不正画像URLガード）はAppTest6件で確認。生成基盤・計算・DB保存ロジックは変更していない。
- `git diff --check`は成功。Gitが通知した改行LF/CRLF警告はリポジトリ既存設定によるもの。
- 検証用サーバーは確認後に停止。本番アプリは起動/再起動/Deployしていない。

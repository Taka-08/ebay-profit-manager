# Stage 7: 承認済み出品変更の安全な実行

## 範囲

第6段階の承認・Outbox・Mock Providerを再利用する。価格変更、数量変更、数量0、終了が対象。
実eBay API、OAuth、Sandbox、Productionの通信は引き続き無効。設定変更だけでは有効化できない。
第8段階以降、自動監視、実商品への紐付けや既存94件のバックフィルは行わない。

## 調査結果

- 既存 `ebay_api.py` はネットワークを持たないMock実装で、Inventory/Tradingのいずれも未接続。
- `marketplace_listings` はMock専用。product_id、listing_draft_id、publication_id、外部ID、SKU、marketplace、versionと現在値JSONを保持する。
- Offer ID、inventoryItemGroupKey、検証済み販売者アカウント、API方式、外部の更新バージョンは保存していない。
- 通常 `listings` とMock連携データは別。Mock操作で通常listings、商品、在庫、費用、送料スナップショットを更新しない。
- 旧94件は前回本番確認ではproduct_idがNULL。実Item IDとの対応をURL等から推測しない。
- 承認者名は自己申告であり認証済みユーザーIDではない。本番書き込み前に認証・権限確認が必要。
- 仕入先URL登録は存在するが、自動監視Workerはこの段階でも追加しない。

## 今回の追加

`change_safety.py` に、対象・承認前値・通貨・金額精度・数量・返却結果の検証を分離した。

1. 提案時に商品ID、下書きID、公開ID、Mock連携ID、外部ID、出品SKU、marketplace、mode、currency、revision、変更前全payloadを固定。
2. 商品マスターSKUは任意で出品SKUと別設定可能な既存仕様を維持し、別の固定値として後日の変更を検出する。
3. 同一対象・同一版・同一操作・同一payloadの提案は、別冪等キーでも既存要求を返す。取消・却下後は再提案可能。
4. 人間の承認で固定payloadとOutboxを同一DBトランザクションに保存。
5. 実行を1件だけ獲得してトランザクションを閉じ、ローカル紐付けとMock出品先の現在値を再照合する。
6. Mock Providerの書き込みトランザクション内でも同じ現在値・版を再確認し、事前確認との間の競合を拒否。
7. 返却ID、変更後全payload、status、versionを承認内容から算出した期待値と比較し、出品先を再取得して照合する。
8. 正常時だけMock連携データ、承認結果、Outbox、試行履歴、監査ログを同一トランザクションで確定。

数量0はACTIVEを維持し、END_LISTINGだけがENDEDに遷移する。
終了は承認画面と実行画面の両方で明示確認する既存UIを維持。
価格は対応通貨の桁数に合わなければ丸めず拒否。数量は0以上の整数で、NULL・bool・小数を拒否。
数量上限2147483647はアプリの安全上限であり、eBay全サービスの公式上限を意味しない。

## 状態・障害復旧

DBスキーマ、Migrationは変更しない。既存status列の制約を維持し、execution_statusで詳細を表す。

| 状態 | 保存・対応 |
|---|---|
| 未承認 | 実行拒否、Provider書き込みなし |
| 事前照合不一致 | FAILED / STALE、未送信と表示、取消・再提案 |
| 事前読取失敗 | FAILED / READ_FAILED、書き込み未送信。手動再試行時に再照合 |
| 明確な認証切れ・rate limit拒否 | FAILED、エラー分類だけ保存。自動リトライなし |
| timeout・返却結果不一致・部分反映・結果保存失敗 | status=FAILED、execution_status=UNKNOWN、reconcile_required=1。再実行・取消を拒否 |
| 照合成功 | 保存済み冪等receiptと現在値を比較し、SUCCEEDED / RECONCILED。送信せずDB反映を再試行 |
| receiptなし・現在値がさらに変更された | 未確定のまま停止。値の一致だけで「自分の成功」と決めつけない |

再起動後も同じDBのreceiptと試行履歴を利用する。生の例外文字列・Tokenは保存せず固定文言を使用する。
`ebay.execution.reconciled` を既存の成功・失敗・開始・承認等の監査ログに追加する。
SQLスキーマを変更しないため、UNKNOWN/RECONCILEDはトップレベルstatusではない。

旧版の未実行変更提案に固定targetがない場合、推測で補完せず取り消し・再提案を要求する。
既存の完了履歴や新規Mock公開フローは維持する。

## eBay公式仕様と今後のAdapter

2026-09-17確認。現状はどちらのAPI方式も実装していないため、出品の作成元とアカウントを確認して選択する。

| 対象 | 候補API | 識別・注意点 |
|---|---|---|
| Inventory管理の価格/数量 | POST `/sell/inventory/v1/bulk_update_price_quantity` | SKU、offerId、currency。SKU全体在庫とMarketplace別offer数量の両方を確認し、他市場への影響を明示 |
| Inventory単一SKUの終了 | POST `/sell/inventory/v1/offer/{offerId}/withdraw` | offerId。削除APIで代用しない。複数バリエーションのgroup終了は初期対応対象外 |
| Trading管理の固定価格変更 | `ReviseInventoryStatus` | ItemID/SKUとInventoryTrackingMethodを照合。Inventory管理出品には使用しない |
| Trading管理の固定価格終了 | `EndFixedPriceItem` | ItemIDとEndingReason。SKUもローカルで照合し、API側の無視動作に依存しない |

Inventoryの部分成功はSKU/offerごとのstatusCodeで判断する。今回は単一Mock操作を対象とし、複数実商品への一括送信は実装しない。
Tradingの数量0はOutOfStockControl等の条件確認が必要で、アカウント全体の設定を勝手に変更しない。
`updateOffer`の全体置換や、全市場の在庫を不用意に0へ変更する実装は採用しない。
実APIの冪等性・CASをMockのreceipt/DBロックと同等とみなさない。取得と更新間の外部競合は別途対策が必要。

一次資料:
- [Inventory価格・数量更新](https://developer.ebay.com/api-docs/sell/static/inventory/bulk-updates.html)
- [Offer管理](https://developer.ebay.com/api-docs/sell/static/inventory/managing-offers.html)
- [ReviseInventoryStatus](https://developer.ebay.com/Devzone/XML/docs/Reference/eBay/ReviseInventoryStatus.html)
- [EndFixedPriceItem](https://developer.ebay.com/devzone/xml/docs/reference/ebay/EndFixedPriceItem.html)
- [Out-of-stock設定](https://developer.ebay.com/api-docs/user-guides/static/trading-user-guide/out-of-stock-enable.html)
- [認証ガイド](https://developer.ebay.com/develop/guides/sell/authorization)

## 本番接続前の残作業

1. 認証済み操作者・権限・二者確認等の本番実行許可、機能ゲート、対象許可リストの設計。
2. 販売者account/environment/API方式/marketplace/Item ID/Offer ID/SKU/variationの検証済み紐付け。必要なら追加型Migrationを別途承認。
3. Sandbox用OAuth・読取Adapter・scope・期限・rate limit・再照合手順の検証。秘密情報は本文・ログに出さない。
4. 実APIの数量0条件、終了理由、部分成功、外部競合、手動復旧画面を検証。
5. Sandbox書き込み試験を先行し、本番はまず許可された読取確認。その後も商品変更は個別承認。

現時点で本番eBay接続テストへ進めるか: **NO**。Mock安全性の確認は実API接続・認可・実商品識別の代替ではない。

## 検証・保全方針

- SQLite、ローカルlibSQL、偽Turso設定+ローカルlibSQLで同一の安全性テストを実行。
- テストの既存94件fixtureを全列比較し、通常listingsを増やさず、送料JSONとNULL product_idも維持。
- 実本番DBは今回接続・再計算・Migrationせず、前回保全確認結果を引き継ぐ。本番を今再照合したとは扱わない。
- FedEx差分、料金JSON、利益計算アプリ、Secrets等の保護対象9ファイルを保存済みハッシュと比較。
- ブラウザ検証は毎回新しい一時DBの `approval_preview.py` だけを使用し、外部HTTPを遮断。
- 回帰テストはSecrets読取を無効化する既存runnerを使用する。
- コード切戻しは今回コミットのrevert。スキーマ/既存行の巻戻しは不要だが、実行中要求がある状態で切り戻さない。

## 最終ローカル検証結果

2026-09-17:

- 第7段階追加: 66/66成功（22ケースをSQLite、libSQL、偽Turso設定の3構成で確認）。
- 作業ツリー全回帰: 374/374成功、失敗0、エラー0、スキップ0。
- FedEx未コミット差分を除く候補: 全359件成功後、最終の例外秘匿化について既存承認86件と追加66件を追試。
- Chrome / WebKit × 1440 / 390 / 414 / 360px: 8構成とも横はみ出し・例外なし。
- タイトル上端は約104〜105px、固定ヘッダー下端は60px。スマホ操作ボタンは46px。
- 保護対象9ファイルは保存済みSHA-256と一致。通常94件fixtureは全列不変。
- 本番画面の読取で登録件数94件を確認。今回は本番DB全行ハッシュの再取得や書き込みは行っていない。

検証ログと画像、一時DB、候補ビルドはGit対象外の `.tmp_stage6` / `.tmp_stage7` に保存する。
本番eBayの実通信精度や実APIにおける原子的更新を証明した結果ではない。

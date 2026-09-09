# 第3段階 商品マスター・在庫管理

## 範囲

第2段階で追加した `product_id` を親キーとして、商品基本情報、複数仕入先、
在庫、画像メタデータ、既存 `listings` との関連を管理する。AI出品、eBay API、
仕入先監視、Outbox Workerはこの段階に含めない。

## Migration

`0002_product_catalog_inventory` は追加専用で、既存テーブルや行を削除・更新しない。
既存 `products` に商品属性を追加し、`product_sources`、`inventory`、
`product_images` を新設する。既存 `listings.product_id` のNULL値は変更しない。

## データモデル

- `products`: 商品名、販路、SKU、JAN/EAN/UPC、ブランド、型番、カテゴリ、メモ、
  原産国、HS/HTS、重量・3辺、仕入価格・通貨、ACTIVE/INACTIVE/ARCHIVED。
- `product_sources`: 1商品に複数の仕入先。部分一意indexにより主仕入先は最大1件。
- `inventory`: 1商品1行。有在庫と無在庫を `IN_STOCK` / `DROPSHIP` で区別。
- `product_images`: URLまたは外部ストレージキーだけを保持し、画像BLOBを保存しない。
- `listings.product_id`: 新規listingを商品マスターへ関連付けるnullableな既存ブリッジ。

`available_quantity` は重複保存せず、`IN_STOCK` の場合だけ
`max(0, on_hand_quantity - reserved_quantity)` としてサービス層で算出する。
`DROPSHIP` は将来の仕入先在庫判定が必要なため `None`（未確定）とする。

## アプリ連携

出品管理アプリの「商品マスター」タブで一覧、作成、編集、論理アーカイブ、
仕入先、在庫、画像メタデータ、関連出品を管理する。商品詳細の「この商品で利益計算」
は `product_id` をクエリへ渡し、利益計算側が商品名、SKU、仕入価格、重量、寸法、
原産国、HS/HTS、主仕入先URL、メモを既存入力へプリフィルする。

`ListingRegistrationService.register(..., product_id=...)` に既存IDを渡すと、
新しいproducts行を作らず、その商品へlistingを関連付ける。IDを省略した既存の登録経路は、
従来どおり新しい商品を作成して紐付ける。

## 整合性と監査

子テーブルはproductsへの外部キーと `ON DELETE RESTRICT` を持つ。商品削除は行わず、
ARCHIVEDへの論理変更を使う。商品、仕入先、在庫の重要操作は `audit_logs` に記録し、
外部処理がないためOutboxイベントは作成しない。

## 構成設定

利益計算URLは `PROFIT_CALCULATOR_URL` 環境変数、またはStreamlit Secretsの
`[app_urls].profit_calculator` で上書きできる。未設定時は既存の本番利益計算URLを使う。
Secretsそのものは第3段階では変更しない。

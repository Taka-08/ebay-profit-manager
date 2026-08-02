# EBリサーチプラス利益計算ツール 復元版

復元日: 2026-07-17

このフォルダは、利益・送料計算ツール、出品管理ツール、分析・集計機能、
配送料金データ、Zonos設定、既存SQLiteデータをまとめた最新版です。

## 起動方法

1. Python 3.11以降をインストールします。
2. このフォルダで次を実行します。

```powershell
py -m pip install -r requirements.txt
```

3. `run_all_tools.bat` をダブルクリックします。

- 利益・送料計算ツール: http://localhost:8501
- 出品管理ツール: http://localhost:8502

個別に起動する場合:

- `run_profit_calculator.bat`
- `run_listing_manager.bat`

旧ショートカット用の
`ebay_profit_calculator_streamlit\run_streamlit.bat` も最新版を起動します。

## スマートフォンからの利用

PCとスマートフォンを同じWi-Fiへ接続し、PCで `run_all_tools.bat` を起動します。
PCのIPv4アドレスは、PowerShellで次のコマンドを実行して確認できます。

```powershell
ipconfig
```

たとえばPCのIPv4アドレスが `192.168.10.114` の場合:

- 利益・送料計算ツール: `http://192.168.10.114:8501`
- 出品管理ツール: `http://192.168.10.114:8502`

Windows Defender ファイアウォールの確認画面が出た場合は、信頼できる
プライベートネットワークでPythonの通信を許可してください。ルーターから
割り当てられるIPv4アドレスは変わることがあるため、接続できないときは
`ipconfig` で再確認してください。

画面幅768px以下では、入力欄を1列へ切り替え、操作ボタンを押しやすい幅にし、
出品一覧を横長の表から商品カードへ切り替えます。PC表示では従来の表形式を維持します。

PCとスマートフォンは同じ
`ebay_listing_manager\ebay_listings.sqlite3` を参照します。SQLiteはWALモードと
待機時間を設定しているため、両方から登録・編集した内容が同じ一覧へ反映されます。

## 外出先からの利用

利益計算ツールと出品管理ツールは、ログイン画面を使用せずに直接開きます。
Streamlit Community Cloudで公開した場合、公開URLを知る人は画面とデータを利用できます。
閲覧者を限定したい場合は、Community Cloud側のShare settingsを使用してください。

Streamlit Community Cloudではローカルファイルの永続性が保証されないため、公開版は
SQLite互換のTurso Cloudへ接続します。ローカルSQLiteはそのまま残り、自動削除・自動上書き
されません。GitHub、Turso、Community Cloudの設定と既存データの移行方法は
[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) を参照してください。

## 主な機能

- USD/JPYを起動時と更新ボタンで自動取得
- Yahoo Finance市場データを主取得先として使用
- `open.er-api.com`への自動フォールバック
- 保存済みレートと手動入力へのフォールバック
- API更新日時、取得日時、取得元、手動設定状態を表示
- 日本郵便、SpeedPAK / CPaSS、FedEx、DHLの送料・利益比較
- 実重量のみの概算と、梱包サイズ入力後の容積重量計算
- 米国向け日本郵便のZonos Prepay手数料・関税計算
- おすすめ配送方法、最安送料、配送方法の手動選択
- 選択した配送方法と送料内訳を出品管理へ登録
- 出品中、売却済み、キャンセル済みの管理
- 実績手数料、実送料、実利益、発送業者、発送重量の管理
- 月別集計、配送会社別分析、予定と実績の差額分析
- CSV出力

## 重要なデータ

- 出品管理DB: `ebay_listing_manager\ebay_listings.sqlite3`
- 登録更新通知: `ebay_listing_manager\registration_event.json`
- 登録ログ: `ebay_listing_manager\logs\registration.log`
- 共通為替レート: `ebay_listing_manager\exchange_rate.json`
- 配送料金データ: `shipping_rates.json`
- Zonos設定: `zonos_prepay_config.json`
- 配送料金生成処理: `shipping_rate_data\build_shipping_rates_from_pdfs.py`

既存SQLiteデータは復元作業で初期化していません。

利益計算ツールは登録後にSQLiteを別接続で再読込し、保存IDと総件数を確認します。
同じ `eBay` ワークスペース内にZIP展開版があっても、各ツールは上記の正規DBを
共通利用します。出品管理画面は登録更新通知を監視し、新規登録を自動反映します。

## 初期値

- eBay手数料率: 15.00%
- 広告率: 2.10%
- 固定手数料: 0.30 USD
- コピー代: 20円
- 購入者から受け取る送料: 新規計算では0 USD固定

## 為替レートの保護

取得値が0以下、数値以外、USD/JPY以外、前回値から5%超の変動、
またはAPI更新から96時間超の場合は自動適用しません。
API取得に失敗した場合も、保存済みレートまたは手動入力値を維持します。

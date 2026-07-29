# 外出先から安全に利用するための公開手順

このプロジェクトは、同じコードを次の2通りで動かせます。

- ローカル: 既存の `ebay_listing_manager/ebay_listings.sqlite3` をそのまま使用
- Streamlit Community Cloud: Turso Cloudの共有データベースを使用

Community Cloudではローカルファイルの永続性が保証されません。そのため、公開版で
SQLiteファイルへ直接保存する構成にはせず、SQLite互換のTursoへ保存します。利益計算と
出品管理の2アプリへ同じTurso設定を入れることで、PCとスマートフォンが同じデータを
参照します。

## 0. 公開前のバックアップ

PowerShellをこのプロジェクトで開き、既存DBをコピーします。

```powershell
$stamp = Get-Date -Format yyyyMMdd_HHmmss
Copy-Item -LiteralPath .\ebay_listing_manager\ebay_listings.sqlite3 `
  -Destination ".\ebay_listing_manager\ebay_listings_backup_$stamp.sqlite3"
```

バックアップも `.gitignore` の対象なので、GitHubへは送信されません。

## 1. ログインパスワードを作る

Community Cloudとデータ移行ではPython 3.12を使用します。Python 3.12をインストール
した後、次を実行します。

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 scripts\generate_password_hash.py
```

12文字以上のパスワードを2回入力すると、次の形式の1行が表示されます。

```toml
APP_PASSWORD_HASH = "pbkdf2_sha256$600000$..."
```

この行とユーザー名は、後でCommunity CloudのSecretsへ設定します。パスワードそのものや
ハッシュをGitHubのファイルへ書かないでください。

## 2. 永続データベースを用意する

1. [Turso](https://turso.tech/)でアカウントを作成します。
2. Tursoのダッシュボードで新しいデータベースを1つ作成します。
3. Database URL（`libsql://...turso.io`）を控えます。
4. そのデータベースへ読み書きできるDatabase Tokenを作成して控えます。

Tursoの料金・無料枠は変更されることがあるため、作成時に公式料金ページを確認して
ください。有料プランを選ぶ必要はありません。

## 3. 既存データをTursoへ移す

`.streamlit/secrets.toml` を新規作成します。この実ファイルはGitから除外されています。

```toml
[auth]
REQUIRE_AUTH = true
APP_USERNAME = "任意のユーザー名"
APP_PASSWORD_HASH = "手順1で生成した値"

[database]
TURSO_DATABASE_URL = "libsql://取得したURL"
TURSO_AUTH_TOKEN = "取得したToken"
```

最初の1回だけ、次を実行します。

```powershell
py -3.12 scripts\migrate_sqlite_to_turso.py
```

スクリプトは元のSQLiteを読み取り専用で開きます。Turso側に既存データがある場合は安全の
ため停止します。Turso側を置き換える `--replace-remote` は、Turso側のバックアップと
内容確認を済ませた場合だけ使用してください。

## 4. GitHubへアップロードする

GitHubで**Private repository**を作成します。GitHub上でREADMEや`.gitignore`を先に
生成せず、空のリポジトリとして作ると分かりやすくなります。

このプロジェクトで次を実行します。

```powershell
git init
git add .
py -3.12 scripts\check_github_safety.py
git status --short
git commit -m "Prepare secure Streamlit Cloud deployment"
git branch -M main
git remote add origin https://github.com/あなたのユーザー名/リポジトリ名.git
git push -u origin main
```

`git status` やGitHubのファイル一覧に、次がないことを必ず確認します。

- `.streamlit/secrets.toml`
- `*.sqlite3`、`*.sqlite`、`*.db`
- `.env`
- APIキー、Webhook URL、パスワード、Turso Token
- バックアップZIP、登録ログ

サンプルの `.streamlit/secrets.toml.example` は公開して構いません。実際の値は含まれて
いません。

## 5. 利益計算ツールをCommunity Cloudへ配置する

1. [Streamlit Community Cloud](https://share.streamlit.io/)へGitHubでログインします。
2. `Create app` を選び、手順4のPrivate repositoryを接続します。
3. Branchは `main`、Main file pathは `streamlit_app.py` を指定します。
4. Advanced settingsでPython `3.12` を選びます。
5. Secretsへ、手順3の `secrets.toml` と同じ内容を貼り付けます。
6. Deployを押します。

成功すると `https://任意の名前.streamlit.app` のURLが発行されます。

## 6. 出品管理ツールをCommunity Cloudへ配置する

同じリポジトリからもう1つアプリを作ります。

1. Branchは `main` を指定します。
2. Main file pathは `ebay_listing_manager/streamlit_app.py` を指定します。
3. Pythonは `3.12` を選びます。
4. **利益計算ツールと完全に同じSecrets**を貼り付けます。
5. Deployを押します。

2つのアプリが同じTurso URLとTokenを使用するため、利益計算から登録した内容は出品管理へ
反映され、PCとスマートフォンで共通利用できます。

## 7. 公開後の安全設定

- Community CloudのShare settingsでも、可能なら閲覧者を限定します。
- アプリ内ログインも有効なままにし、二重に保護します。
- Secretsを変更した場合は2つのアプリ両方へ同じ変更を反映します。
- Turso Tokenが漏れた可能性がある場合は、Turso側でTokenを失効し再発行します。
- GitHubへ実データやSecretsを誤ってcommitした場合は、履歴から消すだけでなくTokenと
  パスワードも必ず変更します。

## 8. 動作確認

1. Wi-FiのPCでCloud URLを開き、未ログインではデータが見えないことを確認します。
2. ログインして利益計算からテスト商品を1件登録します。
3. 出品管理のCloud URLへログインし、同じ商品が表示されることを確認します。
4. スマートフォンのWi-Fiを切り、4G・5Gで両URLを開きます。
5. PCとスマートフォンで同じ登録件数・商品内容になることを確認します。
6. テスト商品を編集し、別端末側にも反映されることを確認します。

ローカルの `run_all_tools.bat` は引き続き使用できます。ローカルに
`.streamlit/secrets.toml` がなければ従来のSQLiteを使い、設定があればローカル起動でも
Tursoを使います。既存SQLiteは自動削除・自動上書きされません。

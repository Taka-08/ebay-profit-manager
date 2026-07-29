# Turso / Streamlit Community Cloud setup

## Completed locally

- The original SQLite database was backed up before migration.
- The `listings` table was migrated to Turso.
- Local and remote row counts, column definitions, IDs, and all row values were
  compared.
- The Streamlit database adapter can read the Turso database.
- Turso write access was tested inside a transaction and rolled back.
- Cloud authentication uses a PBKDF2 password hash.
- Real database credentials, login credentials, SQLite files, logs, and backups
  are excluded by `.gitignore`.

## Private files generated on this PC

These files are intentionally ignored by Git:

- `.streamlit/community_cloud_secrets.toml`
- `.streamlit/community_cloud_login_credentials.txt`

The first file is pasted into Streamlit Community Cloud Secrets. The second
file contains the application login username and generated password.

## Security action before deployment

The current Turso token was used for the migration. Because it was shared in a
chat, revoke it in Turso and issue a new read/write token before deploying.
Do not paste the replacement token into chat or commit it to Git.

After rotating the token, update only the Turso credentials in the ignored
Secrets file. The helper preserves the existing application login settings:

```powershell
$env:TURSO_DATABASE_URL = "libsql://YOUR_DATABASE.turso.io"
$env:TURSO_AUTH_TOKEN = Read-Host "New Turso token"
python scripts\update_cloud_turso_credentials.py
Remove-Item Env:TURSO_DATABASE_URL, Env:TURSO_AUTH_TOKEN
```

Use the same updated Secrets content for both Streamlit apps.

## GitHub

1. Create an empty private GitHub repository.
2. In this project directory, run:

```powershell
git add .
python scripts\check_github_safety.py
git status --short
git commit -m "Prepare Turso and Streamlit Cloud deployment"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/YOUR_REPOSITORY.git
git push -u origin main
```

Before committing, verify that the two private files above and every
`*.sqlite3`, `*.sqlite`, and `*.db` file are absent from `git status`.

## Streamlit Community Cloud

Create two apps from the same private repository and branch.

### Profit calculator

- Main file: `streamlit_app.py`
- Python: `3.12`
- Secrets: paste the full contents of
  `.streamlit/community_cloud_secrets.toml`

### Listing manager

- Main file: `ebay_listing_manager/streamlit_app.py`
- Python: `3.12`
- Secrets: paste the same Secrets content

Both apps use the same Turso database, so registrations and edits are shared
between PC and smartphone sessions.

## Verification after deployment

1. Open both Cloud URLs while logged out and confirm no transaction data is
   visible.
2. Sign in using the ignored local login credentials file.
3. Register one test item from the profit calculator.
4. Confirm it appears in the listing manager without using the local SQLite
   file.
5. Edit the item in the listing manager and confirm the updated value is
   visible from another browser.
6. Turn off Wi-Fi on the phone and verify both Cloud URLs over 4G/5G.

"""Generate a PBKDF2 password hash for Streamlit Secrets."""

from __future__ import annotations

import base64
import getpass
import hashlib
import os


ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000


def main() -> None:
    password = getpass.getpass("新しいログインパスワード: ")
    confirmation = getpass.getpass("確認のため再入力: ")
    if not password:
        raise SystemExit("空のパスワードは使用できません。")
    if password != confirmation:
        raise SystemExit("入力したパスワードが一致しません。")
    if len(password) < 12:
        raise SystemExit("12文字以上のパスワードを使用してください。")

    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        ITERATIONS,
    )
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii")
    print("\nStreamlit Secretsへ次の1行を設定してください。")
    print(
        f'APP_PASSWORD_HASH = "{ALGORITHM}${ITERATIONS}'
        f'${encoded_salt}${encoded_digest}"'
    )


if __name__ == "__main__":
    main()

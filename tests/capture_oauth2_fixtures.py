import argparse
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


def main() -> None:
    if ROOT_DIR not in sys.path:
        sys.path.insert(0, ROOT_DIR)

    from birdapp.oauth2 import (
        DEFAULT_OAUTH2_SCOPES,
        build_authorize_url,
        create_pkce_pair,
        exchange_code_for_token,
        get_user_me,
        wait_for_oauth_callback,
        write_oauth2_fixtures,
    )
    from birdapp.session import save_token

    parser = argparse.ArgumentParser(description="Capture OAuth2 fixtures for tests")
    parser.add_argument("--json", action="store_true", help="Print /2/users/me payload")
    parser.add_argument("--timeout", type=int, default=180, help="Callback timeout in seconds")
    args = parser.parse_args()

    _load_dotenv(os.path.join(ROOT_DIR, ".env"))

    client_id = os.getenv("X_OAUTH2_CLIENT_ID")
    redirect_uri = os.getenv("X_OAUTH2_REDIRECT_URI")
    scopes = os.getenv("X_OAUTH2_SCOPES", DEFAULT_OAUTH2_SCOPES).split()
    client_secret = os.getenv("X_OAUTH2_CLIENT_SECRET")

    if not client_id or not redirect_uri:
        raise RuntimeError("Missing X_OAUTH2_CLIENT_ID or X_OAUTH2_REDIRECT_URI in environment")

    state = os.urandom(16).hex()
    code_verifier, code_challenge = create_pkce_pair()
    authorize_url = build_authorize_url(
        state=state,
        code_challenge=code_challenge,
        scopes=scopes,
        redirect_uri=redirect_uri,
        client_id=client_id,
    )

    print("Open this URL in your browser and authorize the app:")
    print(authorize_url)
    print(f"Waiting for callback on {redirect_uri} ...")

    params = wait_for_oauth_callback(redirect_uri=redirect_uri, timeout_seconds=args.timeout)
    returned_state = params.get("state", [None])[0]
    code = params.get("code", [None])[0]
    if not code or returned_state != state:
        raise RuntimeError("Invalid OAuth2 callback (missing code or state mismatch)")

    token = exchange_code_for_token(
        code=code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        client_id=client_id,
        client_secret=client_secret,
    )
    user_payload = get_user_me(token["access_token"])
    user_id: str | None = None
    if isinstance(user_payload.get("data"), dict):
        user_id = user_payload["data"].get("id")
    if not user_id:
        raise RuntimeError("OAuth2 /2/users/me response missing user id")

    save_token(user_id=user_id, token=token)
    write_oauth2_fixtures(token=token, user_payload=user_payload)

    if args.json:
        import json
        print(json.dumps(user_payload, indent=2))

if __name__ == "__main__":
    main()

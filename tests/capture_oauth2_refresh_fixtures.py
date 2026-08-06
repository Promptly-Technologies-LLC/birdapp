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


def _normalize_profile(profile: str) -> str:
    return profile.strip().lstrip("@")


def main() -> None:
    if ROOT_DIR not in sys.path:
        sys.path.insert(0, ROOT_DIR)

    from birdapp import oauth2, session
    from birdapp.config import get_active_profile, get_credential

    parser = argparse.ArgumentParser(
        description="Refresh OAuth2 token and capture updated fixtures"
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Profile name to refresh (default: active profile)",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=str,
        default=os.path.join(ROOT_DIR, "tests", "fixtures"),
        help="Directory to write fixtures into",
    )
    args = parser.parse_args()

    _load_dotenv(os.path.join(ROOT_DIR, ".env"))

    profile = _normalize_profile(args.profile) if args.profile else (get_active_profile() or "")
    if not profile:
        raise RuntimeError(
            "No profile specified and no active profile set. "
            "Run `birdapp profile use <username>` or pass --profile."
        )

    loaded = session.load_any_oauth2_token(profile)
    if not loaded:
        raise RuntimeError(
            f"No OAuth2 token stored for profile {profile!r}. "
            f"Run `birdapp --profile {profile} auth login` first."
        )

    user_id, token = loaded
    refresh_token = token.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise RuntimeError(
            "Stored token is missing refresh_token. Ensure your OAuth2 scopes include "
            f"`offline.access` (default: {oauth2.DEFAULT_OAUTH2_SCOPES!r}), then re-login."
        )

    client_id = os.getenv("X_OAUTH2_CLIENT_ID") or get_credential(
        "X_OAUTH2_CLIENT_ID", profile=profile
    )
    client_secret = os.getenv("X_OAUTH2_CLIENT_SECRET") or get_credential(
        "X_OAUTH2_CLIENT_SECRET", profile=profile
    )
    if not isinstance(client_id, str) or not client_id.strip():
        raise RuntimeError(
            "Missing X_OAUTH2_CLIENT_ID. Run `birdapp auth config --oauth2` "
            "or set it in your environment."
        )

    refreshed = oauth2.refresh_access_token(
        refresh_token=refresh_token.strip(),
        client_id=client_id.strip(),
        client_secret=client_secret.strip()
        if isinstance(client_secret, str) and client_secret.strip()
        else None,
    )

    merged = dict(token)
    merged.update(refreshed)
    if "refresh_token" not in merged:
        merged["refresh_token"] = refresh_token

    session.save_token(user_id=user_id, token=merged, profile=profile)

    access_token = merged.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise RuntimeError("Refreshed token response missing access_token")

    user_payload = oauth2.get_user_me(access_token=access_token.strip())
    oauth2.write_oauth2_fixtures(
        token=merged, user_payload=user_payload, fixtures_dir=args.fixtures_dir
    )

    print("Wrote OAuth2 fixtures:")
    print(f"  {os.path.join(args.fixtures_dir, 'oauth2_token.json')}")
    print(f"  {os.path.join(args.fixtures_dir, 'oauth2_user.json')}")


if __name__ == "__main__":
    main()


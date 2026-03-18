import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import platformdirs
from requests_oauthlib import OAuth2Session
from .auth import create_oauth2_session
from .config import get_active_profile

def get_sessions_dir() -> str:
    """Get or create the sessions directory."""
    override = os.getenv("BIRDAPP_SESSIONS_DIR")
    if override and override.strip():
        sessions_dir = override.strip()
    else:
        sessions_dir = os.path.join(platformdirs.user_state_dir("birdapp"), "sessions")

    Path(sessions_dir).mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(sessions_dir, 0o700)
    except OSError:
        pass

    _migrate_legacy_tokens(sessions_dir)
    return sessions_dir


def _migrate_legacy_tokens(sessions_dir: str) -> None:
    """
    Migrate tokens from older locations into the current sessions directory.

    Historically, tokens were stored relative to the import location of the
    `birdapp` package, which caused tokens to "disappear" depending on how the
    CLI was installed or where it was executed from.
    """
    tokens_path = os.path.join(sessions_dir, "tokens.json")
    if os.path.exists(tokens_path):
        return

    legacy_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sessions")
    legacy_tokens_path = os.path.join(legacy_dir, "tokens.json")
    if not os.path.exists(legacy_tokens_path):
        return

    Path(sessions_dir).mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(legacy_tokens_path, tokens_path)
        os.chmod(tokens_path, 0o600)
    except OSError:
        return

def _resolve_profile(profile: str | None, tokens: Dict[str, Any]) -> Optional[str]:
    if profile:
        return profile
    active = get_active_profile()
    if active:
        return active
    profiles = tokens.get("profiles")
    if isinstance(profiles, dict) and len(profiles) == 1:
        return next(iter(profiles.keys()))
    return None

def _load_tokens(tokens_path: str) -> Dict[str, Any]:
    if not os.path.exists(tokens_path):
        return {}
    try:
        with open(tokens_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_token(user_id: str, token: Mapping[str, Any], profile: str | None = None) -> None:
    """Save a user's token to the tokens file."""
    sessions_dir = get_sessions_dir()
    tokens_path = os.path.join(sessions_dir, "tokens.json")
    
    tokens = _load_tokens(tokens_path)
    profile_name = _resolve_profile(profile, tokens)
    if profile_name:
        profiles = tokens.get("profiles")
        if not isinstance(profiles, dict):
            profiles = {}
            tokens = {"profiles": profiles}
        profile_tokens = profiles.get(profile_name)
        if not isinstance(profile_tokens, dict):
            profile_tokens = {}
            profiles[profile_name] = profile_tokens
        profile_tokens[user_id] = dict(token)
    else:
        tokens[user_id] = dict(token)
    
    # Save updated tokens
    with open(tokens_path, "w") as f:
        json.dump(tokens, f)
    try:
        os.chmod(tokens_path, 0o600)
    except OSError:
        pass

def load_token(user_id: str, profile: str | None = None) -> Optional[Dict[str, Any]]:
    """Load a user's token from the tokens file."""
    sessions_dir = get_sessions_dir()
    tokens_path = os.path.join(sessions_dir, "tokens.json")
    
    tokens = _load_tokens(tokens_path)
    profiles = tokens.get("profiles")
    if isinstance(profiles, dict):
        profile_name = _resolve_profile(profile, tokens)
        if not profile_name:
            return None
        profile_tokens = profiles.get(profile_name)
        if isinstance(profile_tokens, dict):
            return profile_tokens.get(user_id)
        return None
    return tokens.get(user_id)

def create_session_from_token(token: Dict[str, Any]) -> OAuth2Session:
    """Create a new OAuth2Session from a token."""
    return create_oauth2_session(token)

def get_user_session(user_id: str, profile: str | None = None) -> tuple[Optional[OAuth2Session], Optional[Dict[str, Any]]]:
    """Get a user's session and token."""
    token = load_token(user_id, profile=profile)
    if token:
        # Add user ID to token for updater closure
        token['user_id'] = user_id
        session = create_session_from_token(token)
        return session, token
    return None, None 


def clear_oauth2_tokens(profile: str | None = None) -> None:
    """Remove all stored OAuth2 tokens for the given profile."""
    sessions_dir = get_sessions_dir()
    tokens_path = os.path.join(sessions_dir, "tokens.json")
    tokens = _load_tokens(tokens_path)
    if not tokens:
        return

    profiles = tokens.get("profiles")
    if isinstance(profiles, dict):
        profile_name = _resolve_profile(profile, tokens)
        if profile_name and profile_name in profiles:
            del profiles[profile_name]
    else:
        # Legacy format: clear all tokens
        tokens.clear()

    with open(tokens_path, "w") as f:
        json.dump(tokens, f)
    try:
        os.chmod(tokens_path, 0o600)
    except OSError:
        pass


def has_oauth2_token(profile: str | None = None) -> bool:
    """
    Return True if any OAuth2 token (with an access_token) exists for the given
    profile (or the active profile when omitted).
    """
    sessions_dir = get_sessions_dir()
    tokens_path = os.path.join(sessions_dir, "tokens.json")
    tokens = _load_tokens(tokens_path)
    profiles = tokens.get("profiles")
    if not isinstance(profiles, dict):
        # Legacy format: { "<user_id>": { "access_token": "...", ... }, ... }
        # Without profile scoping, only treat it as usable when exactly one
        # token entry exists with a non-empty access_token. This avoids
        # accidentally mixing tokens across multiple profiles.
        usable = 0
        for token in tokens.values():
            if isinstance(token, dict) and isinstance(token.get("access_token"), str) and token["access_token"].strip():
                usable += 1
        return usable == 1

    profile_name = _resolve_profile(profile, tokens)
    if not profile_name:
        return False

    profile_tokens = profiles.get(profile_name)
    if not isinstance(profile_tokens, dict):
        return False

    for token in profile_tokens.values():
        if isinstance(token, dict) and isinstance(token.get("access_token"), str) and token["access_token"].strip():
            return True
    return False


def load_any_oauth2_token(profile: str) -> tuple[str, Dict[str, Any]] | None:
    """
    Load any stored OAuth2 token for a specific profile.

    Returns (user_id, token) when present, otherwise None.
    """
    sessions_dir = get_sessions_dir()
    tokens_path = os.path.join(sessions_dir, "tokens.json")
    tokens = _load_tokens(tokens_path)
    profiles = tokens.get("profiles")
    if not isinstance(profiles, dict):
        # Legacy format: tokens are not profile-scoped. Only treat it as
        # loadable when there is exactly one usable token.
        usable: list[tuple[str, Dict[str, Any]]] = []
        for user_id, token in tokens.items():
            if (
                isinstance(user_id, str)
                and isinstance(token, dict)
                and isinstance(token.get("access_token"), str)
                and token["access_token"].strip()
            ):
                usable.append((user_id, token))
        if len(usable) == 1:
            return usable[0]
        return None

    profile_tokens = profiles.get(profile)
    if not isinstance(profile_tokens, dict) or not profile_tokens:
        return None

    user_id = next(iter(profile_tokens.keys()))
    token = profile_tokens.get(user_id)
    if not isinstance(user_id, str) or not isinstance(token, dict):
        return None
    return user_id, token
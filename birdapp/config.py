import getpass
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

def get_config_path() -> Path:
    """Get the path to the user-level config file."""
    config_dir = Path.home() / ".config" / "birdapp"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"

def load_config() -> Dict[str, Any]:
    """Load configuration from the user-level config file."""
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to the user-level config file."""
    config_path = get_config_path()
    
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        # Set secure permissions (read/write for owner only)
        os.chmod(config_path, 0o600)
    except IOError as e:
        raise RuntimeError(f"Failed to save config: {e}")

_PROFILE_OVERRIDE: str | None = None
_OAUTH2_APP_KEYS = {
    "X_OAUTH2_CLIENT_ID",
    "X_OAUTH2_CLIENT_SECRET",
    "X_OAUTH2_REDIRECT_URI",
    "X_OAUTH2_SCOPES",
}

def _normalize_profile_name(profile: str) -> str:
    return profile.strip().lstrip("@")

def _get_profiles(config: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    profiles = config.get("profiles")
    if isinstance(profiles, dict):
        return profiles
    return {}

def _get_oauth2_app_config(config: Dict[str, Any]) -> Dict[str, str]:
    oauth2_app = config.get("oauth2_app")
    if isinstance(oauth2_app, dict):
        return oauth2_app
    return {}


def _get_embeddings_config(config: Dict[str, Any]) -> Dict[str, str]:
    embeddings = config.get("embeddings")
    if isinstance(embeddings, dict):
        return embeddings
    return {}

def _get_active_profile(config: Dict[str, Any]) -> Optional[str]:
    active = config.get("active_profile")
    if isinstance(active, str) and active.strip():
        return _normalize_profile_name(active)
    if "profiles" not in config:
        username = config.get("X_USERNAME")
        if isinstance(username, str) and username.strip():
            return _normalize_profile_name(username)
    return None

def _resolve_profile_name(config: Dict[str, Any], profile: str | None = None) -> Optional[str]:
    if profile:
        return _normalize_profile_name(profile)
    if _PROFILE_OVERRIDE:
        return _normalize_profile_name(_PROFILE_OVERRIDE)
    active = _get_active_profile(config)
    if active:
        return active
    profiles = _get_profiles(config)
    if len(profiles) == 1:
        return next(iter(profiles.keys()))
    return None

def set_profile_override(profile: str) -> None:
    global _PROFILE_OVERRIDE
    _PROFILE_OVERRIDE = _normalize_profile_name(profile)

def clear_profile_override() -> None:
    global _PROFILE_OVERRIDE
    _PROFILE_OVERRIDE = None

def get_active_profile() -> Optional[str]:
    config = load_config()
    return _get_active_profile(config)

def list_profiles() -> list[str]:
    config = load_config()
    profiles = _get_profiles(config)
    if profiles:
        return sorted(profiles.keys())
    username = config.get("X_USERNAME")
    if isinstance(username, str) and username.strip():
        return [_normalize_profile_name(username)]
    return []

def has_profile(profile: str) -> bool:
    normalized = _normalize_profile_name(profile)
    return normalized in list_profiles()

def set_active_profile(profile: str) -> None:
    config = load_config()
    profiles = _get_profiles(config)
    normalized = _normalize_profile_name(profile)
    if profiles and normalized not in profiles:
        raise ValueError(f"Profile '{normalized}' not found")
    config["active_profile"] = normalized
    if "profiles" not in config:
        config["profiles"] = profiles
    save_config(config)

def ensure_profile(username: str) -> None:
    config = load_config()
    profile_name = _normalize_profile_name(username)
    profile_data = _ensure_profiles_config(config, profile_name)
    if not profile_data.get("X_USERNAME"):
        profile_data["X_USERNAME"] = profile_name
    config["active_profile"] = profile_name
    save_config(config)

def get_credential(key: str, profile: str | None = None) -> Optional[str]:
    """Get a credential from the config file."""
    config = load_config()
    profiles = _get_profiles(config)
    oauth2_app = _get_oauth2_app_config(config)
    if profiles:
        profile_name = _resolve_profile_name(config, profile)
        if not profile_name:
            if key in _OAUTH2_APP_KEYS:
                return oauth2_app.get(key)
            return None
        if key == "X_OAUTH2_SCOPES":
            return oauth2_app.get(key)
        profile_value = profiles.get(profile_name, {}).get(key)
        if profile_value:
            return profile_value
        if key in _OAUTH2_APP_KEYS:
            return oauth2_app.get(key)
        return None
    if key in _OAUTH2_APP_KEYS:
        return oauth2_app.get(key) or config.get(key)
    return config.get(key)


def get_embedding_credential(key: str) -> Optional[str]:
    config = load_config()
    embeddings = _get_embeddings_config(config)
    if key in embeddings:
        return embeddings.get(key)
    return config.get(key)


def set_embedding_credentials(api_key: str, model: Optional[str]) -> None:
    config = load_config()
    embeddings = _get_embeddings_config(config)
    if not embeddings:
        embeddings = {}
    embeddings["OPENAI_API_KEY"] = api_key
    if model:
        embeddings["BIRDAPP_EMBEDDING_MODEL"] = model
    config["embeddings"] = embeddings
    save_config(config)


def show_embedding_config() -> None:
    config = load_config()
    embeddings = _get_embeddings_config(config)
    if not embeddings:
        print("No embedding configuration found.")
        return
    api_key = embeddings.get("OPENAI_API_KEY", "")
    redacted = "****" if api_key else "Not set"
    model = embeddings.get("BIRDAPP_EMBEDDING_MODEL") or "Not set"
    print("Embedding configuration:")
    print(f"  OPENAI_API_KEY: {redacted}")
    print(f"  BIRDAPP_EMBEDDING_MODEL: {model}")

def _ensure_profiles_config(config: Dict[str, Any], profile: str) -> Dict[str, str]:
    profiles = config.get("profiles")
    if not isinstance(profiles, dict):
        legacy = {key: value for key, value in config.items() if isinstance(value, str)}
        profiles = {}
        config.clear()
        config["profiles"] = profiles
        if legacy:
            profiles[profile] = legacy
    if "active_profile" not in config:
        config["active_profile"] = profile
    profile_data = profiles.get(profile)
    if not isinstance(profile_data, dict):
        profile_data = {}
        profiles[profile] = profile_data
    return profile_data

def prompt_for_credentials(profile: str | None = None) -> None:
    """Prompt user for Twitter API credentials and save them."""
    print("X CLI Configuration")
    print("==================")
    print("Please enter your X API credentials.")
    print("You can get these from https://developer.x.com/")
    print("(Sensitive fields will be hidden as you type)")
    print()
    
    config = load_config()
    profile_name = _resolve_profile_name(config, profile)
    if not profile_name:
        profile_name = _normalize_profile_name(input("Username (without @): ").strip())
    profile_data = _ensure_profiles_config(config, profile_name)
    
    # Prompt for each credential (hide sensitive fields)
    profile_data['X_API_KEY'] = getpass.getpass("Consumer Key: ").strip()
    profile_data['X_API_SECRET'] = getpass.getpass("Secret Key: ").strip()
    profile_data['X_ACCESS_TOKEN'] = getpass.getpass("Access Token: ").strip()
    profile_data['X_ACCESS_TOKEN_SECRET'] = getpass.getpass("Access Token Secret: ").strip()
    profile_data['X_USERNAME'] = profile_name
    
    # Validate that all fields are filled
    missing = [key for key, value in profile_data.items() if not value]
    if missing:
        print(f"\nError: Missing required fields: {', '.join(missing)}")
        return
    
    # Clear any stale OAuth2 tokens for this profile so the app doesn't
    # try to use them instead of the fresh OAuth1 credentials.
    from .session import clear_oauth2_tokens
    clear_oauth2_tokens(profile=profile_name)

    # Save the configuration
    try:
        config["active_profile"] = profile_name
        save_config(config)
        config_path = get_config_path()
        print(f"\n✅ Configuration saved to {config_path}")
        print("You can now use the CLI to post tweets!")
    except RuntimeError as e:
        print(f"\n❌ {e}")

def show_config(profile: str | None = None) -> None:
    """Show current configuration (without secrets)."""
    config = load_config()
    profiles = _get_profiles(config)
    if not config:
        print("No configuration found. Run `birdapp auth config` to set up credentials.")
        return
    if profiles:
        profile_name = _resolve_profile_name(config, profile)
        if not profile_name:
            print("No active profile set. Run `birdapp profile use <username>`.")
            return
        profile_data = profiles.get(profile_name, {})
    else:
        profile_data = config
        profile_name = config.get("X_USERNAME")
    if not profile_data:
        print("No configuration found. Run `birdapp auth config` to set up credentials.")
        return
    
    print("Current configuration:")
    if profile_name:
        print(f"  Profile: {profile_name}")
    print(f"  Username: {profile_data.get('X_USERNAME', 'Not set')}")
    print(f"  Consumer Key: {'*' * len(profile_data.get('X_API_KEY', '')) if profile_data.get('X_API_KEY') else 'Not set'}")
    print(f"  Secret Key: {'*' * len(profile_data.get('X_API_SECRET', '')) if profile_data.get('X_API_SECRET') else 'Not set'}")
    print(f"  Access Token: {'*' * len(profile_data.get('X_ACCESS_TOKEN', '')) if profile_data.get('X_ACCESS_TOKEN') else 'Not set'}")
    print(f"  Access Token Secret: {'*' * len(profile_data.get('X_ACCESS_TOKEN_SECRET', '')) if profile_data.get('X_ACCESS_TOKEN_SECRET') else 'Not set'}")
    oauth2_app = _get_oauth2_app_config(config)
    if oauth2_app:
        from .oauth2 import DEFAULT_OAUTH2_SCOPES

        raw_scopes = oauth2_app.get("X_OAUTH2_SCOPES")
        scopes_display = raw_scopes or f"Default ({DEFAULT_OAUTH2_SCOPES})"
        print("OAuth2 App Configuration (shared):")
        print("  Client ID: " + ("Set" if oauth2_app.get("X_OAUTH2_CLIENT_ID") else "Not set"))
        print("  Client Secret: " + ("Set" if oauth2_app.get("X_OAUTH2_CLIENT_SECRET") else "Not set"))
        print("  OAuth2 Redirect URI: " + (oauth2_app.get("X_OAUTH2_REDIRECT_URI") or "Not set"))
        print("  OAuth2 Scopes: " + scopes_display)

def prompt_for_oauth2_credentials(profile: str | None = None) -> None:
    """Prompt user for OAuth2 credentials and save them."""
    print("X CLI OAuth2 Configuration")
    print("==========================")
    print("Configure OAuth2 (Authorization Code with PKCE).")
    print("You can get these from your app settings in the X developer console.")
    print()

    _ = profile
    config = load_config()
    oauth2_app = _get_oauth2_app_config(config)
    oauth2_app["X_OAUTH2_CLIENT_ID"] = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client Secret (optional): ").strip()
    if client_secret:
        oauth2_app["X_OAUTH2_CLIENT_SECRET"] = client_secret
    oauth2_app["X_OAUTH2_REDIRECT_URI"] = input("OAuth2 Redirect URI: ").strip()
    scopes = input("OAuth2 Scopes (space-separated, optional): ").strip()
    if scopes:
        oauth2_app["X_OAUTH2_SCOPES"] = scopes

    missing = [
        key
        for key in ("X_OAUTH2_CLIENT_ID", "X_OAUTH2_REDIRECT_URI")
        if not oauth2_app.get(key)
    ]
    if missing:
        print(f"\nError: Missing required fields: {', '.join(missing)}")
        return

    try:
        config["oauth2_app"] = oauth2_app
        save_config(config)
        config_path = get_config_path()
        print(f"\n✅ OAuth2 configuration saved to {config_path}")
    except RuntimeError as e:
        print(f"\n❌ {e}")
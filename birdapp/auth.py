from typing import Any

from requests_oauthlib import OAuth1, OAuth2Session

from .config import get_credential


def create_oauth1_auth() -> OAuth1:
    """Create OAuth1 authentication object for Twitter API requests."""
    required_vars = [
        ("X_API_KEY", get_credential("X_API_KEY")),
        ("X_API_SECRET", get_credential("X_API_SECRET")),
        ("X_ACCESS_TOKEN", get_credential("X_ACCESS_TOKEN")),
        ("X_ACCESS_TOKEN_SECRET", get_credential("X_ACCESS_TOKEN_SECRET"))
    ]
    
    missing_vars = [var_name for var_name, var_value in required_vars if not var_value]
    
    if missing_vars:
        raise ValueError(
            f"Missing required credentials: {', '.join(missing_vars)}. "
            "Run `birdapp auth config --oauth1` to set up your credentials."
        )
    
    return OAuth1(
        required_vars[0][1],  # X_API_KEY
        required_vars[1][1],  # X_API_SECRET
        required_vars[2][1],  # X_ACCESS_TOKEN
        required_vars[3][1]   # X_ACCESS_TOKEN_SECRET
    )

def create_oauth2_session(token: dict[str, Any]) -> OAuth2Session:
    """Create an OAuth2 session from an existing token."""
    return OAuth2Session(token=token)
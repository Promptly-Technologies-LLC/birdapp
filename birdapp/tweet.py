import logging
import os

import requests

from . import config as config_module
from .auth import create_oauth1_auth
from .media import create_media_payload
from .utils import extract_tweet_id

logger = logging.getLogger(__name__)

def _get_env_or_config(key: str) -> str | None:
    return os.getenv(key) or config_module.get_credential(key)

def _has_oauth2_app_config() -> bool:
    # OAuth2 app keys are shared (not per-profile), but we still use
    # get_credential so profile selection logic remains consistent.
    return bool(_get_env_or_config("X_OAUTH2_CLIENT_ID") and _get_env_or_config("X_OAUTH2_REDIRECT_URI"))

def _has_oauth1_credentials() -> bool:
    return all(
        _get_env_or_config(key)
        for key in (
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN",
            "X_ACCESS_TOKEN_SECRET",
        )
    )

def _selected_profile_name() -> str | None:
    profile_override = getattr(config_module, "_PROFILE_OVERRIDE", None)
    return profile_override or config_module.get_active_profile()

def create_text_payload(text: str) -> dict[str, str]:
    return {"text": text}

def create_tweet_payload(text: str, media_path: str | None = None, reply_to: str | None = None) -> dict:
    payload = {}
    
    # Add text if provided and not empty
    if text and text.strip():
        payload.update(create_text_payload(text=text))
    
    # Add media if provided
    if media_path:
        media_payload = create_media_payload(path=media_path)
        payload.update(media_payload)
    
    # Add reply parameters if provided
    if reply_to:
        tweet_id = extract_tweet_id(reply_to)
        payload["reply"] = {
            "in_reply_to_tweet_id": tweet_id
        }
    
    return payload

def construct_tweet_link(tweet_id: str) -> str:
    """Construct the tweet link from the username and tweet ID."""
    username = config_module.get_credential("X_USERNAME")
    if not username:
        return f"https://x.com/status/{tweet_id}"
    return f"https://x.com/{username}/status/{tweet_id}"

def _load_oauth2_access_token() -> str | None:
    """
    Load an OAuth2 access token for the currently selected profile.

    Profile selection respects `birdapp --profile ...` because `get_credential`
    consults the profile override.
    """
    profile_name = _selected_profile_name()
    if not profile_name:
        return None

    from . import session as session_module

    loaded = session_module.load_any_oauth2_token(profile_name)
    if not loaded:
        return None
    _, token = loaded
    access_token = token.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    return access_token.strip()


def handle_tweet_response(response: requests.Response) -> tuple[bool, str]:
    """
    Handle the response from posting a tweet.
    Returns (success, message) tuple where:
    - success: Boolean indicating if the tweet was posted successfully
    - message: A user-friendly message describing the result
    """
    if response.ok:
        tweet_id = response.json().get("data", {}).get("id", "")
        tweet_link = construct_tweet_link(tweet_id=tweet_id)
        logger.info("Successfully posted tweet: %s", tweet_link)
        return True, f"Tweet posted successfully! View it at: {tweet_link}"

    try:
        error_details = response.json()
        if 'errors' in error_details:
            error_messages = [error['message'] for error in error_details['errors']]
            error_msg = '; '.join(error_messages)
            logger.error("Twitter API errors: %s", error_messages)
        else:
            status_code = response.status_code
            if status_code == 429:
                error_msg = "Rate limit exceeded. Please wait a few minutes and try again."
            elif status_code == 503:
                error_msg = (
                    "Error (503): Service Unavailable. "
                    "The X API is not responding. This may indicate that your API plan "
                    "does not support this endpoint or that the API is experiencing an outage. "
                    "Check your plan at https://developer.x.com/en/portal/products."
                )
                logger.error("API returned 503 Service Unavailable")
            else:
                detail = error_details.get('detail') or error_details.get('title') or response.reason
                error_msg = f"Error ({status_code}): {detail}"
                logger.error("API error %d: %s", status_code, detail)

        status_code = response.status_code
        if status_code == 403:
            detail_text = ""
            if isinstance(error_details, dict):
                detail_text = str(error_details.get("detail") or error_details.get("title") or "")
            if "scope" in detail_text.lower() or "permission" in detail_text.lower():
                from .oauth2 import DEFAULT_OAUTH2_SCOPES

                error_msg = (
                    f"{error_msg} "
                    "Your OAuth2 token likely lacks `tweet.write`. "
                    "Re-run `birdapp auth config --oauth2` (set `X_OAUTH2_SCOPES` to "
                    f"`{DEFAULT_OAUTH2_SCOPES}`), then re-run `birdapp auth login`."
                )
    except ValueError:
        error_msg = f"Error ({response.status_code}): {response.reason}"
        logger.error("Failed to parse error response: %s", response.text)
    
    logger.error("Failed to post tweet: %s", error_msg)
    return False, f"Failed to post tweet: {error_msg}"

def submit_tweet(text: str, media_path: str | None = None, reply_to: str | None = None) -> requests.Response:
    """
    Post a tweet with optional media and reply.

    Prefers OAuth2 (Bearer token) when a stored token exists for the selected
    profile; otherwise falls back to OAuth1.
    Returns the raw response object.
    """
    tweet_payload = create_tweet_payload(text=text, media_path=media_path, reply_to=reply_to)
    logger.info(f"Posting tweet with payload: {tweet_payload}")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    access_token = _load_oauth2_access_token()
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
        response = requests.request(
            method="POST",
            url="https://api.x.com/2/tweets",
            json=tweet_payload,
            headers=headers,
        )

        if response.status_code == 401:
            from . import oauth2 as oauth2_module
            from . import session as session_module

            profile_name = _selected_profile_name()
            if profile_name:
                loaded = session_module.load_any_oauth2_token(profile_name)
                if loaded:
                    user_id, token = loaded
                    refresh_token = token.get("refresh_token")
                    client_id = _get_env_or_config("X_OAUTH2_CLIENT_ID")
                    client_secret = _get_env_or_config("X_OAUTH2_CLIENT_SECRET")
                    if isinstance(refresh_token, str) and refresh_token.strip() and isinstance(client_id, str) and client_id.strip():
                        refreshed = oauth2_module.refresh_access_token(
                            refresh_token=refresh_token.strip(),
                            client_id=client_id.strip(),
                            client_secret=client_secret.strip() if isinstance(client_secret, str) and client_secret.strip() else None,
                        )
                        merged = dict(token)
                        merged.update(refreshed)
                        if "refresh_token" not in merged and isinstance(refresh_token, str):
                            merged["refresh_token"] = refresh_token
                        session_module.save_token(user_id=user_id, token=merged, profile=profile_name)

                        new_access = merged.get("access_token")
                        if isinstance(new_access, str) and new_access.strip():
                            headers["Authorization"] = f"Bearer {new_access.strip()}"
                            return requests.request(
                                method="POST",
                                url="https://api.x.com/2/tweets",
                                json=tweet_payload,
                                headers=headers,
                            )

            profile_hint = f"--profile {profile_name} " if profile_name else ""
            raise RuntimeError(
                "OAuth2 token appears expired or invalid for this profile. "
                f"Run `birdapp {profile_hint}auth login` to re-authenticate."
            )

        return response

    # No OAuth2 access token is available for this profile. If OAuth2 is
    # configured, prefer guiding the user through OAuth2 login instead of
    # falling back to OAuth1 and prompting for OAuth1 credentials.
    if _has_oauth2_app_config() and not _has_oauth1_credentials():
        profile_name = _selected_profile_name()
        profile_hint = f"--profile {profile_name} " if profile_name else ""
        raise RuntimeError(
            "No OAuth2 login token is stored for this profile. "
            f"Run `birdapp {profile_hint}auth login` to complete OAuth2 login."
        )

    auth = create_oauth1_auth()
    return requests.request(
        method="POST",
        url="https://api.x.com/2/tweets",
        json=tweet_payload,
        auth=auth,
        headers=headers,
    )

def post_tweet(text: str, media_path: str | None = None, reply_to: str | None = None) -> tuple[bool, str]:
    """
    Post a tweet with optional media and reply using OAuth1 authentication.
    Returns (success, message) tuple.
    """
    try:
        response = submit_tweet(text=text, media_path=media_path, reply_to=reply_to)
        return handle_tweet_response(response)
    except Exception as e:
        logger.error("Error posting tweet: %s", str(e))
        return False, f"Error posting tweet: {e!s}"

def get_tweets_by_ids(tweet_ids: list[str]) -> tuple[bool, str | dict]:
    """
    Retrieve tweets by their IDs using the X API.
    Returns (success, result) tuple where result is either error message or tweet data.
    """
    if not tweet_ids:
        return False, "No tweet IDs provided"
    
    if len(tweet_ids) > 100:
        return False, "Too many tweet IDs provided (maximum 100)"
    
    try:
        auth = create_oauth1_auth()
        ids_param = ",".join(tweet_ids)
        
        response = requests.get(
            url="https://api.x.com/2/tweets",
            params={
                "ids": ids_param,
                "tweet.fields": "created_at,author_id,public_metrics,context_annotations,lang,possibly_sensitive",
                "expansions": "author_id",
                "user.fields": "name,username,verified,public_metrics"
            },
            auth=auth
        )
        
        if response.ok:
            data = response.json()
            logger.info("Successfully retrieved tweets")
            return True, data
        else:
            try:
                error_details = response.json()
                if 'errors' in error_details:
                    error_messages = [error['detail'] for error in error_details['errors']]
                    error_msg = '; '.join(error_messages)
                else:
                    error_msg = f"Error ({response.status_code}): {response.reason}"
                logger.error("Failed to retrieve tweets: %s", error_msg)
                return False, error_msg
            except ValueError:
                error_msg = f"Error ({response.status_code}): {response.reason}"
                logger.error("Failed to parse error response: %s", response.text)
                return False, error_msg
                
    except Exception as e:
        logger.error("Error retrieving tweets: %s", str(e))
        return False, f"Error retrieving tweets: {e!s}"

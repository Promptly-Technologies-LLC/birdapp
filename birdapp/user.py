from typing import Any

import requests

from .auth import create_oauth1_auth
from .config import load_config


def get_user_by_id(user_id: str, user_fields: list[str] | None = None, expansions: list[str] | None = None, tweet_fields: list[str] | None = None) -> tuple[bool, dict[str, Any] | str]:
    """
    Get user details by user ID
    
    Args:
        user_id: The ID of the user to lookup
        user_fields: Optional list of user fields to include in response
        expansions: Optional list of expansions
        tweet_fields: Optional list of tweet fields when expanding pinned_tweet_id
    
    Returns:
        Tuple of (success, response_data or error_message)
    """
    creds = load_config()
    if not creds:
        return False, "No credentials configured. Run 'x config' first."
    
    auth = create_oauth1_auth()
    
    url = f"https://api.x.com/2/users/{user_id}"
    
    params = {}
    if user_fields:
        params['user.fields'] = ','.join(user_fields)
    if expansions:
        params['expansions'] = ','.join(expansions)
    if tweet_fields:
        params['tweet.fields'] = ','.join(tweet_fields)
    
    try:
        response = requests.get(url, auth=auth, params=params)
        response.raise_for_status()
        return True, response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return False, f"User with ID {user_id} not found"
        return False, f"HTTP error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return False, str(e)

def get_users_by_ids(user_ids: list[str], user_fields: list[str] | None = None, expansions: list[str] | None = None, tweet_fields: list[str] | None = None) -> tuple[bool, dict[str, Any] | str]:
    """
    Get multiple users by their IDs
    
    Args:
        user_ids: List of user IDs to lookup (max 100)
        user_fields: Optional list of user fields to include in response
        expansions: Optional list of expansions
        tweet_fields: Optional list of tweet fields when expanding pinned_tweet_id
    
    Returns:
        Tuple of (success, response_data or error_message)
    """
    if len(user_ids) > 100:
        return False, "Maximum of 100 user IDs allowed per request"
    
    creds = load_config()
    if not creds:
        return False, "No credentials configured. Run 'x config' first."
    
    auth = create_oauth1_auth()
    
    url = "https://api.x.com/2/users"
    
    params = {
        'ids': ','.join(user_ids)
    }
    if user_fields:
        params['user.fields'] = ','.join(user_fields)
    if expansions:
        params['expansions'] = ','.join(expansions)
    if tweet_fields:
        params['tweet.fields'] = ','.join(tweet_fields)
    
    try:
        response = requests.get(url, auth=auth, params=params)
        response.raise_for_status()
        return True, response.json()
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return False, str(e)

def get_user_by_username(username: str, user_fields: list[str] | None = None, expansions: list[str] | None = None, tweet_fields: list[str] | None = None) -> tuple[bool, dict[str, Any] | str]:
    """
    Get user details by username
    
    Args:
        username: The username (without @) of the user to lookup
        user_fields: Optional list of user fields to include in response
        expansions: Optional list of expansions
        tweet_fields: Optional list of tweet fields when expanding pinned_tweet_id
    
    Returns:
        Tuple of (success, response_data or error_message)
    """
    # Remove @ if present
    username = username.lstrip('@')
    
    creds = load_config()
    if not creds:
        return False, "No credentials configured. Run 'x config' first."
    
    auth = create_oauth1_auth()
    
    url = f"https://api.x.com/2/users/by/username/{username}"
    
    params = {}
    if user_fields:
        params['user.fields'] = ','.join(user_fields)
    if expansions:
        params['expansions'] = ','.join(expansions)
    if tweet_fields:
        params['tweet.fields'] = ','.join(tweet_fields)
    
    try:
        response = requests.get(url, auth=auth, params=params)
        response.raise_for_status()
        return True, response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return False, f"User @{username} not found"
        return False, f"HTTP error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return False, str(e)

def get_users_by_usernames(usernames: list[str], user_fields: list[str] | None = None, expansions: list[str] | None = None, tweet_fields: list[str] | None = None) -> tuple[bool, dict[str, Any] | str]:
    """
    Get multiple users by their usernames
    
    Args:
        usernames: List of usernames to lookup (max 100)
        user_fields: Optional list of user fields to include in response
        expansions: Optional list of expansions
        tweet_fields: Optional list of tweet fields when expanding pinned_tweet_id
    
    Returns:
        Tuple of (success, response_data or error_message)
    """
    if len(usernames) > 100:
        return False, "Maximum of 100 usernames allowed per request"
    
    # Remove @ from all usernames
    usernames = [u.lstrip('@') for u in usernames]
    
    creds = load_config()
    if not creds:
        return False, "No credentials configured. Run 'x config' first."
    
    auth = create_oauth1_auth()
    
    url = "https://api.x.com/2/users/by"
    
    params = {
        'usernames': ','.join(usernames)
    }
    if user_fields:
        params['user.fields'] = ','.join(user_fields)
    if expansions:
        params['expansions'] = ','.join(expansions)
    if tweet_fields:
        params['tweet.fields'] = ','.join(tweet_fields)
    
    try:
        response = requests.get(url, auth=auth, params=params)
        response.raise_for_status()
        return True, response.json()
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return False, str(e)

# Available user fields for CLI help text
AVAILABLE_USER_FIELDS = [
    'affiliation', 'confirmed_email', 'connection_status', 'created_at', 
    'description', 'entities', 'id', 'is_identity_verified', 'location', 
    'most_recent_tweet_id', 'name', 'parody', 'pinned_tweet_id', 
    'profile_banner_url', 'profile_image_url', 'protected', 'public_metrics', 
    'receives_your_dm', 'subscription', 'subscription_type', 'url', 'username', 
    'verified', 'verified_followers_count', 'verified_type', 'withheld'
]

AVAILABLE_EXPANSIONS = [
    'affiliation.user_id', 'most_recent_tweet_id', 'pinned_tweet_id'
]

AVAILABLE_TWEET_FIELDS = [
    'article', 'attachments', 'author_id', 'card_uri', 'community_id',
    'context_annotations', 'conversation_id', 'created_at', 'display_text_range',
    'edit_controls', 'edit_history_tweet_ids', 'entities', 'geo', 'id',
    'in_reply_to_user_id', 'lang', 'media_metadata', 'non_public_metrics',
    'note_tweet', 'organic_metrics', 'possibly_sensitive', 'promoted_metrics',
    'public_metrics', 'referenced_tweets', 'reply_settings', 'scopes',
    'source', 'text', 'withheld'
]
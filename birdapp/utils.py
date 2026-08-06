import atexit
import os
import re
import shutil
import tempfile

# In-memory path for the temp directory
temp_dir_path = None

def get_temp_dir() -> str:
    global temp_dir_path
    if not temp_dir_path:
        temp_dir_path = tempfile.mkdtemp()
    return temp_dir_path

def cleanup_temp_dir() -> None:
    global temp_dir_path
    if temp_dir_path and os.path.exists(temp_dir_path):
        shutil.rmtree(temp_dir_path)
        temp_dir_path = None

# Register cleanup function
atexit.register(cleanup_temp_dir)

def extract_tweet_id(tweet_ref: str) -> str:
    """
    Extract tweet ID from either a tweet ID or URL.
    
    Args:
        tweet_ref: Either a tweet ID or a tweet URL
        
    Returns:
        The tweet ID
        
    Examples:
        extract_tweet_id("1234567890") -> "1234567890"
        extract_tweet_id("https://x.com/user/status/1234567890") -> "1234567890"
        extract_tweet_id("https://twitter.com/user/status/1234567890") -> "1234567890"
    """
    # If it's already just an ID (all digits), return it
    if tweet_ref.isdigit():
        return tweet_ref
    
    # Try to extract ID from URL
    # Matches both x.com and twitter.com URLs
    url_pattern = r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/[^/]+/status/(\d+)'
    match = re.search(url_pattern, tweet_ref)
    
    if match:
        return match.group(1)
    
    # If no pattern matches, assume it's already an ID
    return tweet_ref
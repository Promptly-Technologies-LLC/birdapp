import logging

import requests

from .auth import create_oauth1_auth

logger = logging.getLogger("uvicorn.error")

def create_media_payload(path: str | None) -> dict[str, dict[str, list[str]]]:
    """Upload media using OAuth1 authentication and return a payload containing the media ID."""
    if not path:
        return {"media": {"media_ids": []}}
        
    auth = create_oauth1_auth()
    upload_url = "https://upload.twitter.com/1.1/media/upload.json"
    
    try:
        with open(path, "rb") as file:
            files = {"media": file}
            logger.info(f"Uploading media to {upload_url}")
            response = requests.post(upload_url, auth=auth, files=files)
            response.raise_for_status()
            media_id = response.json().get("media_id_string")
            if media_id:
                return {"media": {"media_ids": [media_id]}}
    except Exception as e:
        logger.error(f"Error uploading media: {e}")
    
    return {"media": {"media_ids": []}}
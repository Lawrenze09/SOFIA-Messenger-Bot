"""
services/messenger_service.py

Facebook Messenger Graph API wrapper.
Handles sending text messages to customers.
"""

import requests

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

_GRAPH_API_URL = "https://graph.facebook.com/v22.0/me/messages"


def send_message(psid: str, text: str) -> bool:
    """
    Send a text message to a Messenger user via the Graph API.

    Args:
        psid: Facebook Page-Scoped ID of the recipient.
        text: Message text to send.

    Returns:
        True if message was sent successfully, False otherwise.
    """
    try:
        response = requests.post(
            _GRAPH_API_URL,
            params={"access_token": settings.page_access_token},
            json={
                "recipient": {"id": psid},
                "message":   {"text": text},
            },
            timeout=10,
        )
        if response.status_code == 200:
            return True

        logger.error(
            f"Messenger send failed — status: {response.status_code} "
            f"body: {response.text[:200]}"
        )
        return False

    except requests.RequestException as exc:
        logger.error(f"Messenger send exception for {psid}: {exc}")
        return False

def send_image(psid: str, image_url: str) -> bool:
    """
    Send an image attachment to a Messenger user.
    """
    try:
        response = requests.post(
            _GRAPH_API_URL,
            params={"access_token": settings.page_access_token},
            json={
                "recipient": {"id": psid},
                "message": {
                    "attachment": {
                        "type": "image",
                        "payload": {
                            "url": image_url,
                            "is_reusable": True
                        }
                    }
                },
            },
            timeout=10,
        )
        if response.status_code == 200:
            logger.info(f"Image sent successfully to {psid}")
            return True

        logger.error(f"Image send failed — status: {response.status_code} body: {response.text}")
        return False

    except requests.RequestException as exc:
        logger.error(f"Image send exception for {psid}: {exc}")
        return False
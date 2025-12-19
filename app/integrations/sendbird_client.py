import httpx
from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any


class SendbirdClient:
    BASE_URL = f"https://api-{settings.SENDBIRD_APP_ID}.sendbird.com"

    @staticmethod
    def _get_headers() -> Dict[str, str]:
        return {
            "Api-Token": settings.SENDBIRD_API_TOKEN,
            "Content-Type": "application/json",
        }

    @staticmethod
    def create_user(user_id: str, nickname: str, profile_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{SendbirdClient.BASE_URL}/v3/users",
                    headers=SendbirdClient._get_headers(),
                    json={
                        "user_id": user_id,
                        "nickname": nickname,
                        "profile_url": profile_url,
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to create Sendbird user: {e}")
            return None

    @staticmethod
    def create_channel(channel_url: str, user_ids: list, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{SendbirdClient.BASE_URL}/v3/group_channels",
                    headers=SendbirdClient._get_headers(),
                    json={
                        "channel_url": channel_url,
                        "user_ids": user_ids,
                        "name": name,
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to create Sendbird channel: {e}")
            return None

    @staticmethod
    def send_message(channel_url: str, user_id: str, message: str) -> Optional[Dict[str, Any]]:
        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{SendbirdClient.BASE_URL}/v3/group_channels/{channel_url}/messages",
                    headers=SendbirdClient._get_headers(),
                    json={
                        "user_id": user_id,
                        "message": message,
                        "message_type": "MESG",
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to send Sendbird message: {e}")
            return None

    @staticmethod
    def get_channels(user_id: str, limit: int = 20) -> Optional[Dict[str, Any]]:
        """Get channels for a user"""
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{SendbirdClient.BASE_URL}/v3/users/{user_id}/group_channels",
                    headers=SendbirdClient._get_headers(),
                    params={"limit": limit},
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Sendbird channels: {e}")
            return None

    @staticmethod
    def get_channel(channel_url: str) -> Optional[Dict[str, Any]]:
        """Get channel details"""
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{SendbirdClient.BASE_URL}/v3/group_channels/{channel_url}",
                    headers=SendbirdClient._get_headers(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Sendbird channel: {e}")
            return None

    @staticmethod
    def get_messages(channel_url: str, limit: int = 50, token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get messages from a channel"""
        try:
            with httpx.Client() as client:
                params = {"limit": limit}
                if token:
                    params["token"] = token
                
                response = client.get(
                    f"{SendbirdClient.BASE_URL}/v3/group_channels/{channel_url}/messages",
                    headers=SendbirdClient._get_headers(),
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Sendbird messages: {e}")
            return None

    @staticmethod
    def update_channel(channel_url: str, name: Optional[str] = None, cover_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Update channel details"""
        try:
            with httpx.Client() as client:
                data = {}
                if name:
                    data["name"] = name
                if cover_url:
                    data["cover_url"] = cover_url
                
                response = client.put(
                    f"{SendbirdClient.BASE_URL}/v3/group_channels/{channel_url}",
                    headers=SendbirdClient._get_headers(),
                    json=data,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to update Sendbird channel: {e}")
            return None

    @staticmethod
    def delete_channel(channel_url: str) -> bool:
        """Delete a channel"""
        try:
            with httpx.Client() as client:
                response = client.delete(
                    f"{SendbirdClient.BASE_URL}/v3/group_channels/{channel_url}",
                    headers=SendbirdClient._get_headers(),
                    timeout=30.0
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Failed to delete Sendbird channel: {e}")
            return False


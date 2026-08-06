import os
import logging
from pathlib import Path
from typing import List, Dict, Optional
from pyrogram import Client
from config import settings

logger = logging.getLogger(__name__)

class SessionManager:
    """Manages Telegram user sessions and Pyrogram Client instances."""
    
    def __init__(self, sessions_dir: Optional[Path] = None):
        self.sessions_dir = sessions_dir or settings.sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.active_clients: Dict[str, Client] = {}

    def get_existing_sessions(self) -> List[str]:
        """List all existing session names in the sessions directory."""
        sessions = []
        for file in os.listdir(self.sessions_dir):
            if file.endswith(".session"):
                sessions.append(file[:-8])
        return sorted(sessions)

    def create_client(
        self,
        session_name: str,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        proxy_url: Optional[str] = None
    ) -> Client:
        """Instantiate a Pyrogram client for a session name."""
        eff_api_id = api_id or settings.api_id
        eff_api_hash = api_hash or settings.api_hash
        
        if not eff_api_id or not eff_api_hash:
            raise ValueError(
                "API_ID and API_HASH are required. Please set them in your .env file or pass them explicitly."
            )

        session_path = str(self.sessions_dir / session_name)
        proxy = settings.parse_proxy(proxy_url)

        client = Client(
            name=session_path,
            api_id=eff_api_id,
            api_hash=eff_api_hash,
            proxy=proxy,
            workdir=str(self.sessions_dir)
        )
        return client

    async def start_session(
        self,
        session_name: str,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        proxy_url: Optional[str] = None
    ) -> Client:
        """Start and authenticate a Telegram client session."""
        if session_name in self.active_clients:
            client = self.active_clients[session_name]
            if client.is_connected:
                return client

        client = self.create_client(session_name, api_id, api_hash, proxy_url)
        await client.start()
        
        me = await client.get_me()
        logger.info(f"Successfully logged in as: {me.first_name} (@{me.username or 'NoUsername'}) [ID: {me.id}]")
        
        self.active_clients[session_name] = client
        return client

    async def stop_session(self, session_name: str):
        """Stop an active Telegram client session."""
        if session_name in self.active_clients:
            client = self.active_clients.pop(session_name)
            if client.is_connected:
                await client.stop()
                logger.info(f"Session '{session_name}' stopped.")

    async def stop_all(self):
        """Stop all active client sessions."""
        for name in list(self.active_clients.keys()):
            await self.stop_session(name)

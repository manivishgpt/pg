import csv
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from pyrogram import Client
from config import settings
from core.anti_flood import handle_flood_wait

logger = logging.getLogger(__name__)

class TelegramScraperModule:
    """Telegram group, channel, and user scraping utility."""

    def __init__(self, client: Client, output_dir: Optional[Path] = None):
        self.client = client
        self.output_dir = output_dir or settings.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @handle_flood_wait()
    async def scrape_members(self, chat_id: str, limit: int = 5000) -> List[Dict[str, Any]]:
        """Scrape member details from a group/supergroup."""
        members = []
        logger.info(f"Fetching member list for chat '{chat_id}' (limit: {limit})...")

        async for member in self.client.get_chat_members(chat_id, limit=limit):
            user = member.user
            status = str(member.status).split('.')[-1] if member.status else "UNKNOWN"
            members.append({
                "user_id": user.id,
                "username": user.username or "",
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "phone": user.phone_number or "",
                "is_bot": user.is_bot,
                "role_status": status
            })

        logger.info(f"Scraped {len(members)} members successfully.")
        return members

    @handle_flood_wait()
    async def scrape_messages(self, chat_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """Scrape message history from a channel or group."""
        messages = []
        logger.info(f"Fetching message history for chat '{chat_id}' (limit: {limit})...")

        async for msg in self.client.get_chat_history(chat_id, limit=limit):
            sender_id = msg.from_user.id if msg.from_user else (msg.sender_chat.id if msg.sender_chat else 0)
            messages.append({
                "message_id": msg.id,
                "date": msg.date.isoformat() if msg.date else "",
                "sender_id": sender_id,
                "text": msg.text or msg.caption or "",
                "has_media": bool(msg.media),
                "media_type": str(msg.media).split('.')[-1] if msg.media else None,
                "views": msg.views or 0,
                "forwards": msg.forwards or 0
            })

        logger.info(f"Scraped {len(messages)} messages successfully.")
        return messages

    @handle_flood_wait()
    async def find_writable_groups(self) -> List[Dict[str, Any]]:
        """Scan all joined chats/groups and filter those where message posting is allowed."""
        writable_groups = []
        logger.info("Scanning joined dialogs for groups with message sending permissions...")

        async for dialog in self.client.get_dialogs():
            chat = dialog.chat
            # Filter for Group or Supergroup types
            if str(chat.type) in ["ChatType.GROUP", "ChatType.SUPERGROUP"]:
                can_send = True
                
                # Check permissions if available
                if chat.permissions is not None:
                    can_send = getattr(chat.permissions, "can_send_messages", True)
                
                # Check if restricted
                if getattr(chat, "is_restricted", False):
                    can_send = False

                if can_send:
                    writable_groups.append({
                        "chat_id": chat.id,
                        "title": chat.title or "",
                        "username": chat.username or "",
                        "type": str(chat.type).split('.')[-1],
                        "members_count": getattr(chat, "members_count", 0) or 0,
                        "can_send_messages": True
                    })

        logger.info(f"Found {len(writable_groups)} writable groups.")
        return writable_groups

    @handle_flood_wait()
    async def find_my_admin_groups(self) -> List[Dict[str, Any]]:
        """Scan all joined chats/channels and filter those where the account is an Owner or Admin."""
        admin_chats = []
        logger.info("Scanning joined dialogs for groups & channels where account is Owner/Admin...")

        async for dialog in self.client.get_dialogs():
            chat = dialog.chat
            try:
                member = await self.client.get_chat_member(chat.id, "me")
                status_str = str(member.status).split('.')[-1].upper()

                if status_str in ["OWNER", "ADMINISTRATOR", "CREATOR"]:
                    role_label = "OWNER (Creator)" if status_str in ["OWNER", "CREATOR"] else "ADMINISTRATOR"
                    admin_chats.append({
                        "chat_id": chat.id,
                        "title": chat.title or "",
                        "username": chat.username or "",
                        "type": str(chat.type).split('.')[-1],
                        "role": role_label,
                        "members_count": getattr(chat, "members_count", 0) or 0
                    })
            except Exception as e:
                logger.debug(f"Skipping chat '{chat.title}': {e}")

        logger.info(f"Found {len(admin_chats)} Admin/Owner groups & channels.")
        return admin_chats

    @handle_flood_wait()
    async def find_active_chatting_groups(self, max_age_hours: float = 24.0, min_recent_messages: int = 3) -> List[Dict[str, Any]]:
        """
        Scan all joined groups/supergroups and filter those with high active continuous chatting activity.
        Evaluates posting permission (can_send_messages = True), top message freshness, and recent message frequency.
        """
        import datetime
        active_groups = []
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff_time = now - datetime.timedelta(hours=max_age_hours)

        logger.info(f"Scanning joined dialogs for active continuous chatting groups (Cutoff: {max_age_hours}h)...")

        async for dialog in self.client.get_dialogs():
            chat = dialog.chat
            if str(chat.type) in ["ChatType.GROUP", "ChatType.SUPERGROUP"]:
                can_send = True
                if chat.permissions is not None:
                    can_send = getattr(chat.permissions, "can_send_messages", True)
                if getattr(chat, "is_restricted", False):
                    can_send = False

                if not can_send:
                    continue

                top_msg = dialog.top_message
                if not top_msg or not top_msg.date:
                    continue

                # Check top message timestamp freshness
                msg_date = top_msg.date
                if msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=datetime.timezone.utc)

                if msg_date < cutoff_time:
                    continue

                # Inspect recent 20 messages to measure continuous chat activity
                recent_msgs_count = 0
                unique_senders = set()
                last_activity_date = msg_date

                try:
                    async for msg in self.client.get_chat_history(chat.id, limit=20):
                        if not msg.date:
                            continue
                        m_date = msg.date
                        if m_date.tzinfo is None:
                            m_date = m_date.replace(tzinfo=datetime.timezone.utc)

                        if m_date >= cutoff_time:
                            recent_msgs_count += 1
                            sender_id = msg.from_user.id if msg.from_user else (msg.sender_chat.id if msg.sender_chat else 0)
                            if sender_id:
                                unique_senders.add(sender_id)
                except Exception as e:
                    logger.debug(f"Could not fetch history for active group verification on '{chat.title}': {e}")
                    recent_msgs_count = 1

                if recent_msgs_count >= min_recent_messages:
                    active_groups.append({
                        "chat_id": chat.id,
                        "title": chat.title or "",
                        "username": chat.username or "",
                        "type": str(chat.type).split('.')[-1],
                        "members_count": getattr(chat, "members_count", 0) or 0,
                        "recent_messages_24h": recent_msgs_count,
                        "unique_senders_24h": len(unique_senders),
                        "last_active_time": last_activity_date.strftime("%Y-%m-%d %H:%M:%S"),
                        "can_send_messages": True
                    })

        # Sort by most active recent message count descending
        active_groups.sort(key=lambda g: (g["recent_messages_24h"], g["unique_senders_24h"]), reverse=True)
        logger.info(f"Found {len(active_groups)} active continuous chatting groups.")
        return active_groups

    def export_to_csv(self, data: List[Dict[str, Any]], filename: str) -> Path:
        """Export scraped dictionary list to CSV file."""
        if not filename.endswith('.csv'):
            filename += '.csv'
        filepath = self.output_dir / filename
        
        if not data:
            logger.warning("No data to export to CSV.")
            return filepath

        fieldnames = list(data[0].keys())
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

        logger.info(f"Data exported to CSV: {filepath}")
        return filepath

    def export_to_json(self, data: List[Dict[str, Any]], filename: str) -> Path:
        """Export scraped data to JSON file."""
        if not filename.endswith('.json'):
            filename += '.json'
        filepath = self.output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Data exported to JSON: {filepath}")
        return filepath

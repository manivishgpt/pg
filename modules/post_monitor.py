import os
import csv
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Callable
from pyrogram import Client
from pyrogram.errors import RPCError

from config import settings

logger = logging.getLogger(__name__)

TRACKER_FILE = settings.output_dir / "sent_posts_tracker.json"
RESTRICTED_CSV = settings.output_dir / "restricted_groups.csv"
RESTRICTED_JSON = settings.output_dir / "restricted_groups.json"

class GroupBlacklistManager:
    """Manages restricted/blacklisted groups that delete posts or block links/media."""

    @staticmethod
    def get_blacklisted_ids() -> set:
        """Return set of blacklisted chat_ids as strings."""
        blacklisted = set()
        if RESTRICTED_CSV.exists():
            try:
                with open(RESTRICTED_CSV, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        cid = row.get("chat_id", "").strip()
                        if cid:
                            blacklisted.add(cid)
            except Exception as e:
                logger.error(f"Error reading {RESTRICTED_CSV}: {e}")
        return blacklisted

    @staticmethod
    def get_restricted_groups() -> List[Dict[str, Any]]:
        """Return full list of restricted groups from JSON."""
        if RESTRICTED_JSON.exists():
            try:
                with open(RESTRICTED_JSON, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    @classmethod
    def blacklist_group(
        cls,
        chat_id: Union[str, int],
        title: str = "",
        username: str = "",
        reason: str = "POST_DELETED_BY_BOT_OR_ADMIN"
    ) -> bool:
        """Add a group to the restricted/blacklisted list."""
        cid_str = str(chat_id).strip()
        existing = cls.get_restricted_groups()
        
        # Check if already blacklisted
        for g in existing:
            if str(g.get("chat_id")) == cid_str:
                return False

        entry = {
            "chat_id": cid_str,
            "title": title or "Unknown Group",
            "username": username or "",
            "reason": reason,
            "blacklisted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        existing.append(entry)

        # Save JSON
        try:
            with open(RESTRICTED_JSON, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write {RESTRICTED_JSON}: {e}")

        # Save CSV
        try:
            fieldnames = ["chat_id", "title", "username", "reason", "blacklisted_at"]
            with open(RESTRICTED_CSV, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in existing:
                    writer.writerow(row)
        except Exception as e:
            logger.error(f"Failed to write {RESTRICTED_CSV}: {e}")

        logger.warning(f"🛡️ [BLACKLISTED GROUP] Added chat '{title}' ({cid_str}) to blacklist. Reason: {reason}")
        return True

    @classmethod
    def filter_targets(cls, targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out blacklisted groups from a target list."""
        blacklisted_ids = cls.get_blacklisted_ids()
        filtered = []
        skipped_count = 0

        for t in targets:
            cid = str(t.get("chat_id", "")).strip()
            if cid in blacklisted_ids:
                skipped_count += 1
            else:
                filtered.append(t)

        if skipped_count > 0:
            logger.info(f"🛡️ Auto-filtered {skipped_count} blacklisted/restricted groups from target list.")
        return filtered


class SentPostTracker:
    """Logs sent posts and message IDs for health tracking."""

    @staticmethod
    def load_tracker() -> List[Dict[str, Any]]:
        if TRACKER_FILE.exists():
            try:
                with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    @classmethod
    def log_sent_post(
        cls,
        chat_id: Union[str, int],
        message_id: int,
        title: str = "",
        username: str = "",
        post_url: str = "",
        send_type: str = "forward"
    ):
        """Record a sent message entry in tracker."""
        tracker = cls.load_tracker()
        cid_str = str(chat_id).strip()

        entry = {
            "chat_id": cid_str,
            "message_id": message_id,
            "title": title or "Target Chat",
            "username": username or "",
            "post_url": post_url,
            "send_type": send_type,
            "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "ACTIVE",
            "last_checked_at": None
        }

        # Keep last 500 tracked posts
        tracker.append(entry)
        if len(tracker) > 500:
            tracker = tracker[-500:]

        try:
            with open(TRACKER_FILE, "w", encoding="utf-8") as f:
                json.dump(tracker, f, indent=2, ensure_ascii=False)
            logger.debug(f"Logged sent post {message_id} in {cid_str}")
        except Exception as e:
            logger.error(f"Failed to log sent post: {e}")


class PostHealthMonitor:
    """Verifies previously sent posts in groups and auto-blacklists groups if posts are deleted."""

    def __init__(self, client: Client):
        self.client = client

    async def check_all_tracked_posts(
        self,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None
    ) -> Dict[str, Any]:
        """Scan all logged posts in sent_posts_tracker.json and verify if they still exist."""
        tracker = SentPostTracker.load_tracker()
        if not tracker:
            return {"total_checked": 0, "active_count": 0, "deleted_count": 0, "new_blacklisted": 0}

        total = len(tracker)
        active_count = 0
        deleted_count = 0
        new_blacklisted = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info(f"Starting Post Health Verification Scan on {total} tracked messages...")

        for index, item in enumerate(tracker, start=1):
            chat_id_str = item["chat_id"]
            message_id = item["message_id"]
            title = item.get("title", "Chat")
            username = item.get("username", "")

            # Convert to int if numeric
            chat_target = int(chat_id_str) if (chat_id_str.startswith("-") and chat_id_str[1:].isdigit()) or chat_id_str.isdigit() else chat_id_str

            is_active = False
            error_reason = ""

            try:
                # Retrieve message from Telegram API
                msg = await self.client.get_messages(chat_id=chat_target, message_ids=message_id)
                
                # If msg is None or empty/service empty, it was deleted by bot/admin
                if msg and not msg.empty:
                    is_active = True
                    item["status"] = "ACTIVE"
                    active_count += 1
                else:
                    item["status"] = "DELETED"
                    deleted_count += 1
                    error_reason = "POST_DELETED_BY_BOT_OR_ADMIN"
            except RPCError as rpc_err:
                item["status"] = "DELETED"
                deleted_count += 1
                error_reason = f"RPC_ERROR: {rpc_err.MESSAGE}"
            except Exception as e:
                item["status"] = "DELETED"
                deleted_count += 1
                error_reason = str(e)

            item["last_checked_at"] = now_str

            if not is_active:
                logger.warning(f"[{index}/{total}] ⚠️ Post {message_id} in '{title}' ({chat_id_str}) was DELETED! Reason: {error_reason}")
                # Auto-blacklist group
                added = GroupBlacklistManager.blacklist_group(
                    chat_id=chat_id_str,
                    title=title,
                    username=username,
                    reason=error_reason or "POST_DELETED_BY_BOT_OR_ADMIN"
                )
                if added:
                    new_blacklisted += 1
            else:
                logger.info(f"[{index}/{total}] ✅ Post {message_id} in '{title}' is ACTIVE.")

            if progress_callback:
                progress_callback(index, total, title, "ACTIVE" if is_active else "DELETED")

            await asyncio.sleep(1.0) # Gentle rate limit

        # Save updated tracker
        try:
            with open(TRACKER_FILE, "w", encoding="utf-8") as f:
                json.dump(tracker, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to update tracker file: {e}")

        logger.info(f"Health Verification Complete. Checked: {total}, Active: {active_count}, Deleted: {deleted_count}, New Blacklisted Groups: {new_blacklisted}")

        return {
            "total_checked": total,
            "active_count": active_count,
            "deleted_count": deleted_count,
            "new_blacklisted": new_blacklisted
        }

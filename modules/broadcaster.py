import re
import csv
import random
import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any, Union, Tuple
from pyrogram import Client
from core.anti_flood import human_delay, handle_flood_wait
from config import settings
from modules.post_monitor import GroupBlacklistManager, SentPostTracker

logger = logging.getLogger(__name__)

# Anti-Ban Safety Presets
SAFETY_PRESETS = {
    "ultra_safe": {
        "name": "Ultra Safe (Anti-Ban)",
        "min_delay": 20.0,
        "max_delay": 45.0,
        "pause_every": 8,
        "pause_duration": 90.0,
        "description": "Recommended for public/writable groups to avoid account ban."
    },
    "balanced": {
        "name": "Balanced Mode",
        "min_delay": 10.0,
        "max_delay": 25.0,
        "pause_every": 10,
        "pause_duration": 60.0,
        "description": "Standard safe delay for moderate broadcasting."
    },
    "fast": {
        "name": "Fast Mode",
        "min_delay": 5.0,
        "max_delay": 12.0,
        "pause_every": 15,
        "pause_duration": 30.0,
        "description": "Faster delivery (use mainly for admin chats you own)."
    }
}

def parse_telegram_post_url(url: str) -> Tuple[Optional[Union[str, int]], Optional[int]]:
    """
    Parse a Telegram post URL into (from_chat, message_id).
    Supports formats:
      - https://t.me/username/1085
      - t.me/username/1085
      - https://t.me/c/1234567890/1085
      - @username/1085
    """
    clean_url = url.strip()
    
    # Private chat post link format: t.me/c/123456789/1085
    m_c = re.search(r't\.me/c/(\d+)/(\d+)', clean_url)
    if m_c:
        chat_id = int("-100" + m_c.group(1))
        msg_id = int(m_c.group(2))
        return chat_id, msg_id

    # Public channel post link format: t.me/username/1085 or @username/1085
    m_u = re.search(r'(?:t\.me/|@)?([^/\s]+)/(\d+)', clean_url)
    if m_u:
        from_chat = m_u.group(1).replace("https://", "").replace("http://", "")
        msg_id = int(m_u.group(2))
        return from_chat, msg_id

    return None, None

def load_targets_from_csv(csv_path: Union[str, Path], filter_blacklisted: bool = True) -> List[Dict[str, Any]]:
    """Extract deduplicated chat targets from CSV, automatically filtering out blacklisted groups."""
    p = Path(csv_path)
    if not p.exists():
        return []
    
    targets = []
    seen_ids = set()
    with open(p, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            chat_id_str = row.get("chat_id", "").strip()
            if not chat_id_str or chat_id_str in seen_ids:
                continue
            seen_ids.add(chat_id_str)
            targets.append({
                "chat_id": chat_id_str,
                "title": row.get("title", ""),
                "username": row.get("username", ""),
                "type": row.get("type", ""),
                "role": row.get("role", "MEMBER"),
                "members_count": row.get("members_count", 0),
                "can_send_messages": row.get("can_send_messages", "True")
            })

    if filter_blacklisted:
        targets = GroupBlacklistManager.filter_targets(targets)

    return targets


def _extract_target_info(target: Union[str, Dict[str, Any]]) -> Tuple[str, str]:
    if isinstance(target, dict):
        cid = str(target.get("chat_id", "")).strip()
        title = target.get("title", "").strip() or target.get("username", "").strip()
        display = f"{title} [{cid}]" if title and title != cid else cid
        return cid, display
    else:
        cid = str(target).strip()
        return cid, cid


class BroadcasterModule:
    """Message broadcast and announcement manager with Telegram Anti-Ban Protections."""

    def __init__(self, client: Client):
        self.client = client

    @handle_flood_wait(max_retries=3)
    async def _send_single(self, target: str, text: str, media_path: Optional[str] = None) -> bool:
        chat_target = int(target) if (target.startswith("-") and target[1:].isdigit()) or target.isdigit() else target
        if media_path:
            msg = await self.client.send_photo(chat_id=chat_target, photo=media_path, caption=text)
        else:
            msg = await self.client.send_message(chat_id=chat_target, text=text)
        
        if msg and hasattr(msg, "id"):
            SentPostTracker.log_sent_post(
                chat_id=target,
                message_id=msg.id,
                title=getattr(msg.chat, "title", target),
                username=getattr(msg.chat, "username", ""),
                send_type="custom_text"
            )
        return True

    @handle_flood_wait(max_retries=3)
    async def _forward_single_post(
        self,
        target: str,
        from_chat: Union[str, int],
        message_id: int,
        copy_mode: bool = False,
        post_url: str = ""
    ) -> bool:
        chat_target = int(target) if (target.startswith("-") and target[1:].isdigit()) or target.isdigit() else target
        if copy_mode:
            msg = await self.client.copy_message(
                chat_id=chat_target,
                from_chat_id=from_chat,
                message_id=message_id
            )
        else:
            fwd_msgs = await self.client.forward_messages(
                chat_id=chat_target,
                from_chat_id=from_chat,
                message_ids=message_id
            )
            msg = fwd_msgs[0] if isinstance(fwd_msgs, list) and fwd_msgs else fwd_msgs

        if msg and hasattr(msg, "id"):
            SentPostTracker.log_sent_post(
                chat_id=target,
                message_id=msg.id,
                title=getattr(msg.chat, "title", target),
                username=getattr(msg.chat, "username", ""),
                post_url=post_url,
                send_type="copy" if copy_mode else "forward"
            )
        return True

    def _resolve_safety_params(
        self,
        safety_preset: Optional[str],
        min_delay: Optional[float],
        max_delay: Optional[float]
    ) -> Tuple[float, float, int, float]:
        """Determine effective min_delay, max_delay, pause_every, pause_duration."""
        preset = SAFETY_PRESETS.get(safety_preset or "balanced", SAFETY_PRESETS["balanced"])
        eff_min = min_delay if min_delay is not None else preset["min_delay"]
        eff_max = max_delay if max_delay is not None else preset["max_delay"]
        pause_every = preset["pause_every"]
        pause_duration = preset["pause_duration"]
        return eff_min, eff_max, pause_every, pause_duration

    async def broadcast(
        self,
        targets: List[Union[str, Dict[str, Any]]],
        text: str,
        media_path: Optional[str] = None,
        min_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        safety_preset: Optional[str] = "balanced",
        max_batch_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str, bool, str, str], None]] = None
    ) -> Dict[str, Any]:
        """Broadcast a message to a list of targets with anti-ban protections."""
        eff_targets = targets[:max_batch_size] if max_batch_size and max_batch_size > 0 else targets
        total = len(eff_targets)
        successful = 0
        failed = 0
        results = []

        eff_min, eff_max, pause_every, pause_duration = self._resolve_safety_params(safety_preset, min_delay, max_delay)

        logger.info(f"Starting broadcast campaign to {total} targets (Safety Preset: {safety_preset}, Delays: {eff_min}s-{eff_max}s)...")

        for index, target_item in enumerate(eff_targets, start=1):
            target_id, target_display = _extract_target_info(target_item)
            if not target_id:
                continue

            next_display = "End of Queue"
            if index < total:
                _, next_display = _extract_target_info(eff_targets[index])

            success = False
            error_msg = ""
            try:
                await self._send_single(target_id, text, media_path)
                success = True
                successful += 1
                logger.info(f"[{index}/{total}] Delivered to '{target_display}' | Next: '{next_display}'")
            except Exception as e:
                failed += 1
                error_msg = str(e)
                logger.error(f"[{index}/{total}] Failed delivery to '{target_display}': {e}")
                err_str = error_msg.lower()
                if any(k in err_str for k in ["forbidden", "banned", "kicked", "restricted", "private", "not a member", "permission", "cannot send"]):
                    GroupBlacklistManager.blacklist_group(
                        chat_id=target_id,
                        title=target_display,
                        reason=f"AUTO_BLACKLIST: {type(e).__name__} ({e})"
                    )

            results.append({
                "target": target_id,
                "display": target_display,
                "status": "success" if success else "failed",
                "error": error_msg
            })

            if progress_callback:
                progress_callback(index, total, target_display, success, error_msg, next_display)

            if index < total:
                # Anti-ban mandatory rest pause
                if index % pause_every == 0:
                    logger.info(f"🛡️ [ANTI-BAN PAUSE] Rest pause active after {index} messages. Sleeping for {pause_duration}s... Next target: '{next_display}'")
                    if progress_callback:
                        progress_callback(index, total, f"REST_PAUSE ({pause_duration}s)", True, f"Anti-Ban Rest Pause ({pause_duration}s)", next_display)
                    await asyncio.sleep(pause_duration)
                else:
                    await human_delay(eff_min, eff_max)

        logger.info(f"Broadcast campaign completed. Sent: {successful}/{total}, Failed: {failed}")
        return {
            "total": total,
            "successful": successful,
            "failed": failed,
            "details": results
        }

    async def broadcast_post(
        self,
        targets: List[Union[str, Dict[str, Any]]],
        post_url: str,
        copy_mode: bool = False,
        min_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        safety_preset: Optional[str] = "balanced",
        max_batch_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str, bool, str, str], None]] = None
    ) -> Dict[str, Any]:
        """Forward or copy a specific Telegram post URL with Anti-Ban rules."""
        from_chat, message_id = parse_telegram_post_url(post_url)
        if not from_chat or not message_id:
            raise ValueError(f"Invalid Telegram post URL: '{post_url}'. Expected format like 'https://t.me/channel/123'")

        eff_targets = targets[:max_batch_size] if max_batch_size and max_batch_size > 0 else targets
        total = len(eff_targets)
        successful = 0
        failed = 0
        results = []

        eff_min, eff_max, pause_every, pause_duration = self._resolve_safety_params(safety_preset, min_delay, max_delay)

        logger.info(f"Starting post forward campaign ({post_url}) to {total} targets (Safety Preset: {safety_preset}, Delays: {eff_min}s-{eff_max}s)...")

        for index, target_item in enumerate(eff_targets, start=1):
            target_id, target_display = _extract_target_info(target_item)
            if not target_id:
                continue

            next_display = "End of Queue"
            if index < total:
                _, next_display = _extract_target_info(eff_targets[index])

            success = False
            error_msg = ""
            try:
                await self._forward_single_post(
                    target=target_id,
                    from_chat=from_chat,
                    message_id=message_id,
                    copy_mode=copy_mode,
                    post_url=post_url
                )
                success = True
                successful += 1
                logger.info(f"[{index}/{total}] Post sent to '{target_display}' | Next: '{next_display}'")
            except Exception as e:
                failed += 1
                error_msg = str(e)
                logger.error(f"[{index}/{total}] Post send failed to '{target_display}': {e}")
                err_str = error_msg.lower()
                if any(k in err_str for k in ["forbidden", "banned", "kicked", "restricted", "private", "not a member", "permission", "cannot send"]):
                    GroupBlacklistManager.blacklist_group(
                        chat_id=target_id,
                        title=target_display,
                        reason=f"AUTO_BLACKLIST: {type(e).__name__} ({e})"
                    )

            results.append({
                "target": target_id,
                "display": target_display,
                "status": "success" if success else "failed",
                "error": error_msg
            })

            if progress_callback:
                progress_callback(index, total, target_display, success, error_msg, next_display)

            if index < total:
                # Anti-ban mandatory rest pause
                if index % pause_every == 0:
                    logger.info(f"🛡️ [ANTI-BAN PAUSE] Rest pause active after {index} posts. Sleeping for {pause_duration}s... Next target: '{next_display}'")
                    if progress_callback:
                        progress_callback(index, total, f"REST_PAUSE ({pause_duration}s)", True, f"Anti-Ban Rest Pause ({pause_duration}s)", next_display)
                    await asyncio.sleep(pause_duration)
                else:
                    await human_delay(eff_min, eff_max)

        logger.info(f"Post forward campaign completed. Sent: {successful}/{total}, Failed: {failed}")
        return {
            "total": total,
            "successful": successful,
            "failed": failed,
            "details": results
        }

    async def continuous_broadcast(
        self,
        targets_source: Union[List[Union[str, Dict[str, Any]]], str, Path],
        post_url: Optional[str] = None,
        text: Optional[str] = None,
        media_path: Optional[str] = None,
        copy_mode: bool = False,
        min_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        safety_preset: Optional[str] = "ultra_safe",
        min_interval_minutes: float = 5.0,
        max_interval_minutes: float = 10.0,
        max_batch_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, int, str, bool, str, str], None]] = None,
        stop_event: Optional[asyncio.Event] = None
    ) -> Dict[str, Any]:
        """
        Continuously broadcast messages/posts to target groups every X minutes without stopping,
        obeying all Telegram anti-ban safety guidelines, flood wait restrictions, and group health rules.
        """
        round_num = 0
        total_successful_all_rounds = 0
        total_failed_all_rounds = 0

        logger.info(f"🔁 Initializing Continuous Auto-Send Campaign (Interval: {min_interval_minutes}-{max_interval_minutes} mins, Safety: {safety_preset})...")

        while True:
            if stop_event and stop_event.is_set():
                logger.info("🛑 Continuous broadcast campaign stopped by user request.")
                break

            round_num += 1
            logger.info(f"🚀 Starting Continuous Broadcast Round #{round_num}...")

            # Load/Refresh targets for current round
            if isinstance(targets_source, (str, Path)):
                current_targets = load_targets_from_csv(targets_source, filter_blacklisted=True)
            elif isinstance(targets_source, list):
                current_targets = GroupBlacklistManager.filter_targets(targets_source)
            else:
                current_targets = []

            if not current_targets:
                logger.warning(f"⚠️ No active non-blacklisted targets available for Round #{round_num}. Waiting for next cycle...")
            else:
                def round_cb(current, total, target_disp, success, err, next_disp="End of Queue"):
                    if progress_callback:
                        progress_callback(round_num, current, total, target_disp, success, err, next_disp)

                if post_url:
                    summary = await self.broadcast_post(
                        targets=current_targets,
                        post_url=post_url,
                        copy_mode=copy_mode,
                        min_delay=min_delay,
                        max_delay=max_delay,
                        safety_preset=safety_preset,
                        max_batch_size=max_batch_size,
                        progress_callback=round_cb
                    )
                else:
                    summary = await self.broadcast(
                        targets=current_targets,
                        text=text or "",
                        media_path=media_path,
                        min_delay=min_delay,
                        max_delay=max_delay,
                        safety_preset=safety_preset,
                        max_batch_size=max_batch_size,
                        progress_callback=round_cb
                    )

                total_successful_all_rounds += summary.get("successful", 0)
                total_failed_all_rounds += summary.get("failed", 0)

            if stop_event and stop_event.is_set():
                logger.info("🛑 Continuous broadcast campaign cancelled after round execution.")
                break

            # Calculate randomized sleep interval between 5 and 10 minutes (or user specified)
            low_sec = max(30.0, min_interval_minutes * 60.0)
            high_sec = max(low_sec, max_interval_minutes * 60.0)
            wait_seconds = random.uniform(low_sec, high_sec)
            wait_mins_str = f"{wait_seconds / 60.0:.1f}"

            logger.info(f"⏳ Round #{round_num} Complete. Sleeping for {wait_mins_str} mins ({int(wait_seconds)}s) before Round #{round_num + 1}...")

            if progress_callback:
                progress_callback(
                    round_num,
                    len(current_targets),
                    len(current_targets),
                    f"CYCLE_WAIT ({wait_mins_str}m)",
                    True,
                    f"Round #{round_num} Complete. Waiting {wait_mins_str} mins for Round #{round_num + 1}...",
                    f"Round #{round_num + 1}"
                )

            # Interruptible countdown sleep loop
            sleep_step = 1.0
            elapsed = 0.0
            while elapsed < wait_seconds:
                if stop_event and stop_event.is_set():
                    logger.info("🛑 Continuous broadcast campaign stopped during cycle interval.")
                    break
                await asyncio.sleep(sleep_step)
                elapsed += sleep_step

        return {
            "total_rounds": round_num,
            "total_successful": total_successful_all_rounds,
            "total_failed": total_failed_all_rounds
        }





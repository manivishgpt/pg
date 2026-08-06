import re
import logging
from typing import List, Optional
from pyrogram import Client, filters
from pyrogram.types import Message
from core.anti_flood import handle_flood_wait

logger = logging.getLogger(__name__)

class ChannelForwarderRule:
    def __init__(
        self,
        source_chat: str,
        destination_chat: str,
        whitelist_keywords: Optional[List[str]] = None,
        blacklist_keywords: Optional[List[str]] = None,
        remove_links: bool = False,
        custom_header: str = "",
        custom_footer: str = ""
    ):
        self.source_chat = source_chat
        self.destination_chat = destination_chat
        self.whitelist_keywords = whitelist_keywords or []
        self.blacklist_keywords = blacklist_keywords or []
        self.remove_links = remove_links
        self.custom_header = custom_header
        self.custom_footer = custom_footer

class ChannelForwarderModule:
    """Real-time message forwarding and content mirroring between channels."""

    def __init__(self, client: Client, rules: Optional[List[ChannelForwarderRule]] = None):
        self.client = client
        self.rules: List[ChannelForwarderRule] = rules or []

    def add_rule(self, rule: ChannelForwarderRule):
        self.rules.append(rule)

    def _process_text(self, text: str, rule: ChannelForwarderRule) -> str:
        if not text:
            return ""

        processed = text
        if rule.remove_links:
            # Strip URLs
            processed = re.sub(r'https?://\S+|www\.\S+', '', processed)

        if rule.custom_header:
            processed = f"{rule.custom_header}\n\n{processed}"
        if rule.custom_footer:
            processed = f"{processed}\n\n{rule.custom_footer}"

        return processed.strip()

    def _should_forward(self, text: str, rule: ChannelForwarderRule) -> bool:
        lower_text = text.lower() if text else ""

        # Check blacklist
        for bl in rule.blacklist_keywords:
            if bl.lower() in lower_text:
                return False

        # Check whitelist if specified
        if rule.whitelist_keywords:
            matched = False
            for wl in rule.whitelist_keywords:
                if wl.lower() in lower_text:
                    matched = True
                    break
            if not matched:
                return False

        return True

    def start(self):
        """Start listening for messages in source channels."""
        for rule in self.rules:
            self._register_rule(rule)
        logger.info(f"Channel Forwarder started with {len(self.rules)} rules.")

    def _register_rule(self, rule: ChannelForwarderRule):
        @self.client.on_message(filters.chat(rule.source_chat))
        async def message_handler(client: Client, message: Message):
            original_text = message.text or message.caption or ""

            if not self._should_forward(original_text, rule):
                logger.debug("Message skipped based on forwarder keyword rules.")
                return

            processed_text = self._process_text(original_text, rule)

            @handle_flood_wait()
            async def execute_forward():
                if rule.custom_header or rule.custom_footer or rule.remove_links:
                    # Send modified copy
                    if message.photo:
                        await client.send_photo(
                            chat_id=rule.destination_chat,
                            photo=message.photo.file_id,
                            caption=processed_text
                        )
                    elif message.video:
                        await client.send_video(
                            chat_id=rule.destination_chat,
                            video=message.video.file_id,
                            caption=processed_text
                        )
                    elif message.document:
                        await client.send_document(
                            chat_id=rule.destination_chat,
                            document=message.document.file_id,
                            caption=processed_text
                        )
                    else:
                        await client.send_message(
                            chat_id=rule.destination_chat,
                            text=processed_text
                        )
                else:
                    # Native forward
                    await message.forward(chat_id=rule.destination_chat)

            try:
                await execute_forward()
                logger.info(f"Forwarded message from {rule.source_chat} -> {rule.destination_chat}")
            except Exception as e:
                logger.error(f"Error forwarding message: {e}")

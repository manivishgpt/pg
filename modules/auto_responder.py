import re
import json
import logging
import urllib.request
import asyncio
from typing import List, Dict, Any, Optional
from pyrogram import Client, filters
from pyrogram.enums import ChatAction, ChatType
from pyrogram.types import Message
from pyrogram.handlers import MessageHandler
from core.anti_flood import human_delay, handle_flood_wait

logger = logging.getLogger(__name__)

# Global in-memory chat conversation history store (chat_id -> list of message objects)
CHAT_HISTORIES: Dict[int, List[Dict[str, str]]] = {}

def clear_chat_memories():
    """Clear all cached conversation histories to wipe old prompt memories."""
    CHAT_HISTORIES.clear()
    logger.info("All chat conversation memories have been reset.")

def build_default_prompt(owner_name: str, owner_username: str, sender_name: str, sender_username: str) -> str:
    """Build crystal clear identity system prompt for LLMs."""
    owner_str = f"{owner_name} {owner_username}".strip()
    sender_str = f"{sender_name} {sender_username}".strip()

    return f"""YOU ARE AN AI ASSISTANT REPRESENTING: {owner_str}.

STRICT IDENTITY RULES:
1. YOUR IDENTITY (Who you are):
   - Your name/identity is {owner_str}. You are the personal AI assistant for {owner_str}.
   - When asked "who are you?", "who am I talking to?", or "aap kaun ho?", ALWAYS reply: "Main {owner_str} ka AI assistant hoon." or "My name is {owner_str}."
   - NEVER say that the other person is {owner_str}.

2. THE OTHER USER'S IDENTITY (Who you are talking to):
   - You are currently chatting with {sender_str}.
   - When asked "who am I?" or "mera naam kya hai?", reply: "Aapka naam {sender_str} hai."

3. CONVERSATION GUIDELINES:
   - Be helpful, polite, natural, and friendly.
   - Reply in the same language as the user (Hindi, Hinglish, English, etc.).
   - Never mention BlackSMS, customer support, or unrelated websites.
   - Never output <think> tags or reasoning steps."""

def query_ollama_chat_sync(
    chat_id: int,
    user_prompt: str,
    model: str = "qwen2.5:3b",
    system_prompt: Optional[str] = None,
    max_history_turns: int = 12
) -> str:
    """Synchronous HTTP call to Ollama Chat API with per-user conversation memory."""
    url = "http://localhost:11434/api/chat"
    sys_content = system_prompt or build_default_prompt("Account Owner", "", "User", "")

    # Get or initialize history for this chat_id
    history = CHAT_HISTORIES.get(chat_id, [])

    # Construct full message payload
    messages_payload = [{"role": "system", "content": sys_content}]
    # Append recent history turns
    messages_payload.extend(history[-max_history_turns:])
    # Append current user prompt
    messages_payload.append({"role": "user", "content": user_prompt})

    payload = {
        "model": model,
        "messages": messages_payload,
        "stream": False
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        logger.debug(f"Requesting reply from '{model}' for chat {chat_id}...")
        with urllib.request.urlopen(req, timeout=35) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            ai_reply = res_data.get("message", {}).get("content", "").strip()

            if ai_reply:
                # Update memory for this chat
                history.append({"role": "user", "content": user_prompt})
                history.append({"role": "assistant", "content": ai_reply})
                CHAT_HISTORIES[chat_id] = history[-max_history_turns:]
                logger.info(f"Ollama reply generated for chat {chat_id}: {ai_reply[:50]}...")

            return ai_reply or "I got your message."
    except Exception as e:
        logger.error(f"Error querying Ollama API with memory ({model}): {e}")
        return "Sorry, I am currently unable to process your message."

async def query_ollama_ai_with_memory(
    chat_id: int,
    prompt: str,
    model: str = "qwen2.5:3b",
    system_prompt: Optional[str] = None
) -> str:
    """Async wrapper for querying local Ollama model with per-chat memory."""
    return await asyncio.to_thread(query_ollama_chat_sync, chat_id, prompt, model, system_prompt)

class AutoResponderRule:
    def __init__(
        self,
        keywords: List[str],
        response_text: str = "",
        match_type: str = "contains",  # "contains", "exact", "regex", "all"
        private_only: bool = True,
        simulate_typing: bool = True,
        use_ai: bool = False,
        ai_model: str = "qwen2.5:3b",
        ai_system_prompt: Optional[str] = None
    ):
        self.keywords = keywords
        self.response_text = response_text
        self.match_type = match_type
        self.private_only = private_only
        self.simulate_typing = simulate_typing
        self.use_ai = use_ai
        self.ai_model = ai_model
        self.ai_system_prompt = ai_system_prompt

    def matches(self, text: str) -> bool:
        if self.match_type == "all" or "*" in self.keywords:
            return True

        if not text:
            return False

        lower_text = text.lower()
        for kw in self.keywords:
            kw_lower = kw.lower()
            if self.match_type == "exact" and lower_text == kw_lower:
                return True
            elif self.match_type == "contains" and kw_lower in lower_text:
                return True
            elif self.match_type == "regex":
                try:
                    if re.search(kw, text, re.IGNORECASE):
                        return True
                except re.error:
                    pass
        return False

class AutoResponderModule:
    """Automated message reply engine with Ollama AI memory integration."""

    def __init__(
        self,
        client: Client,
        rules: Optional[List[AutoResponderRule]] = None,
        ai_mode_global: bool = False,
        global_ai_model: str = "qwen2.5:3b"
    ):
        self.client = client
        self.rules: List[AutoResponderRule] = rules or []
        self.ai_mode_global = ai_mode_global
        self.global_ai_model = global_ai_model
        self._handler_ref = None
        # Always clear old prompt memories when starting fresh responder instance
        clear_chat_memories()

    def add_rule(self, rule: AutoResponderRule):
        self.rules.append(rule)

    async def _on_message(self, client: Client, message: Message):
        # Ignore own messages
        if message.from_user and message.from_user.is_self:
            return

        text = message.text or message.caption or ""
        chat_type_str = str(message.chat.type)
        is_private = chat_type_str.lower().endswith("private") or message.chat.type == ChatType.PRIVATE
        chat_id = message.chat.id

        # Account Owner (Our) details
        me = client.me or await client.get_me()
        owner_first = me.first_name or ""
        owner_last = f" {me.last_name}" if me.last_name else ""
        owner_name = f"{owner_first}{owner_last}".strip() or "Anshu Web"
        owner_username = f"(@{me.username})" if me.username else ""

        # Sender (User) details
        u = message.from_user
        sender_first = u.first_name if u else (message.chat.first_name or "User")
        sender_last = f" {u.last_name}" if (u and u.last_name) else ""
        sender_name = f"{sender_first}{sender_last}".strip()
        sender_username = f"(@{u.username})" if (u and u.username) else ""

        dynamic_sys_prompt = build_default_prompt(owner_name, owner_username, sender_name, sender_username)

        # Global Ollama AI Mode for all Private Messages
        if self.ai_mode_global and is_private and text:
            logger.info(f"Ollama AI Auto-Responder processing private message from '{sender_name}' (ID: {chat_id})")

            try:
                await client.send_chat_action(chat_id, ChatAction.TYPING)
            except Exception:
                pass

            ai_reply = await query_ollama_ai_with_memory(
                chat_id,
                text,
                model=self.global_ai_model,
                system_prompt=dynamic_sys_prompt
            )
            await human_delay(1.0, 2.5)

            @handle_flood_wait()
            async def send_ai_reply():
                await message.reply_text(ai_reply)

            try:
                await send_ai_reply()
                logger.info(f"Ollama AI reply sent to {sender_name}")
            except Exception as e:
                logger.error(f"Failed to send Ollama AI reply: {e}")
            return

        # Rule-based matching
        for rule in self.rules:
            if rule.private_only and not is_private:
                continue

            if rule.matches(text):
                logger.info(f"Auto-responder rule triggered for chat '{message.chat.title or sender_name}'")

                if rule.simulate_typing:
                    try:
                        await client.send_chat_action(chat_id, ChatAction.TYPING)
                        await human_delay(1.5, 3.0)
                    except Exception as e:
                        logger.warning(f"Failed to send typing action: {e}")

                # Determine response text (Static or Ollama AI Memory)
                if rule.use_ai:
                    reply_content = await query_ollama_ai_with_memory(
                        chat_id,
                        text,
                        model=rule.ai_model,
                        system_prompt=rule.ai_system_prompt or dynamic_sys_prompt
                    )
                else:
                    reply_content = rule.response_text

                @handle_flood_wait()
                async def send_reply():
                    await message.reply_text(reply_content)

                try:
                    await send_reply()
                    logger.info("Auto-reply sent successfully.")
                except Exception as e:
                    logger.error(f"Error sending auto-reply: {e}")
                break

    def start(self):
        """Register Pyrogram message handler dynamically."""
        handler = MessageHandler(self._on_message, filters.incoming & ~filters.me)
        self.client.add_handler(handler)
        self._handler_ref = handler
        logger.info(f"Auto-responder module with Chat Memory activated (Global AI Mode: {self.ai_mode_global}, Model: {self.global_ai_model}).")

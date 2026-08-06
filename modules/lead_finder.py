import csv
import json
import logging
import urllib.request
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from pyrogram import Client
from pyrogram.enums import ChatType
from config import settings
from core.anti_flood import handle_flood_wait

logger = logging.getLogger(__name__)

LEAD_QUALIFIER_SYSTEM_PROMPT = """You are an AI Lead Classifier specializing in identifying prospective buyers who NEED SMS services.

TASK:
Analyze the given message text and classify the sender into ONE of three categories:
1. "BUYER": The user is explicitly asking to BUY, NEED, or FIND OTP SMS, OTP API, Bulk SMS, or virtual numbers for their website/app (e.g. "I need OTP API for my website", "Looking for Bulk SMS provider", "Need SMS gateway").
2. "PROVIDER": The user is SELLING, ADVERTISING, or PROVIDING SMS, OTP, or USDT services (e.g. "We sell OTP API", "Contact us for Bulk SMS", "Best rate OTP service").
3. "IRRELEVANT": The message is unrelated to buying SMS/OTP services.

CRITICAL RULE:
- ONLY classify as "BUYER" if they are a potential CLIENT/BUYER needing the service.
- If they are a PROVIDER or SELLER, classify as "PROVIDER".

OUTPUT FORMAT:
Return ONLY a valid JSON object with no additional text:
{"category": "BUYER" | "PROVIDER" | "IRRELEVANT", "reason": "<short explanation>"}"""

def classify_message_with_ollama_sync(text: str, model: str = "qwen2.5:3b") -> Dict[str, Any]:
    """Use local Ollama model to classify if a message is from a genuine buyer needing SMS/OTP services."""
    url = "http://localhost:11434/api/chat"
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": LEAD_QUALIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Message to analyze: \"{text}\""}
        ],
        "stream": False,
        "format": "json"
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data.get("message", {}).get("content", "").strip()
            parsed = json.loads(content)
            return parsed
    except Exception as e:
        logger.error(f"Error classifying message via Ollama: {e}")
        return {"category": "IRRELEVANT", "reason": str(e)}

async def classify_message_ai(text: str, model: str = "qwen2.5:3b") -> Dict[str, Any]:
    """Async wrapper for Ollama lead classification."""
    return await asyncio.to_thread(classify_message_with_ollama_sync, text, model)

class TelegramLeadFinderModule:
    """Module to scan groups/chats and extract buyers needing OTP SMS, OTP API, or Bulk SMS services."""

    def __init__(self, client: Client, output_dir: Optional[Path] = None):
        self.client = client
        self.output_dir = output_dir or settings.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @handle_flood_wait()
    async def find_sms_buyers(
        self,
        chat_id: str,
        limit: int = 500,
        ai_model: str = "qwen2.5:3b"
    ) -> List[Dict[str, Any]]:
        """Scan messages in a group/channel and filter ONLY genuine buyers using Ollama AI."""
        qualified_leads = []
        logger.info(f"Scanning chat '{chat_id}' for OTP/Bulk SMS buyers (limit: {limit})...")

        keywords = ["otp", "sms", "api", "bulk", "gateway", "verification", "number", "virtual", "need", "looking for", "buy"]

        async for msg in self.client.get_chat_history(chat_id, limit=limit):
            text = msg.text or msg.caption or ""
            if not text or len(text) < 5:
                continue

            lower_text = text.lower()
            # Fast keyword pre-filter before calling LLM
            if not any(kw in lower_text for kw in keywords):
                continue

            user = msg.from_user
            if not user or user.is_bot:
                continue

            # Classify message using Ollama AI
            result = await classify_message_ai(text, model=ai_model)

            if result.get("category") == "BUYER":
                lead_data = {
                    "user_id": user.id,
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                    "username": f"@{user.username}" if user.username else "",
                    "message_snippet": text[:200],
                    "ai_reason": result.get("reason", ""),
                    "message_id": msg.id,
                    "date": msg.date.isoformat() if msg.date else ""
                }
                qualified_leads.append(lead_data)
                logger.info(f"[BUYER FOUND] {lead_data['first_name']} ({lead_data['username']}): {text[:60]}...")

        logger.info(f"Scan complete. Found {len(qualified_leads)} qualified buyers.")
        return qualified_leads

    @handle_flood_wait()
    async def find_buyers_in_all_joined_groups(
        self,
        per_group_limit: int = 200,
        ai_model: str = "qwen2.5:3b"
    ) -> List[Dict[str, Any]]:
        """Scan ALL joined groups and supergroups of the account for genuine OTP/Bulk SMS buyers."""
        all_leads = []
        logger.info("Scanning ALL joined groups and supergroups for SMS/OTP buyers...")

        async for dialog in self.client.get_dialogs():
            chat = dialog.chat
            if str(chat.type) in ["ChatType.GROUP", "ChatType.SUPERGROUP"]:
                logger.info(f"Scanning joined group '{chat.title}' (ID: {chat.id})...")
                try:
                    leads = await self.find_sms_buyers(chat.id, limit=per_group_limit, ai_model=ai_model)
                    for lead in leads:
                        lead["source_group"] = chat.title or str(chat.id)
                    all_leads.extend(leads)
                except Exception as e:
                    logger.warning(f"Could not scan group '{chat.title}': {e}")

        logger.info(f"All joined groups scan complete. Total qualified buyers found: {len(all_leads)}")
        return all_leads

    def export_to_csv(self, data: List[Dict[str, Any]], filename: str = "otp_sms_buyers.csv") -> Path:
        """Export qualified leads to CSV file."""
        if not filename.endswith('.csv'):
            filename += '.csv'
        filepath = self.output_dir / filename

        if not data:
            logger.warning("No lead data to export to CSV.")
            return filepath

        fieldnames = list(data[0].keys())
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

        logger.info(f"Leads exported to CSV: {filepath}")
        return filepath

    def export_to_json(self, data: List[Dict[str, Any]], filename: str = "otp_sms_buyers.json") -> Path:
        """Export qualified leads to JSON file."""
        if not filename.endswith('.json'):
            filename += '.json'
        filepath = self.output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Leads exported to JSON: {filepath}")
        return filepath

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

class Settings:
    def __init__(self):
        self.api_id: int = int(os.getenv("TELEGRAM_API_ID", "0"))
        self.api_hash: str = os.getenv("TELEGRAM_API_HASH", "")
        self.min_delay: float = float(os.getenv("MIN_ACTION_DELAY", "3.0"))
        self.max_delay: float = float(os.getenv("MAX_ACTION_DELAY", "8.0"))
        self.default_proxy: Optional[str] = os.getenv("DEFAULT_PROXY", None)
        self.sessions_dir: Path = BASE_DIR / os.getenv("SESSIONS_DIR", "sessions")
        self.output_dir: Path = BASE_DIR / os.getenv("OUTPUT_DIR", "output")

        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def parse_proxy(self, proxy_str: Optional[str] = None):
        """Parse proxy URL into Pyrogram compatible dictionary format."""
        target = proxy_str or self.default_proxy
        if not target:
            return None
        
        try:
            from urllib.parse import urlparse
            parsed = urlparse(target)
            scheme = parsed.scheme.lower()
            
            scheme_map = {
                "socks5": "socks5",
                "socks4": "socks4",
                "http": "http",
                "https": "http"
            }
            
            if scheme not in scheme_map:
                return None
                
            proxy_dict = {
                "scheme": scheme_map[scheme],
                "hostname": parsed.hostname,
                "port": parsed.port or 1080
            }
            
            if parsed.username:
                proxy_dict["username"] = parsed.username
            if parsed.password:
                proxy_dict["password"] = parsed.password
                
            return proxy_dict
        except Exception:
            return None

settings = Settings()

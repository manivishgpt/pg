import sys
import io
import asyncio
import logging
from pathlib import Path

# Force UTF-8 output encoding for Windows terminal
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.session_manager import SessionManager
from modules.broadcaster import BroadcasterModule, load_targets_from_csv
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("WritableForwardScript")

async def main():
    post_url = "https://t.me/gatewaydeveloper/1085"
    csv_file = settings.output_dir / "writable_groups.csv"

    print("=" * 70)
    print(" 🛡️ TELEGRAM ANTI-BAN 1-CLICK POST FORWARDER (writable_groups.csv)")
    print("=" * 70)
    print(f"Post URL: {post_url}")
    print(f"Targets Source CSV: {csv_file}")
    
    # 1. Load targets from CSV
    targets_data = load_targets_from_csv(csv_file)
    if not targets_data:
        print(f"Error: No targets found in {csv_file}")
        return

    chat_ids = [t["chat_id"] for t in targets_data]
    print(f"Loaded {len(chat_ids)} total writable groups.")
    
    # Test batch size of 5 groups for verification
    max_batch = 5
    print(f"Running safe test batch of {max_batch} groups with Ultra-Safe anti-ban rules (Copy mode)...")
    print("-" * 70)

    # 2. Start Session
    session_mgr = SessionManager()
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        print("Error: No active sessions found in sessions directory.")
        return

    sname = "blacksms" if "blacksms" in sessions else sessions[0]
    print(f"Connecting to session: '{sname}'...")
    
    try:
        client = await session_mgr.start_session(sname)
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} (@{me.username or 'NoUsername'}) [ID: {me.id}]")
        print("-" * 70)

        broadcaster = BroadcasterModule(client)

        def progress_cb(current, total, target, success, err):
            if "REST_PAUSE" in target:
                print(f" 🛡️ [ANTI-BAN PAUSE] Rest pause active: {err}")
            else:
                status = "SUCCESS" if success else f"FAILED ({err})"
                print(f" [{current}/{total}] {status} -> Target Chat: {target}")

        print("Starting broadcast campaign...")
        summary = await broadcaster.broadcast_post(
            targets=chat_ids,
            post_url=post_url,
            copy_mode=True, # Copy mode recommended for public groups
            safety_preset="ultra_safe",
            max_batch_size=max_batch,
            progress_callback=progress_cb
        )

        print("=" * 70)
        print(" CAMPAIGN COMPLETED SUMMARY")
        print("=" * 70)
        print(f" Total Targets Processed : {summary['total']}")
        print(f" Successful Deliveries  : {summary['successful']}")
        print(f" Failed / Restricted    : {summary['failed']}")
        print("=" * 70)

    except Exception as e:
        logger.exception("Error executing writable groups post forward campaign")
        print(f"Execution failed: {e}")
    finally:
        await session_mgr.stop_all()

if __name__ == "__main__":
    asyncio.run(main())

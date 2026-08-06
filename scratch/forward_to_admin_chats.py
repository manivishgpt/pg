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
logger = logging.getLogger("ForwardScript")

async def main():
    post_url = "https://t.me/gatewaydeveloper/1085"
    csv_file = settings.output_dir / "my_admin_chats.csv"

    print("=" * 60)
    print(" [1-CLICK TELEGRAM POST FORWARDER]")
    print("=" * 60)
    print(f"Post URL: {post_url}")
    print(f"Targets Source CSV: {csv_file}")
    
    # 1. Load targets from CSV
    targets_data = load_targets_from_csv(csv_file)
    if not targets_data:
        print(f"Error: No targets found in {csv_file}")
        return

    chat_ids = [t["chat_id"] for t in targets_data]
    print(f"Loaded {len(chat_ids)} unique target admin groups/channels:")
    for t in targets_data:
        print(f" - [{t['type']}] {t['title']} (ID: {t['chat_id']}, Role: {t['role']})")
    print("-" * 60)

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
        print("-" * 60)

        broadcaster = BroadcasterModule(client)

        def progress_cb(current, total, target, success):
            status = "SUCCESS" if success else "FAILED"
            print(f" [{current}/{total}] {status} -> Target Chat: {target}")

        print("Starting broadcast campaign...")
        summary = await broadcaster.broadcast_post(
            targets=chat_ids,
            post_url=post_url,
            copy_mode=False, # Native forward
            min_delay=3.0,
            max_delay=6.0,
            progress_callback=progress_cb
        )

        print("=" * 60)
        print(" CAMPAIGN COMPLETED SUMMARY")
        print("=" * 60)
        print(f" Total Targets : {summary['total']}")
        print(f" Successful    : {summary['successful']}")
        print(f" Failed        : {summary['failed']}")
        print("=" * 60)

    except Exception as e:
        logger.exception("Error executing post forward campaign")
        print(f"Execution failed: {e}")
    finally:
        await session_mgr.stop_all()

if __name__ == "__main__":
    asyncio.run(main())


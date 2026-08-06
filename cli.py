import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import print as rprint

from config import settings
from core.session_manager import SessionManager
from modules.auto_responder import AutoResponderModule, AutoResponderRule
from modules.broadcaster import BroadcasterModule, load_targets_from_csv
from modules.forwarder import ChannelForwarderModule, ChannelForwarderRule
from modules.scraper import TelegramScraperModule

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("telegram_automation.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("CLI")

console = Console()

def display_banner():
    console.clear()
    banner_text = (
        "[bold cyan]====================================================[/bold cyan]\n"
        "[bold magenta]    PYTHON TELEGRAM ACCOUNT AUTOMATION SYSTEM      [/bold magenta]\n"
        "[bold cyan]====================================================[/bold cyan]\n"
        "[dim]Powered by Pyrogram, AsyncIO & Rich CLI[/dim]"
    )
    console.print(Panel(banner_text, expand=False))

def ensure_credentials() -> bool:
    if not settings.api_id or not settings.api_hash:
        console.print("\n[bold yellow]API Credentials Missing![/bold yellow]")
        console.print("Obtain API_ID and API_HASH from [link=https://my.telegram.org]my.telegram.org[/link].\n")
        
        api_id_inp = Prompt.ask("Enter TELEGRAM_API_ID")
        api_hash_inp = Prompt.ask("Enter TELEGRAM_API_HASH")

        if not api_id_inp or not api_hash_inp:
            console.print("[red]API Credentials cannot be empty. Exiting...[/red]")
            return False

        # Save to .env
        env_path = Path(__file__).resolve().parent / ".env"
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"TELEGRAM_API_ID={api_id_inp}\n")
            f.write(f"TELEGRAM_API_HASH={api_hash_inp}\n")
            f.write("MIN_ACTION_DELAY=3.0\n")
            f.write("MAX_ACTION_DELAY=8.0\n")

        settings.api_id = int(api_id_inp)
        settings.api_hash = api_hash_inp
        console.print("[green]Credentials saved to .env successfully![/green]\n")
    return True

async def account_manager_menu(session_mgr: SessionManager):
    while True:
        console.print("\n[bold green]-- Account & Session Manager --[/bold green]")
        sessions = session_mgr.get_existing_sessions()
        
        table = Table(title="Available Sessions")
        table.add_column("Index", style="cyan", justify="center")
        table.add_column("Session Name", style="bold white")
        table.add_column("Status", style="yellow")

        for idx, sname in enumerate(sessions, start=1):
            is_active = "Active" if sname in session_mgr.active_clients else "Offline"
            table.add_row(str(idx), sname, is_active)

        console.print(table)
        console.print("1. Login / Add New Account Session")
        console.print("2. Test Session Connection")
        console.print("3. Back to Main Menu")

        choice = Prompt.ask("Select option", choices=["1", "2", "3"])

        if choice == "1":
            sname = Prompt.ask("Enter session name (e.g. account1)")
            if sname:
                try:
                    with console.status(f"[bold green]Starting login flow for '{sname}'..."):
                        client = await session_mgr.start_session(sname)
                    me = await client.get_me()
                    console.print(f"[bold green]Logged in successfully as {me.first_name} (@{me.username})[/bold green]")
                except Exception as e:
                    console.print(f"[bold red]Login failed: {e}[/bold red]")
        elif choice == "2":
            if not sessions:
                console.print("[yellow]No sessions found. Add one first.[/yellow]")
                continue
            idx_str = Prompt.ask("Select session index", choices=[str(i) for i in range(1, len(sessions) + 1)])
            sname = sessions[int(idx_str) - 1]
            try:
                client = await session_mgr.start_session(sname)
                me = await client.get_me()
                console.print(f"[bold green]Connected: {me.first_name} (@{me.username}) ID: {me.id}[/bold green]")
            except Exception as e:
                console.print(f"[bold red]Session test failed: {e}[/bold red]")
        elif choice == "3":
            break

async def auto_responder_menu(session_mgr: SessionManager):
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        console.print("[red]No account sessions available. Please add an account first.[/red]")
        return

    sname = Prompt.ask("Select session name to attach Auto-Responder", choices=sessions, default=sessions[0])
    client = await session_mgr.start_session(sname)
    
    console.print("\n[bold green]-- Auto-Responder Mode Selection --[/bold green]")
    console.print("1. Ollama AI Auto-Responder (qwen2.5:3b for private chats)")
    console.print("2. Static Keyword / Rule-Based Auto-Responder")
    mode_choice = Prompt.ask("Select mode", choices=["1", "2"], default="1")

    if mode_choice == "1":
        model_name = Prompt.ask("Enter Ollama model name", default="qwen2.5:3b")
        responder = AutoResponderModule(client, ai_mode_global=True, global_ai_model=model_name)
        responder.start()
        console.print(f"[bold green]Ollama AI ({model_name}) Auto-Responder is now ACTIVE for private DMs![/bold green]")
        console.print("[dim]Press Ctrl+C to return to main menu.[/dim]")
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("\n[yellow]Stopping Ollama AI Auto-Responder...[/yellow]")
            return

    responder = AutoResponderModule(client)
    console.print("\n[bold green]-- Configure Static Auto-Responder Rules --[/bold green]")
    while True:
        kw = Prompt.ask("Enter trigger keyword (or press Enter to finish adding rules)", default="")
        if not kw:
            break
        resp_text = Prompt.ask("Enter automated reply message")
        p_only = Confirm.ask("Private chats only?", default=True)
        m_type = Prompt.ask("Match type", choices=["contains", "exact", "regex"], default="contains")
        
        rule = AutoResponderRule(
            keywords=[kw],
            response_text=resp_text,
            match_type=m_type,
            private_only=p_only
        )
        responder.add_rule(rule)
        console.print(f"[green]Rule added for keyword '{kw}'.[/green]")

    if not responder.rules:
        console.print("[yellow]No rules added. Returning to main menu.[/yellow]")
        return

    responder.start()
    console.print("[bold green]Auto-Responder is now ACTIVE and listening in the background...[/bold green]")
    console.print("[dim]Press Ctrl+C to return to main menu (session will remain active).[/dim]")
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]Stopping Auto-Responder listener...[/yellow]")

async def broadcast_menu(session_mgr: SessionManager):
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        console.print("[red]No account sessions available.[/red]")
        return

    sname = Prompt.ask("Select session name for broadcasting", choices=sessions, default=sessions[0])
    client = await session_mgr.start_session(sname)

    broadcaster = BroadcasterModule(client)

    console.print("\n[bold green]-- Broadcast Campaign Launcher --[/bold green]")
    console.print("1. 🔁 Continuous Auto-Send Loop (Send every 5-10 mins continuously across groups) [RECOMMENDED]")
    console.print("2. 1-Click Forward Telegram Post URL (Single Pass)")
    console.print("3. Broadcast Custom Text / Photo Message (Single Pass)")
    bc_type = Prompt.ask("Select broadcast option", choices=["1", "2", "3"], default="1")

    if bc_type == "1":
        console.print("\n[bold cyan]Select Message Type:[/bold cyan]")
        console.print("1. Forward/Copy Telegram Post Link URL")
        console.print("2. Custom Text / Photo Announcement")
        msg_type = Prompt.ask("Select type", choices=["1", "2"], default="1")

        post_url = None
        custom_text = None
        media_path = None
        if msg_type == "1":
            post_url = Prompt.ask("Enter Telegram Post Link URL", default="https://t.me/gatewaydeveloper/1085")
        else:
            custom_text = Prompt.ask("Enter broadcast message text")
            media_inp = Prompt.ask("Optional image file path (press Enter to skip)", default="")
            if media_inp and os.path.exists(media_inp):
                media_path = media_inp

        console.print("\n[bold cyan]Select Target CSV Source:[/bold cyan]")
        console.print("1. active_writable_groups.csv (🔥 Active Continuous Chat Groups) [RECOMMENDED]")
        console.print("2. writable_groups.csv (All Writable Groups)")
        console.print("3. my_admin_chats.csv (Admin/Owner Chats)")
        target_choice = Prompt.ask("Select source", choices=["1", "2", "3"], default="1")
        
        csv_map = {"1": "active_writable_groups.csv", "2": "writable_groups.csv", "3": "my_admin_chats.csv"}
        csv_filename = csv_map[target_choice]
        csv_file = settings.output_dir / csv_filename
        targets_data = load_targets_from_csv(csv_file)
        
        if not targets_data:
            console.print(f"[red]No targets found in {csv_file}. Please run Scraper first.[/red]")
            return

        chat_ids = [t["chat_id"] for t in targets_data]

        min_int = float(Prompt.ask("Enter MIN round interval in minutes", default="5.0"))
        max_int = float(Prompt.ask("Enter MAX round interval in minutes", default="10.0"))

        console.print("\n[bold cyan]Select Anti-Ban Safety Mode:[/bold cyan]")
        console.print("1. 🛡️ Ultra Safe Mode (20-45s delay + 90s rest pause per 8 chats) [RECOMMENDED]")
        console.print("2. ⚖️ Balanced Mode (10-25s delay + 60s rest pause per 10 chats)")
        console.print("3. ⚡ Fast Mode (5-12s delay + 30s rest pause per 15 chats)")
        safety_choice = Prompt.ask("Select mode", choices=["1", "2", "3"], default="1")
        preset_map = {"1": "ultra_safe", "2": "balanced", "3": "fast"}
        safety_preset = preset_map[safety_choice]

        copy_mode = True
        if msg_type == "1":
            copy_mode = Confirm.ask("Use Copy Mode (clean message without forward tag)?", default=True)

        console.print(f"\n[bold yellow]Target Count:[/bold yellow] {len(chat_ids)} chats from '{csv_filename}'")
        console.print(f"[bold yellow]Repeat Interval:[/bold yellow] Every {min_int} to {max_int} minutes continuously")
        console.print(f"[bold yellow]Anti-Ban Safety Preset:[/bold yellow] {safety_preset}")
        console.print("[bold red]Note: Press Ctrl+C at any time to safely stop the continuous campaign loop.[/bold red]\n")

        if not Confirm.ask("Start Continuous Auto-Send campaign now?"):
            return

        stop_evt = asyncio.Event()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Continuous Loop Initializing...", total=len(chat_ids))

            def cb(round_n, current, total, target_disp, success, err, next_disp="End of Queue"):
                progress.update(task, total=total if total > 0 else 1)
                if "CYCLE_WAIT" in target_disp:
                    progress.update(
                        task,
                        completed=total,
                        description=f"[bold yellow]🔄 Round #{round_n} Complete | ⏳ {err} | ⏩ Next: {next_disp}[/bold yellow]"
                    )
                elif "REST_PAUSE" in target_disp:
                    progress.update(
                        task,
                        description=f"[yellow]🛡️ Round #{round_n} Rest Pause ({err}) | ⏩ Next: {next_disp}[/yellow]"
                    )
                else:
                    status_color = "green" if success else "red"
                    progress.update(
                        task,
                        completed=current,
                        description=f"[{status_color}]Round #{round_n} ({current}/{total}): {target_disp}[/{status_color}] | [cyan]⏩ Next: {next_disp}[/cyan]"
                    )

            try:
                summary = await broadcaster.continuous_broadcast(
                    targets_source=csv_file,
                    post_url=post_url,
                    text=custom_text,
                    media_path=media_path,
                    copy_mode=copy_mode,
                    safety_preset=safety_preset,
                    min_interval_minutes=min_int,
                    max_interval_minutes=max_int,
                    progress_callback=cb,
                    stop_event=stop_evt
                )
                console.print(f"\n[bold green]Continuous Campaign Finished![/bold green] Total Rounds Completed: {summary['total_rounds']}, Sent: {summary['total_successful']}, Failed: {summary['total_failed']}")
            except (KeyboardInterrupt, asyncio.CancelledError):
                stop_evt.set()
                console.print("\n[yellow]Continuous broadcast campaign stopped by user interrupt (Ctrl+C).[/yellow]")
        return

    if bc_type == "2":
        post_url = Prompt.ask("Enter Telegram Post Link URL", default="https://t.me/gatewaydeveloper/1085")
        
        console.print("\n[bold cyan]Select Target CSV Source:[/bold cyan]")
        console.print("1. active_writable_groups.csv (🔥 Active Continuous Chat Groups) [RECOMMENDED]")
        console.print("2. writable_groups.csv (All Writable Groups)")
        console.print("3. my_admin_chats.csv (Admin/Owner Chats)")
        target_choice = Prompt.ask("Select source", choices=["1", "2", "3"], default="1")
        
        csv_map = {"1": "active_writable_groups.csv", "2": "writable_groups.csv", "3": "my_admin_chats.csv"}
        csv_filename = csv_map[target_choice]
        csv_file = settings.output_dir / csv_filename
        targets_data = load_targets_from_csv(csv_file)
        
        if not targets_data:
            console.print(f"[red]No targets found in {csv_file}. Please run Scraper first.[/red]")
            return

        chat_ids = [t["chat_id"] for t in targets_data]

        console.print("\n[bold cyan]Select Anti-Ban Safety Mode:[/bold cyan]")
        console.print("1. 🛡️ Ultra Safe Mode (20-45s delay + 90s rest pause per 8 chats) [RECOMMENDED]")
        console.print("2. ⚖️ Balanced Mode (10-25s delay + 60s rest pause per 10 chats)")
        console.print("3. ⚡ Fast Mode (5-12s delay + 30s rest pause per 15 chats)")
        safety_choice = Prompt.ask("Select mode", choices=["1", "2", "3"], default="1")
        preset_map = {"1": "ultra_safe", "2": "balanced", "3": "fast"}
        safety_preset = preset_map[safety_choice]

        batch_inp = IntPrompt.ask(f"Enter Max Batch Limit (1-{len(chat_ids)}, 0 for ALL {len(chat_ids)})", default=0)
        max_batch = batch_inp if batch_inp > 0 else None

        default_copy = True if target_choice == "1" else False
        copy_mode = Confirm.ask("Use Copy Mode (clean message without forward tag - recommended for public groups)?", default=default_copy)

        target_cnt = max_batch if max_batch else len(chat_ids)
        console.print(f"\n[bold yellow]Campaign Target Count:[/bold yellow] {target_cnt} chats from '{csv_filename}'")
        console.print(f"[bold yellow]Anti-Ban Safety Preset:[/bold yellow] {safety_preset}")

        if not Confirm.ask("Start 1-click post forwarding campaign now?"):
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Forwarding Post...", total=target_cnt)

            def cb(current, total, target_disp, success, err, next_disp="End of Queue"):
                if "REST_PAUSE" in target_disp:
                    progress.update(
                        task,
                        description=f"[yellow]🛡️ Rest Pause ({err}) | ⏩ Next: {next_disp}[/yellow]"
                    )
                else:
                    status_color = "green" if success else "red"
                    progress.update(
                        task,
                        completed=current,
                        description=f"[{status_color}]Sent: {target_disp} ({current}/{total})[/{status_color}] | [cyan]⏩ Next: {next_disp}[/cyan]"
                    )

            summary = await broadcaster.broadcast_post(
                targets=targets_data,
                post_url=post_url,
                copy_mode=copy_mode,
                safety_preset=safety_preset,
                max_batch_size=max_batch,
                progress_callback=cb
            )


        console.print(f"\n[bold green]Post Forward Campaign Completed![/bold green] Success: {summary['successful']}, Failed: {summary['failed']}")
        return


    targets_input = Prompt.ask("Enter target usernames/IDs separated by commas (or path to text file)")
    
    targets = []
    if os.path.exists(targets_input):
        with open(targets_input, 'r', encoding='utf-8') as f:
            targets = [line.strip() for line in f if line.strip()]
    else:
        targets = [t.strip() for t in targets_input.split(',') if t.strip()]

    if not targets:
        console.print("[red]No valid targets provided.[/red]")
        return

    msg_text = Prompt.ask("Enter broadcast message text")
    media_path = Prompt.ask("Optional image file path (press Enter to skip)", default="")
    media_path = media_path if media_path and os.path.exists(media_path) else None

    console.print(f"\n[bold yellow]Target Count:[/bold yellow] {len(targets)}")
    if not Confirm.ask("Start campaign now?"):
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Broadcasting...", total=len(targets))

        def cb(current, total, target, success):
            status_color = "green" if success else "red"
            progress.update(
                task,
                completed=current,
                description=f"[{status_color}]Target: {target} ({current}/{total})[/{status_color}]"
            )

        summary = await broadcaster.broadcast(
            targets=targets,
            text=msg_text,
            media_path=media_path,
            progress_callback=cb
        )

    console.print(f"\n[bold green]Campaign Completed![/bold green] Success: {summary['successful']}, Failed: {summary['failed']}")


async def channel_forwarder_menu(session_mgr: SessionManager):
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        console.print("[red]No account sessions available.[/red]")
        return

    sname = Prompt.ask("Select session name for Channel Forwarder", choices=sessions, default=sessions[0])
    client = await session_mgr.start_session(sname)

    forwarder = ChannelForwarderModule(client)

    console.print("\n[bold green]-- Channel Mirror & Forwarder Setup --[/bold green]")
    source = Prompt.ask("Enter source channel username/ID (e.g. @source_chan)")
    destination = Prompt.ask("Enter destination channel username/ID (e.g. @dest_chan)")
    
    rem_links = Confirm.ask("Remove links from forwarded messages?", default=False)
    hdr = Prompt.ask("Optional header text to prepend (press Enter to skip)", default="")
    ftr = Prompt.ask("Optional footer text to append (press Enter to skip)", default="")

    rule = ChannelForwarderRule(
        source_chat=source,
        destination_chat=destination,
        remove_links=rem_links,
        custom_header=hdr,
        custom_footer=ftr
    )
    forwarder.add_rule(rule)
    forwarder.start()

    console.print(f"[bold green]Forwarder ACTIVE: Mirroring {source} -> {destination}[/bold green]")
    console.print("[dim]Press Ctrl+C to return to main menu.[/dim]")
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]Stopping channel forwarder daemon...[/yellow]")

async def scraper_menu(session_mgr: SessionManager):
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        console.print("[red]No account sessions available.[/red]")
        return

    sname = Prompt.ask("Select session for Scraper", choices=sessions, default=sessions[0])
    client = await session_mgr.start_session(sname)

    scraper = TelegramScraperModule(client)

    console.print("\n[bold green]-- Telegram Group & Data Scraper --[/bold green]")
    console.print("1. Scrape Group Members")
    console.print("2. Scrape Message History")
    console.print("3. Find Writable Groups (Groups where sending messages is allowed)")
    console.print("4. Find OTP SMS / API Buyers (AI Lead Qualifier via Ollama qwen2.5:3b)")
    console.print("5. Find My Admin/Owner Groups & Channels")
    console.print("6. 🔥 Find Active Continuous Chatting Groups (Filters high-activity writable groups)")
    choice = Prompt.ask("Select scraping mode", choices=["1", "2", "3", "4", "5", "6"])

    if choice == "6":
        hours = float(Prompt.ask("Enter max message age threshold in hours", default="24.0"))
        with console.status(f"[bold green]Scanning joined dialogs for active continuous chatting groups (Cutoff: {hours}h)..."):
            active_groups = await scraper.find_active_chatting_groups(max_age_hours=hours)
        if active_groups:
            csv_path = scraper.export_to_csv(active_groups, "active_writable_groups.csv")
            json_path = scraper.export_to_json(active_groups, "active_writable_groups.json")
            console.print(f"\n[bold green]Found {len(active_groups)} Active Continuous Chatting Groups![/bold green]")
            
            table = Table(title="🔥 Active Continuous Chatting Groups")
            table.add_column("Chat ID", style="cyan")
            table.add_column("Title", style="bold white")
            table.add_column("Username", style="yellow")
            table.add_column("Recent Msgs (24h)", style="bold green")
            table.add_column("Active Senders", style="bold magenta")
            table.add_column("Last Active", style="dim white")

            for g in active_groups:
                table.add_row(
                    str(g["chat_id"]),
                    g["title"],
                    f"@{g['username']}" if g['username'] else "Private/No Username",
                    str(g["recent_messages_24h"]),
                    str(g["unique_senders_24h"]),
                    g["last_active_time"]
                )
            console.print(table)

            console.print(f"\n[bold green]Exported Active Continuous Groups to:[/bold green]")
            console.print(f" - CSV: [link=file://{csv_path}]{csv_path}[/link]")
            console.print(f" - JSON: [link=file://{json_path}]{json_path}[/link]")
        else:
            console.print("[yellow]No active continuous chatting groups found matching criteria.[/yellow]")
        return

    if choice == "5":
        with console.status("[bold green]Scanning all joined dialogs for Owner/Admin roles..."):
            admin_chats = await scraper.find_my_admin_groups()
        if admin_chats:
            csv_path = scraper.export_to_csv(admin_chats, "my_admin_chats.csv")
            json_path = scraper.export_to_json(admin_chats, "my_admin_chats.json")
            console.print(f"\n[bold green]Found {len(admin_chats)} Groups/Channels where you are Owner/Admin![/bold green]")
            
            table = Table(title="My Admin/Owner Groups & Channels")
            table.add_column("Chat ID", style="cyan")
            table.add_column("Title", style="bold white")
            table.add_column("Username", style="yellow")
            table.add_column("Role", style="bold magenta")
            table.add_column("Type", style="blue")
            table.add_column("Members", style="green")

            for c in admin_chats:
                table.add_row(
                    str(c["chat_id"]),
                    c["title"],
                    f"@{c['username']}" if c["username"] else "Private/No Username",
                    c["role"],
                    c["type"],
                    str(c["members_count"])
                )
            console.print(table)

            console.print(f"\n[bold green]Exported Admin Chats List to:[/bold green]")
            console.print(f" - CSV: [link=file://{csv_path}]{csv_path}[/link]")
            console.print(f" - JSON: [link=file://{json_path}]{json_path}[/link]")
        else:
            console.print("[yellow]No groups or channels found where your account is Owner or Admin.[/yellow]")
        return

    if choice == "4":
        from modules.lead_finder import TelegramLeadFinderModule
        lead_finder = TelegramLeadFinderModule(client)

        console.print("\n[bold green]-- OTP SMS / API Buyer Finder Target --[/bold green]")
        console.print("1. Scan ALL Joined Groups & Supergroups")
        console.print("2. Scan Specific Group Username or ID")
        sub_choice = Prompt.ask("Select target scope", choices=["1", "2"], default="1")

        buyers = []
        if sub_choice == "1":
            limit_cnt = IntPrompt.ask("Enter max messages to scan per group", default=200)
            with console.status("[bold green]Scanning ALL joined groups and classifying buyers with Ollama AI..."):
                buyers = await lead_finder.find_buyers_in_all_joined_groups(per_group_limit=limit_cnt)
            file_prefix = "all_joined_groups_buyers"
        else:
            chat_target = Prompt.ask("Enter group/channel username or ID (e.g. @tech_group)")
            limit_cnt = IntPrompt.ask("Enter max messages to scan", default=500)
            with console.status(f"[bold green]Scanning '{chat_target}' and classifying buyers with Ollama AI..."):
                buyers = await lead_finder.find_sms_buyers(chat_target, limit=limit_cnt)
            file_prefix = f"otp_buyers_{chat_target.replace('@', '')}"
            
        if buyers:
            csv_path = lead_finder.export_to_csv(buyers, f"{file_prefix}.csv")
            json_path = lead_finder.export_to_json(buyers, f"{file_prefix}.json")
            console.print(f"\n[bold green]Found {len(buyers)} Genuine OTP/Bulk SMS Buyers![/bold green]")
            
            table = Table(title="Qualified Buyers List")
            table.add_column("User ID", style="cyan")
            table.add_column("Name", style="bold white")
            table.add_column("Username", style="yellow")
            table.add_column("Group", style="magenta")
            table.add_column("Message Snippet", style="dim white")

            for b in buyers:
                table.add_row(
                    str(b["user_id"]),
                    f"{b['first_name']} {b['last_name']}".strip(),
                    b["username"] or "No Username",
                    b.get("source_group", "Target Chat"),
                    b["message_snippet"][:40] + "..."
                )
            console.print(table)

            console.print(f"\n[bold green]Exported Qualified Buyers to:[/bold green]")
            console.print(f" - CSV: [link=file://{csv_path}]{csv_path}[/link]")
            console.print(f" - JSON: [link=file://{json_path}]{json_path}[/link]")
        else:
            console.print("[yellow]No buyers found in scanned messages.[/yellow]")
        return

    if choice == "3":
        with console.status("[bold green]Scanning all joined groups/chats for message posting permissions..."):
            w_groups = await scraper.find_writable_groups()
        if w_groups:
            csv_path = scraper.export_to_csv(w_groups, "writable_groups.csv")
            json_path = scraper.export_to_json(w_groups, "writable_groups.json")
            console.print(f"\n[bold green]Found {len(w_groups)} Writable Groups![/bold green]")
            
            table = Table(title="Writable Groups List")
            table.add_column("Chat ID", style="cyan")
            table.add_column("Title", style="bold white")
            table.add_column("Username", style="yellow")
            table.add_column("Members", style="magenta")

            for g in w_groups:
                table.add_row(
                    str(g["chat_id"]),
                    g["title"],
                    f"@{g['username']}" if g['username'] else "Private/No Username",
                    str(g["members_count"])
                )
            console.print(table)

            console.print(f"\n[bold green]Exported Writable Groups to:[/bold green]")
            console.print(f" - CSV: [link=file://{csv_path}]{csv_path}[/link]")
            console.print(f" - JSON: [link=file://{json_path}]{json_path}[/link]")
        else:
            console.print("[yellow]No writable groups found in joined dialogs.[/yellow]")
        return

    chat_target = Prompt.ask("Enter group/channel username or ID (e.g. @group_name)")
    limit_cnt = IntPrompt.ask("Enter max items limit", default=1000)

    if choice == "1":
        with console.status(f"[bold green]Scraping members from {chat_target}..."):
            members = await scraper.scrape_members(chat_target, limit=limit_cnt)
        if members:
            csv_path = scraper.export_to_csv(members, f"members_{chat_target.replace('@', '')}.csv")
            json_path = scraper.export_to_json(members, f"members_{chat_target.replace('@', '')}.json")
            console.print(f"[bold green]Exported {len(members)} members to:[/bold green]")
            console.print(f" - CSV: [link=file://{csv_path}]{csv_path}[/link]")
            console.print(f" - JSON: [link=file://{json_path}]{json_path}[/link]")
        else:
            console.print("[yellow]No members found or permission denied.[/yellow]")

    elif choice == "2":
        with console.status(f"[bold green]Scraping message history from {chat_target}..."):
            messages = await scraper.scrape_messages(chat_target, limit=limit_cnt)
        if messages:
            csv_path = scraper.export_to_csv(messages, f"messages_{chat_target.replace('@', '')}.csv")
            json_path = scraper.export_to_json(messages, f"messages_{chat_target.replace('@', '')}.json")
            console.print(f"[bold green]Exported {len(messages)} messages to:[/bold green]")
            console.print(f" - CSV: [link=file://{csv_path}]{csv_path}[/link]")
            console.print(f" - JSON: [link=file://{json_path}]{json_path}[/link]")
        else:
            console.print("[yellow]No messages scraped.[/yellow]")

async def post_monitor_menu(session_mgr: SessionManager):
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        console.print("[red]No account sessions available.[/red]")
        return

    sname = Prompt.ask("Select session for Post Health Monitor", choices=sessions, default=sessions[0])
    client = await session_mgr.start_session(sname)

    from modules.post_monitor import PostHealthMonitor, GroupBlacklistManager
    monitor = PostHealthMonitor(client)

    console.print("\n[bold green]-- Group Health & Anti-Deletion Monitor --[/bold green]")
    console.print("1. Scan & Verify Tracked Posts Health (Auto-Blacklist Deleted Posts)")
    console.print("2. View Blacklisted / Restricted Groups (restricted_groups.csv)")
    m_choice = Prompt.ask("Select action", choices=["1", "2"], default="1")

    if m_choice == "1":
        with console.status("[bold green]Verifying post health across tracked groups..."):
            summary = await monitor.check_all_tracked_posts()
        console.print(f"\n[bold green]Post Health Verification Complete![/bold green]")
        console.print(f" Total Checked        : {summary['total_checked']}")
        console.print(f" Active Messages      : {summary['active_count']}")
        console.print(f" Deleted Messages     : {summary['deleted_count']}")
        console.print(f" New Blacklisted Chats: {summary['new_blacklisted']}")
    elif m_choice == "2":
        restricted = GroupBlacklistManager.get_restricted_groups()
        if not restricted:
            console.print("[green]No blacklisted groups found in restricted_groups.csv.[/green]")
            return
        
        table = Table(title="Blacklisted / Restricted Groups")
        table.add_column("Chat ID", style="cyan")
        table.add_column("Title", style="bold white")
        table.add_column("Reason", style="red")
        table.add_column("Date Added", style="yellow")

        for r in restricted:
            table.add_row(str(r["chat_id"]), r["title"], r.get("reason", "DELETED"), r.get("blacklisted_at", ""))
        console.print(table)


async def main():
    display_banner()
    if not ensure_credentials():
        return

    session_mgr = SessionManager()

    try:
        while True:
            display_banner()
            console.print("\n[bold white]MAIN AUTOMATION MENU[/bold white]")
            console.print("[bold cyan]1.[/bold cyan] Account & Session Manager")
            console.print("[bold cyan]2.[/bold cyan] Auto-Responder Engine")
            console.print("[bold cyan]3.[/bold cyan] Broadcast & Mass Messenger")
            console.print("[bold cyan]4.[/bold cyan] Channel Mirror & Forwarder")
            console.print("[bold cyan]5.[/bold cyan] Group & Chat Data Scraper")
            console.print("[bold cyan]6.[/bold cyan] Group Health & Anti-Deletion Monitor")
            console.print("[bold cyan]7.[/bold cyan] Exit")

            option = Prompt.ask("\nSelect action", choices=["1", "2", "3", "4", "5", "6", "7"])

            if option == "1":
                await account_manager_menu(session_mgr)
            elif option == "2":
                await auto_responder_menu(session_mgr)
            elif option == "3":
                await broadcast_menu(session_mgr)
            elif option == "4":
                await channel_forwarder_menu(session_mgr)
            elif option == "5":
                await scraper_menu(session_mgr)
            elif option == "6":
                await post_monitor_menu(session_mgr)
            elif option == "7":
                console.print("\n[bold cyan]Shutting down sessions and exiting...[/bold cyan]")
                await session_mgr.stop_all()
                break

    except Exception as e:
        logger.exception("Unexpected runtime exception in CLI main")
        console.print(f"[bold red]Fatal Error: {e}[/bold red]")
    finally:
        await session_mgr.stop_all()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        rprint("\n[bold yellow]Program terminated by user.[/bold yellow]")

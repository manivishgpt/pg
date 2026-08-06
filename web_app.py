import os
import json
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from config import settings
from core.session_manager import SessionManager
from modules.scraper import TelegramScraperModule
from modules.broadcaster import BroadcasterModule
from modules.auto_responder import AutoResponderModule, AutoResponderRule
from modules.post_monitor import PostHealthMonitor, GroupBlacklistManager, SentPostTracker


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebApp")

app = FastAPI(title="Telegram Account Automation Web Dashboard")

BASE_DIR = Path(__file__).resolve().parent

# Static & Templates setup
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

session_mgr = SessionManager()
connected_websockets: List[WebSocket] = []

# Log Broadcaster Helper
async def broadcast_log(message: str):
    logger.info(message)
    disconnected = []
    for ws in connected_websockets:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in connected_websockets:
            connected_websockets.remove(ws)

# Models
class ScanRequest(BaseModel):
    session_name: Optional[str] = None

class BroadcastRequest(BaseModel):
    session_name: str
    targets: List[str]
    text: str
    min_delay: Optional[float] = None
    max_delay: Optional[float] = None
    safety_preset: Optional[str] = "ultra_safe"
    max_batch_size: Optional[int] = None

class PostForwardRequest(BaseModel):
    session_name: str
    post_url: str
    target_csv: Optional[str] = "my_admin_chats.csv"
    copy_mode: Optional[bool] = False
    min_delay: Optional[float] = None
    max_delay: Optional[float] = None
    safety_preset: Optional[str] = "ultra_safe"
    max_batch_size: Optional[int] = None

class ContinuousBroadcastRequest(BaseModel):
    session_name: str
    post_url: Optional[str] = None
    text: Optional[str] = None
    target_csv: Optional[str] = "writable_groups.csv"
    copy_mode: Optional[bool] = True
    safety_preset: Optional[str] = "ultra_safe"
    min_interval_minutes: Optional[float] = 5.0
    max_interval_minutes: Optional[float] = 10.0
    max_batch_size: Optional[int] = None

active_continuous_tasks: Dict[str, Dict[str, Any]] = {}


class AutoResponderRequest(BaseModel):
    session_name: str
    rules: Optional[List[Dict[str, Any]]] = []
    ai_mode_global: Optional[bool] = False
    global_ai_model: Optional[str] = "qwen2.5:3b"

# Routes
@app.get("/")
async def serve_dashboard(request: Request):
    return FileResponse(BASE_DIR / "templates" / "index.html")

@app.get("/api/sessions")
async def list_sessions():
    existing = session_mgr.get_existing_sessions()
    sessions_data = []
    for sname in existing:
        client_info = {
            "name": sname,
            "status": "Offline",
            "first_name": "",
            "username": "",
            "user_id": None
        }
        if sname in session_mgr.active_clients:
            client = session_mgr.active_clients[sname]
            if client.is_connected:
                try:
                    me = await client.get_me()
                    client_info["status"] = "Active"
                    client_info["first_name"] = me.first_name or ""
                    client_info["username"] = me.username or ""
                    client_info["user_id"] = me.id
                except Exception:
                    pass
        sessions_data.append(client_info)
    return {"sessions": sessions_data}

@app.get("/api/scraper/my-admin-chats")
async def get_my_admin_chats():
    json_path = settings.output_dir / "my_admin_chats.json"
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"chats": data}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return {"chats": []}

@app.get("/api/scraper/writable-groups")
async def get_writable_groups():
    json_path = settings.output_dir / "writable_groups.json"
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"groups": data}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return {"groups": []}

@app.get("/api/scraper/active-writable-groups")
async def get_active_writable_groups():
    json_path = settings.output_dir / "active_writable_groups.json"
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"groups": data}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return {"groups": []}

@app.post("/api/scraper/scan-active-groups")
async def scan_active_groups(req: ScanRequest):
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        return JSONResponse(status_code=400, content={"status": "error", "error": "No session accounts available. Please log in first."})
    
    sname = req.session_name or sessions[0]
    await broadcast_log(f"[WEB API] Starting Active Continuous Chatting Groups scan on session '{sname}'...")
    
    try:
        client = await session_mgr.start_session(sname)
        scraper = TelegramScraperModule(client)
        
        active_groups = await scraper.find_active_chatting_groups(max_age_hours=24.0)
        scraper.export_to_json(active_groups, "active_writable_groups.json")
        scraper.export_to_csv(active_groups, "active_writable_groups.csv")
        
        await broadcast_log(f"[WEB API] Active groups scan completed. Found {len(active_groups)} high-activity groups.")
        return {"status": "success", "count": len(active_groups), "groups": active_groups}
    except Exception as e:
        await broadcast_log(f"[WEB API ERROR] Active groups scan failed: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

@app.post("/api/scraper/scan-writable-groups")
async def scan_writable_groups(req: ScanRequest):
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        return JSONResponse(status_code=400, content={"status": "error", "error": "No session accounts available. Please log in first."})
    
    sname = req.session_name or sessions[0]
    await broadcast_log(f"[WEB API] Starting Writable Groups scan on session '{sname}'...")
    
    try:
        client = await session_mgr.start_session(sname)
        scraper = TelegramScraperModule(client)
        
        w_groups = await scraper.find_writable_groups()
        scraper.export_to_json(w_groups, "writable_groups.json")
        scraper.export_to_csv(w_groups, "writable_groups.csv")
        
        await broadcast_log(f"[WEB API] Scan completed. Found {len(w_groups)} writable groups.")
        return {"status": "success", "count": len(w_groups), "groups": w_groups}
    except Exception as e:
        await broadcast_log(f"[WEB API ERROR] Scan failed: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

@app.post("/api/scraper/scan-my-admin-chats")
async def scan_my_admin_chats(req: ScanRequest):
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        return JSONResponse(status_code=400, content={"status": "error", "error": "No session accounts available. Please log in first."})
    
    sname = req.session_name or sessions[0]
    await broadcast_log(f"[WEB API] Scanning Admin/Owner groups & channels on session '{sname}'...")
    
    try:
        client = await session_mgr.start_session(sname)
        scraper = TelegramScraperModule(client)
        
        admin_chats = await scraper.find_my_admin_groups()
        scraper.export_to_json(admin_chats, "my_admin_chats.json")
        scraper.export_to_csv(admin_chats, "my_admin_chats.csv")
        
        await broadcast_log(f"[WEB API] Admin chats scan completed. Found {len(admin_chats)} chats.")
        return {"status": "success", "count": len(admin_chats), "chats": admin_chats}
    except Exception as e:
        await broadcast_log(f"[WEB API ERROR] Admin scan failed: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

@app.post("/api/broadcaster/launch")
async def launch_broadcast(req: BroadcastRequest):
    await broadcast_log(f"[WEB API] Launching broadcast campaign for {len(req.targets)} targets using session '{req.session_name}' (Safety Preset: {req.safety_preset})...")
    try:
        client = await session_mgr.start_session(req.session_name)
        broadcaster = BroadcasterModule(client)
        
        def cb(current, total, target_disp, success, err, next_disp="End of Queue"):
            if "REST_PAUSE" in target_disp:
                asyncio.create_task(broadcast_log(f"🛡️ [ANTI-BAN PAUSE] {err} | Next Target: '{next_disp}'"))
            else:
                status_str = 'SUCCESS' if success else f'FAILED ({err})'
                asyncio.create_task(broadcast_log(f"[BROADCAST] ({current}/{total}) Delivered: '{target_disp}' | {status_str} | ⏩ Next Target: '{next_disp}'"))
            
        summary = await broadcaster.broadcast(
            targets=req.targets,
            text=req.text,
            min_delay=req.min_delay,
            max_delay=req.max_delay,
            safety_preset=req.safety_preset or "ultra_safe",
            max_batch_size=req.max_batch_size,
            progress_callback=cb
        )
        return summary
    except Exception as e:
        await broadcast_log(f"[WEB API ERROR] Broadcast failed: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

@app.post("/api/broadcaster/post-forward")
async def launch_post_forward(req: PostForwardRequest):
    csv_filename = req.target_csv or "my_admin_chats.csv"
    csv_path = settings.output_dir / csv_filename
    
    targets_data = load_targets_from_csv(csv_path)
    if not targets_data:
        return JSONResponse(status_code=400, content={"status": "error", "error": f"No targets found in '{csv_filename}'. Scan admin chats or writable groups first."})

    total_cnt = len(targets_data)
    if req.max_batch_size and req.max_batch_size > 0:
        total_cnt = min(total_cnt, req.max_batch_size)

    await broadcast_log(f"[WEB API] 1-Click Post Forwarding '{req.post_url}' to {total_cnt} targets from {csv_filename} (Safety Preset: {req.safety_preset})...")

    try:
        client = await session_mgr.start_session(req.session_name)
        broadcaster = BroadcasterModule(client)
        
        def cb(current, total, target_disp, success, err, next_disp="End of Queue"):
            if "REST_PAUSE" in target_disp:
                asyncio.create_task(broadcast_log(f"🛡️ [ANTI-BAN PAUSE] {err} | Next Target: '{next_disp}'"))
            else:
                status_str = 'SUCCESS' if success else f'FAILED ({err})'
                asyncio.create_task(broadcast_log(f"[1-CLICK FORWARD] ({current}/{total}) Delivered: '{target_disp}' | {status_str} | ⏩ Next Target: '{next_disp}'"))
            
        summary = await broadcaster.broadcast_post(
            targets=targets_data,
            post_url=req.post_url,
            copy_mode=req.copy_mode or False,
            min_delay=req.min_delay,
            max_delay=req.max_delay,
            safety_preset=req.safety_preset or "ultra_safe",
            max_batch_size=req.max_batch_size,
            progress_callback=cb
        )
        return summary
    except Exception as e:
        await broadcast_log(f"[WEB API ERROR] Post forward failed: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})


@app.post("/api/broadcaster/continuous/start")
async def start_continuous_broadcast(req: ContinuousBroadcastRequest):
    sname = req.session_name
    if sname in active_continuous_tasks and active_continuous_tasks[sname].get("running"):
        return JSONResponse(status_code=400, content={"status": "error", "error": f"Continuous campaign is already active on session '{sname}'."})

    csv_filename = req.target_csv or "writable_groups.csv"
    csv_path = settings.output_dir / csv_filename

    if not csv_path.exists():
        return JSONResponse(status_code=400, content={"status": "error", "error": f"Target CSV file '{csv_filename}' not found. Please scan target groups first."})

    await broadcast_log(f"[WEB API] Initializing Continuous Auto-Send Campaign on session '{sname}' (Interval: {req.min_interval_minutes}-{req.max_interval_minutes} mins, Safety: {req.safety_preset})...")

    stop_evt = asyncio.Event()
    task_info = {
        "running": True,
        "session_name": sname,
        "round_num": 0,
        "target_csv": csv_filename,
        "current_status": "Starting continuous loop...",
        "stop_event": stop_evt,
        "task": None
    }
    active_continuous_tasks[sname] = task_info

    async def run_loop():
        try:
            client = await session_mgr.start_session(sname)
            broadcaster = BroadcasterModule(client)

            def cb(round_n, current, total, target_disp, success, err, next_disp="End of Queue"):
                task_info["round_num"] = round_n
                if "CYCLE_WAIT" in target_disp:
                    task_info["current_status"] = f"Round #{round_n} Complete. Waiting for next cycle..."
                    asyncio.create_task(broadcast_log(f"⏳ [CONTINUOUS LOOP] Round #{round_n} Complete. Waiting {err}... Next Round #{round_n + 1}"))
                elif "REST_PAUSE" in target_disp:
                    task_info["current_status"] = f"Rest Pause ({err})"
                    asyncio.create_task(broadcast_log(f"🛡️ [ANTI-BAN PAUSE] Round #{round_n} {err} | Next: '{next_disp}'"))
                else:
                    status_str = 'SUCCESS' if success else f'FAILED ({err})'
                    task_info["current_status"] = f"Round #{round_n} ({current}/{total}): {target_disp}"
                    asyncio.create_task(broadcast_log(f"[CONTINUOUS BROADCAST] Round #{round_n} ({current}/{total}) Delivered: '{target_disp}' | {status_str} | ⏩ Next: '{next_disp}'"))

            await broadcaster.continuous_broadcast(
                targets_source=csv_path,
                post_url=req.post_url,
                text=req.text,
                copy_mode=req.copy_mode if req.copy_mode is not None else True,
                safety_preset=req.safety_preset or "ultra_safe",
                min_interval_minutes=req.min_interval_minutes or 5.0,
                max_interval_minutes=req.max_interval_minutes or 10.0,
                max_batch_size=req.max_batch_size,
                progress_callback=cb,
                stop_event=stop_evt
            )
        except Exception as e:
            await broadcast_log(f"[CONTINUOUS LOOP ERROR] Campaign error on '{sname}': {e}")
        finally:
            task_info["running"] = False
            task_info["current_status"] = "Stopped"
            await broadcast_log(f"[CONTINUOUS LOOP] Continuous auto-send campaign on '{sname}' stopped.")

    bg_task = asyncio.create_task(run_loop())
    task_info["task"] = bg_task

    return {"status": "success", "message": f"Continuous Auto-Send campaign launched on session '{sname}'."}

@app.post("/api/broadcaster/continuous/stop")
async def stop_continuous_broadcast(req: ScanRequest):
    sessions = session_mgr.get_existing_sessions()
    sname = req.session_name or (sessions[0] if sessions else "")
    
    if sname not in active_continuous_tasks or not active_continuous_tasks[sname].get("running"):
        return JSONResponse(status_code=400, content={"status": "error", "error": f"No active continuous campaign running on session '{sname}'."})

    t_info = active_continuous_tasks[sname]
    evt: asyncio.Event = t_info.get("stop_event")
    if evt:
        evt.set()
    t_info["running"] = False
    t_info["current_status"] = "Stopping..."

    await broadcast_log(f"[WEB API] Stop signal sent to continuous campaign on session '{sname}'.")
    return {"status": "success", "message": f"Continuous broadcast campaign on '{sname}' is stopping."}

@app.get("/api/broadcaster/continuous/status")
async def get_continuous_broadcast_status():
    status_list = []
    for sname, info in active_continuous_tasks.items():
        status_list.append({
            "session_name": sname,
            "running": info.get("running", False),
            "round_num": info.get("round_num", 0),
            "target_csv": info.get("target_csv", ""),
            "current_status": info.get("current_status", "Idle")
        })
    return {"tasks": status_list}



@app.post("/api/auto-responder/start")
async def start_auto_responder(req: AutoResponderRequest):
    await broadcast_log(f"[WEB API] Starting Auto-Responder daemon for session '{req.session_name}' (AI Mode: {req.ai_mode_global}, Model: {req.global_ai_model})...")
    try:
        client = await session_mgr.start_session(req.session_name)
        responder = AutoResponderModule(
            client,
            ai_mode_global=req.ai_mode_global or False,
            global_ai_model=req.global_ai_model or "qwen2.5:3b"
        )
        
        if req.rules:
            for r_dict in req.rules:
                rule = AutoResponderRule(
                    keywords=[r_dict["keyword"]],
                    response_text=r_dict.get("response_text", ""),
                    match_type=r_dict.get("match_type", "contains"),
                    private_only=r_dict.get("private_only", True),
                    use_ai=r_dict.get("use_ai", False),
                    ai_model=r_dict.get("ai_model", "qwen2.5:3b")
                )
                responder.add_rule(rule)
            
        responder.start()
        mode_desc = f"Ollama AI ({req.global_ai_model})" if req.ai_mode_global else f"{len(req.rules or [])} rules"
        await broadcast_log(f"[WEB API] Auto-Responder active with {mode_desc}.")
        return {"status": "success", "message": f"Auto-Responder activated with {mode_desc}."}
    except Exception as e:
        await broadcast_log(f"[WEB API ERROR] Failed to start responder: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

@app.get("/api/monitor/restricted-groups")
async def get_restricted_groups():
    return {"restricted_groups": GroupBlacklistManager.get_restricted_groups()}

@app.get("/api/monitor/tracked-posts")
async def get_tracked_posts():
    return {"tracked_posts": SentPostTracker.load_tracker()}

@app.post("/api/monitor/check-health")
async def check_post_health(req: ScanRequest):
    sessions = session_mgr.get_existing_sessions()
    if not sessions:
        return JSONResponse(status_code=400, content={"status": "error", "error": "No session accounts available."})

    sname = req.session_name or sessions[0]
    await broadcast_log(f"[WEB API] Starting Post Health Verification Scan on session '{sname}'...")

    try:
        client = await session_mgr.start_session(sname)
        monitor = PostHealthMonitor(client)

        def cb(current, total, title, status):
            asyncio.create_task(broadcast_log(f"[POST HEALTH] ({current}/{total}) '{title}': {status}"))

        summary = await monitor.check_all_tracked_posts(progress_callback=cb)
        await broadcast_log(f"[WEB API] Post Health Verification Complete. Checked: {summary['total_checked']}, Active: {summary['active_count']}, Deleted: {summary['deleted_count']}, New Blacklisted Groups: {summary['new_blacklisted']}")
        return {"status": "success", "summary": summary}
    except Exception as e:
        await broadcast_log(f"[WEB API ERROR] Post Health check failed: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

@app.get("/api/download/{filename}")

async def download_file(filename: str):
    file_path = settings.output_dir / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(path=str(file_path), filename=filename)
    raise HTTPException(status_code=404, detail="File not found")

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    await websocket.send_text("[SYSTEM] WebSocket Log Stream Active.")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_app:app", host="127.0.0.1", port=8000, reload=True)

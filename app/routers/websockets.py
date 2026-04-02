from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.database import connected_websockets, db, device_status_cache

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    """
    Real-time device status updates for a project.

    Connect via: `ws://localhost:8000/ws/{project_id}`

    Message types:
    - **init**: initial device list with current status
    - **device_status**: device came online or went offline
    """
    await websocket.accept()

    connected_websockets.setdefault(project_id, []).append(websocket)

    try:
        # Send current state immediately on connect
        devices = await db.devices.find({"project_id": project_id}).to_list(100)
        await websocket.send_json({
            "type": "init",
            "devices": [{
                "id": d["device_id"],
                "name": d["name"],
                "online": device_status_cache.get(d["device_id"], {}).get("online", False),
            } for d in devices],
        })

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        if project_id in connected_websockets:
            connected_websockets[project_id].remove(websocket)

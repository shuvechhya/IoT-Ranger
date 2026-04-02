from app.database import connected_websockets


def broadcast_message(project_id: str, message: dict):
    """Broadcast a message to all WebSocket clients subscribed to a project."""
    if project_id not in connected_websockets:
        return

    dead_connections = []
    for ws in connected_websockets[project_id]:
        try:
            import asyncio
            asyncio.run(ws.send_json(message))
        except Exception:
            dead_connections.append(ws)

    for ws in dead_connections:
        connected_websockets[project_id].remove(ws)

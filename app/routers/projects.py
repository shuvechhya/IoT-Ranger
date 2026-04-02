import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.dependencies import get_current_user
from app.models.schemas import ProjectCreate

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("", response_model=list)
async def list_projects(current_user: dict = Depends(get_current_user)):
    """List all projects belonging to the current user."""
    db = get_db()
    projects = await db.projects.find({"user_id": current_user["user_id"]}).to_list(100)
    return [{"id": str(p["_id"]), "name": p["name"]} for p in projects]


@router.post("", response_model=dict)
async def create_project(data: ProjectCreate, current_user: dict = Depends(get_current_user)):
    """Create a new project to group IoT devices."""
    db = get_db()
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    await db.projects.insert_one({
        "_id": project_id,
        "name": data.name,
        "user_id": current_user["user_id"],
        "created_at": datetime.now(timezone.utc),
    })
    return {"id": project_id, "name": data.name}


@router.delete("/{project_id}", response_model=dict)
async def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a project and all its devices. Cannot be undone."""
    db = get_db()
    project = await db.projects.find_one({"_id": project_id, "user_id": current_user["user_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or access denied")

    await db.devices.delete_many({"project_id": project_id})
    await db.projects.delete_one({"_id": project_id})

    return {"message": f"Project {project_id} deleted"}

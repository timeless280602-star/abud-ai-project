"""Owned web projects and conversation organization; no Discord capabilities."""
import time
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app import database

router = APIRouter(prefix="/web/chat")


def actor(request):
    from app.web_chat import identity
    return identity(request)


def init_schema():
    with database.get_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS web_projects (
            id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL REFERENCES auth_identities(identity_id) ON DELETE CASCADE,
            name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', instructions TEXT NOT NULL DEFAULT '',
            memory_mode TEXT NOT NULL CHECK(memory_mode IN ('default','project_only')),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_web_projects_owner ON web_projects(identity_id, updated_at);
        """)


def project(db, project_id, owner):
    if project_id is None:
        return None
    row = db.execute("SELECT * FROM web_projects WHERE id=? AND identity_id=?", (str(project_id), owner)).fetchone()
    if row is None:
        raise HTTPException(404, "Project not found.")
    return dict(row)


def memory_scope(owner, settings):
    if settings and settings['memory_mode'] == 'project_only':
        return f"web-project:{owner}:{settings['id']}"
    return f"web:{owner}"


def conversation(db, cid, owner):
    row = db.execute("SELECT * FROM web_conversations WHERE id=? AND identity_id=?", (cid, owner)).fetchone()
    if row is None:
        raise HTTPException(404, "Conversation not found.")
    if row['lease_until'] > time.time():
        raise HTTPException(409, "A response is still running.")
    return row


def list_conversations(db, owner, archived=False, project_id=None):
    if project_id is not None:
        project(db, project_id, owner)
    conditions = ['c.identity_id=?', 'c.archived_at IS NOT NULL' if archived else 'c.archived_at IS NULL']
    params = [owner]
    if project_id is not None:
        conditions.append('c.project_id=?')
        params.append(str(project_id))
    elif not archived:
        conditions.append('c.project_id IS NULL')
    return [dict(r) for r in db.execute(
        "SELECT c.id,c.title,c.updated_at,c.project_id,c.pinned,c.archived_at,c.title_state,p.name AS project_name "
        "FROM web_conversations c LEFT JOIN web_projects p ON p.id=c.project_id WHERE " + ' AND '.join(conditions)
        + " ORDER BY c.pinned DESC,c.updated_at DESC,c.id DESC LIMIT 200", params)]


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=1000)
    instructions: str = Field(default='', max_length=4000)


class ProjectCreate(ProjectSettings):
    memory_mode: Literal['default', 'project_only'] = 'default'


class ProjectDelete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    conversations: Literal['keep', 'delete']


class Toggle(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool


class Move(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: uuid.UUID | None


@router.get('/projects')
def projects(request: Request):
    owner = actor(request)
    with database.get_connection() as db:
        return [dict(r) for r in db.execute("""
            SELECT p.*,COUNT(CASE WHEN c.archived_at IS NULL THEN c.id END) AS conversation_count
            FROM web_projects p LEFT JOIN web_conversations c ON c.project_id=p.id AND c.identity_id=p.identity_id
            WHERE p.identity_id=? GROUP BY p.id ORDER BY p.updated_at DESC,p.id DESC
        """, (owner,))]


@router.post('/projects', status_code=201)
def create_project(request: Request, payload: ProjectCreate):
    owner = actor(request)
    pid = str(uuid.uuid4())
    now = database.utc_now()
    with database.get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT COUNT(*) FROM web_projects WHERE identity_id=?', (owner,)).fetchone()[0] >= 50:
            raise HTTPException(409, 'Project limit reached (50).')
        db.execute('INSERT INTO web_projects(id,identity_id,name,description,instructions,memory_mode,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                   (pid, owner, payload.name, payload.description, payload.instructions, payload.memory_mode, now, now))
        return project(db, pid, owner)


@router.get('/projects/{pid}')
def get_project(pid: uuid.UUID, request: Request):
    owner = actor(request)
    with database.get_connection() as db:
        return project(db, pid, owner)


@router.patch('/projects/{pid}')
def update_project(pid: uuid.UUID, request: Request, payload: ProjectSettings):
    owner = actor(request)
    with database.get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        project(db, pid, owner)
        db.execute('UPDATE web_projects SET name=?,description=?,instructions=?,updated_at=? WHERE id=? AND identity_id=?',
                   (payload.name, payload.description, payload.instructions, database.utc_now(), str(pid), owner))
        return project(db, pid, owner)


@router.get('/projects/{pid}/conversations')
def project_conversations(pid: uuid.UUID, request: Request, archived: bool = False):
    owner = actor(request)
    with database.get_connection() as db:
        return list_conversations(db, owner, archived, pid)


@router.delete('/projects/{pid}')
def delete_project(pid: uuid.UUID, request: Request, payload: ProjectDelete):
    owner = actor(request)
    with database.get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        settings = project(db, pid, owner)
        if db.execute('SELECT 1 FROM web_conversations WHERE project_id=? AND identity_id=? AND lease_until>?',
                      (str(pid), owner, time.time())).fetchone():
            raise HTTPException(409, 'A response is still running in this project.')
        if payload.conversations == 'keep':
            if settings['memory_mode'] == 'project_only' and db.execute(
                'SELECT 1 FROM web_messages m JOIN web_conversations c ON c.id=m.conversation_id WHERE c.project_id=? AND c.identity_id=? LIMIT 1',
                (str(pid), owner)).fetchone():
                raise HTTPException(409, 'Project-only history cannot become ordinary chat. Keep this project and archive its chats, or explicitly delete its conversations.')
            db.execute('UPDATE web_conversations SET project_id=NULL WHERE project_id=? AND identity_id=?', (str(pid), owner))
        else:
            db.execute('DELETE FROM web_conversations WHERE project_id=? AND identity_id=?', (str(pid), owner))
        if settings['memory_mode'] == 'project_only':
            db.execute('DELETE FROM users WHERE user_id=?', (memory_scope(owner, settings),))
        db.execute('DELETE FROM web_projects WHERE id=? AND identity_id=?', (str(pid), owner))
    return {'success': True}


@router.patch('/conversations/{cid}/pin')
def pin(cid: str, request: Request, payload: Toggle):
    owner = actor(request)
    with database.get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        conversation(db, cid, owner)
        db.execute('UPDATE web_conversations SET pinned=? WHERE id=? AND identity_id=?', (int(payload.enabled), cid, owner))
    return {'success': True}


@router.patch('/conversations/{cid}/archive')
def archive(cid: str, request: Request, payload: Toggle):
    owner = actor(request)
    with database.get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        conversation(db, cid, owner)
        db.execute('UPDATE web_conversations SET archived_at=? WHERE id=? AND identity_id=?',
                   (database.utc_now() if payload.enabled else None, cid, owner))
    return {'success': True}


@router.patch('/conversations/{cid}/project')
def move(cid: str, request: Request, payload: Move):
    owner = actor(request)
    with database.get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = conversation(db, cid, owner)
        destination = project(db, payload.project_id, owner)
        original = project(db, row['project_id'], owner)
        changed_scope = memory_scope(owner, original) != memory_scope(owner, destination)
        if changed_scope and db.execute('SELECT 1 FROM web_messages WHERE conversation_id=? LIMIT 1', (cid,)).fetchone():
            raise HTTPException(409, 'Only empty conversations can cross project-only memory boundaries. Create a new chat in the destination project; existing memories are never moved.')
        db.execute('UPDATE web_conversations SET project_id=?,updated_at=? WHERE id=? AND identity_id=?',
                   (str(payload.project_id) if payload.project_id else None, database.utc_now(), cid, owner))
    return {'success': True}

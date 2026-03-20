"""Namespace and Team API routes for multi-tenant support."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from deepiri_zepgpu.api.server.dependencies import get_current_user, get_db_session
from deepiri_zepgpu.database.repositories import NamespaceRepository, NamespaceMemberRepository, TeamRepository, TeamMemberRepository, NamespaceQuotaRepository, NamespaceUsageRepository


router = APIRouter()


class NamespaceCreateRequest(BaseModel):
    """Namespace creation request."""
    name: str = Field(..., min_length=3, max_length=255, pattern="^[a-z0-9-]+$")
    display_name: str | None = None
    description: str | None = None
    max_users: int | None = None
    max_gpus: int | None = None
    max_storage_gb: int | None = None


class NamespaceUpdateRequest(BaseModel):
    """Namespace update request."""
    display_name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None
    max_users: int | None = None
    max_gpus: int | None = None
    max_storage_gb: int | None = None


class NamespaceResponse(BaseModel):
    """Namespace response."""
    id: str
    name: str
    display_name: str | None
    description: str | None
    status: str
    owner_id: str | None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NamespaceListResponse(BaseModel):
    """Namespace list response."""
    namespaces: list[NamespaceResponse]
    total: int


class NamespaceMemberResponse(BaseModel):
    """Namespace member response."""
    id: str
    namespace_id: str
    user_id: str
    role: str
    is_active: bool
    joined_at: datetime

    class Config:
        from_attributes = True


class TeamCreateRequest(BaseModel):
    """Team creation request."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class TeamUpdateRequest(BaseModel):
    """Team update request."""
    name: str | None = None
    description: str | None = None
    team_lead_id: str | None = None


class TeamResponse(BaseModel):
    """Team response."""
    id: str
    namespace_id: str
    name: str
    description: str | None
    team_lead_id: str | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TeamListResponse(BaseModel):
    """Team list response."""
    teams: list[TeamResponse]
    total: int


class TeamMemberResponse(BaseModel):
    """Team member response."""
    id: str
    team_id: str
    user_id: str
    role: str
    is_active: bool
    joined_at: datetime

    class Config:
        from_attributes = True


class NamespaceQuotaResponse(BaseModel):
    """Namespace quota response."""
    namespace_id: str
    max_gpus: int | None
    max_gpus_per_user: int | None
    max_storage_gb: int | None
    max_tasks: int | None
    max_scheduled_tasks: int | None
    max_gang_tasks: int | None
    max_gpu_hours_per_day: float | None
    max_gpu_hours_per_month: float | None
    max_concurrent_tasks: int | None

    class Config:
        from_attributes = True


class NamespaceUsageResponse(BaseModel):
    """Namespace usage response."""
    namespace_id: str
    current_gpus: int
    current_storage_gb: float
    total_tasks: int
    running_tasks: int
    scheduled_tasks: int
    gang_tasks: int
    gpu_hours_today: float
    gpu_hours_this_month: float

    class Config:
        from_attributes = True


class QuotaUpdateRequest(BaseModel):
    """Quota update request."""
    max_gpus: int | None = None
    max_gpus_per_user: int | None = None
    max_storage_gb: int | None = None
    max_tasks: int | None = None
    max_scheduled_tasks: int | None = None
    max_gang_tasks: int | None = None
    max_gpu_hours_per_day: float | None = None
    max_gpu_hours_per_month: float | None = None
    max_concurrent_tasks: int | None = None


async def check_namespace_admin(namespace_id: str, user_id: str, db) -> bool:
    """Check if user is admin of namespace."""
    member_repo = NamespaceMemberRepository(db)
    namespace_repo = NamespaceRepository(db)
    
    namespace = await namespace_repo.get_by_id(namespace_id)
    if not namespace:
        return False
    
    if namespace.owner_id == user_id:
        return True
    
    return await member_repo.is_admin(user_id, namespace_id)


@router.post("", response_model=NamespaceResponse, status_code=status.HTTP_201_CREATED)
async def create_namespace(
    request: NamespaceCreateRequest,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> NamespaceResponse:
    """Create a new namespace."""
    from deepiri_zepgpu.database.models import Namespace, NamespaceStatus
    
    namespace_repo = NamespaceRepository(db)
    
    existing = await namespace_repo.get_by_name(request.name)
    if existing:
        raise HTTPException(status_code=400, detail="Namespace name already exists")
    
    namespace = Namespace(
        id=str(uuid.uuid4()),
        name=request.name,
        display_name=request.display_name,
        description=request.description,
        status=NamespaceStatus.ACTIVE,
        owner_id=current_user.id if current_user else None,
        max_users=request.max_users,
        max_gpus=request.max_gpus,
        max_storage_gb=request.max_storage_gb,
    )
    
    db.add(namespace)
    await db.flush()
    
    if current_user:
        member_repo = NamespaceMemberRepository(db)
        member = NamespaceMember(
            id=str(uuid.uuid4()),
            namespace_id=namespace.id,
            user_id=current_user.id,
            role="owner",
            joined_at=datetime.utcnow(),
        )
        db.add(member)
        await db.flush()
    
    return NamespaceResponse(
        id=namespace.id,
        name=namespace.name,
        display_name=namespace.display_name,
        description=namespace.description,
        status=namespace.status.value,
        owner_id=namespace.owner_id,
        is_default=namespace.is_default,
        created_at=namespace.created_at,
        updated_at=namespace.updated_at,
    )


@router.get("", response_model=NamespaceListResponse)
async def list_namespaces(
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> NamespaceListResponse:
    """List namespaces the user has access to."""
    namespace_repo = NamespaceRepository(db)
    
    if current_user:
        namespaces = await namespace_repo.list_user_namespaces(str(current_user.id))
    else:
        namespaces = await namespace_repo.list_all()
    
    return NamespaceListResponse(
        namespaces=[
            NamespaceResponse(
                id=n.id,
                name=n.name,
                display_name=n.display_name,
                description=n.description,
                status=n.status.value,
                owner_id=n.owner_id,
                is_default=n.is_default,
                created_at=n.created_at,
                updated_at=n.updated_at,
            )
            for n in namespaces
        ],
        total=len(namespaces),
    )


@router.get("/{namespace_id}", response_model=NamespaceResponse)
async def get_namespace(
    namespace_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> NamespaceResponse:
    """Get namespace by ID."""
    namespace_repo = NamespaceRepository(db)
    namespace = await namespace_repo.get_by_id(namespace_id)
    
    if not namespace:
        raise HTTPException(status_code=404, detail="Namespace not found")
    
    if current_user:
        member_repo = NamespaceMemberRepository(db)
        if not await member_repo.is_member(str(current_user.id), namespace_id):
            raise HTTPException(status_code=403, detail="Access denied")
    
    return NamespaceResponse(
        id=namespace.id,
        name=namespace.name,
        display_name=namespace.display_name,
        description=namespace.description,
        status=namespace.status.value,
        owner_id=namespace.owner_id,
        is_default=namespace.is_default,
        created_at=namespace.created_at,
        updated_at=namespace.updated_at,
    )


@router.put("/{namespace_id}", response_model=NamespaceResponse)
async def update_namespace(
    namespace_id: str,
    request: NamespaceUpdateRequest,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> NamespaceResponse:
    """Update a namespace."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not await check_namespace_admin(namespace_id, str(current_user.id), db):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    namespace_repo = NamespaceRepository(db)
    update_data = request.model_dump(exclude_unset=True)
    
    namespace = await namespace_repo.update(namespace_id, **update_data)
    
    return NamespaceResponse(
        id=namespace.id,
        name=namespace.name,
        display_name=namespace.display_name,
        description=namespace.description,
        status=namespace.status.value,
        owner_id=namespace.owner_id,
        is_default=namespace.is_default,
        created_at=namespace.created_at,
        updated_at=namespace.updated_at,
    )


@router.delete("/{namespace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_namespace(
    namespace_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> None:
    """Delete a namespace."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    namespace_repo = NamespaceRepository(db)
    namespace = await namespace_repo.get_by_id(namespace_id)
    
    if not namespace:
        raise HTTPException(status_code=404, detail="Namespace not found")
    
    if namespace.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can delete namespace")
    
    await namespace_repo.delete(namespace_id)


@router.post("/{namespace_id}/members", response_model=NamespaceMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_namespace_member(
    namespace_id: str,
    user_id: str,
    role: str = "member",
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> NamespaceMemberResponse:
    """Add a member to namespace."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not await check_namespace_admin(namespace_id, str(current_user.id), db):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from deepiri_zepgpu.database.models import NamespaceMember, TeamRole
    
    member_repo = NamespaceMemberRepository(db)
    existing = await member_repo.get_by_user_namespace(user_id, namespace_id)
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member")
    
    member = NamespaceMember(
        id=str(uuid.uuid4()),
        namespace_id=namespace_id,
        user_id=user_id,
        role=TeamRole(role),
        joined_at=datetime.utcnow(),
    )
    db.add(member)
    await db.flush()
    
    return NamespaceMemberResponse(
        id=member.id,
        namespace_id=member.namespace_id,
        user_id=member.user_id,
        role=member.role.value,
        is_active=member.is_active,
        joined_at=member.joined_at,
    )


@router.get("/{namespace_id}/members", response_model=list[NamespaceMemberResponse])
async def list_namespace_members(
    namespace_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> list[NamespaceMemberResponse]:
    """List namespace members."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    member_repo = NamespaceMemberRepository(db)
    members = await member_repo.list_by_namespace(namespace_id)
    
    return [
        NamespaceMemberResponse(
            id=m.id,
            namespace_id=m.namespace_id,
            user_id=m.user_id,
            role=m.role.value,
            is_active=m.is_active,
            joined_at=m.joined_at,
        )
        for m in members
    ]


@router.delete("/{namespace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_namespace_member(
    namespace_id: str,
    member_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> None:
    """Remove a member from namespace."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not await check_namespace_admin(namespace_id, str(current_user.id), db):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    member_repo = NamespaceMemberRepository(db)
    member = await member_repo.get_by_id(member_id)
    
    if not member or member.namespace_id != namespace_id:
        raise HTTPException(status_code=404, detail="Member not found")
    
    await member_repo.delete(member_id)


@router.post("/{namespace_id}/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    namespace_id: str,
    request: TeamCreateRequest,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> TeamResponse:
    """Create a team in namespace."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not await check_namespace_admin(namespace_id, str(current_user.id), db):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from deepiri_zepgpu.database.models import Team
    
    team_repo = TeamRepository(db)
    existing = await team_repo.get_by_namespace_name(namespace_id, request.name)
    if existing:
        raise HTTPException(status_code=400, detail="Team name already exists in namespace")
    
    team = Team(
        id=str(uuid.uuid4()),
        namespace_id=namespace_id,
        name=request.name,
        description=request.description,
        team_lead_id=current_user.id if current_user else None,
    )
    db.add(team)
    await db.flush()
    
    return TeamResponse(
        id=team.id,
        namespace_id=team.namespace_id,
        name=team.name,
        description=team.description,
        team_lead_id=team.team_lead_id,
        is_active=team.is_active,
        created_at=team.created_at,
    )


@router.get("/{namespace_id}/teams", response_model=TeamListResponse)
async def list_teams(
    namespace_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> TeamListResponse:
    """List teams in namespace."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    team_repo = TeamRepository(db)
    teams = await team_repo.list_by_namespace(namespace_id)
    
    return TeamListResponse(
        teams=[
            TeamResponse(
                id=t.id,
                namespace_id=t.namespace_id,
                name=t.name,
                description=t.description,
                team_lead_id=t.team_lead_id,
                is_active=t.is_active,
                created_at=t.created_at,
            )
            for t in teams
        ],
        total=len(teams),
    )


@router.post("/{namespace_id}/quota", response_model=NamespaceQuotaResponse)
async def get_or_create_quota(
    namespace_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> NamespaceQuotaResponse:
    """Get or create namespace quota."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    quota_repo = NamespaceQuotaRepository(db)
    quota = await quota_repo.get_or_create(namespace_id)
    
    return NamespaceQuotaResponse(
        namespace_id=quota.namespace_id,
        max_gpus=quota.max_gpus,
        max_gpus_per_user=quota.max_gpus_per_user,
        max_storage_gb=quota.max_storage_gb,
        max_tasks=quota.max_tasks,
        max_scheduled_tasks=quota.max_scheduled_tasks,
        max_gang_tasks=quota.max_gang_tasks,
        max_gpu_hours_per_day=quota.max_gpu_hours_per_day,
        max_gpu_hours_per_month=quota.max_gpu_hours_per_month,
        max_concurrent_tasks=quota.max_concurrent_tasks,
    )


@router.put("/{namespace_id}/quota", response_model=NamespaceQuotaResponse)
async def update_quota(
    namespace_id: str,
    request: QuotaUpdateRequest,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> NamespaceQuotaResponse:
    """Update namespace quota."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not await check_namespace_admin(namespace_id, str(current_user.id), db):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    quota_repo = NamespaceQuotaRepository(db)
    update_data = request.model_dump(exclude_unset=True)
    quota = await quota_repo.update(namespace_id, **update_data)
    
    return NamespaceQuotaResponse(
        namespace_id=quota.namespace_id,
        max_gpus=quota.max_gpus,
        max_gpus_per_user=quota.max_gpus_per_user,
        max_storage_gb=quota.max_storage_gb,
        max_tasks=quota.max_tasks,
        max_scheduled_tasks=quota.max_scheduled_tasks,
        max_gang_tasks=quota.max_gang_tasks,
        max_gpu_hours_per_day=quota.max_gpu_hours_per_day,
        max_gpu_hours_per_month=quota.max_gpu_hours_per_month,
        max_concurrent_tasks=quota.max_concurrent_tasks,
    )


@router.get("/{namespace_id}/usage", response_model=NamespaceUsageResponse)
async def get_usage(
    namespace_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> NamespaceUsageResponse:
    """Get namespace resource usage."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    usage_repo = NamespaceUsageRepository(db)
    usage = await usage_repo.get_or_create(namespace_id)
    
    return NamespaceUsageResponse(
        namespace_id=usage.namespace_id,
        current_gpus=usage.current_gpus,
        current_storage_gb=usage.current_storage_gb,
        total_tasks=usage.total_tasks,
        running_tasks=usage.running_tasks,
        scheduled_tasks=usage.scheduled_tasks,
        gang_tasks=usage.gang_tasks,
        gpu_hours_today=usage.gpu_hours_today,
        gpu_hours_this_month=usage.gpu_hours_this_month,
    )


@router.get("/me", response_model=list[NamespaceResponse])
async def get_my_namespaces(
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> list[NamespaceResponse]:
    """Get namespaces for current user."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    namespace_repo = NamespaceRepository(db)
    namespaces = await namespace_repo.list_user_namespaces(str(current_user.id))
    
    return [
        NamespaceResponse(
            id=n.id,
            name=n.name,
            display_name=n.display_name,
            description=n.description,
            status=n.status.value,
            owner_id=n.owner_id,
            is_default=n.is_default,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in namespaces
    ]

"""User API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field

from deepiri_zepgpu.api.server.dependencies import get_current_user, get_db_session
from deepiri_zepgpu.database.models import User
from deepiri_zepgpu.database.repositories import UserRepository
from deepiri_zepgpu.database.models.user import UserRole


router = APIRouter()


class UserRegisterRequest(BaseModel):
    """User registration request."""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: str | None = None
    last_name: str | None = None


class UserLoginRequest(BaseModel):
    """User login request."""
    username: str
    password: str


class UserResponse(BaseModel):
    """User response."""
    id: str
    username: str
    email: str
    role: str
    first_name: str | None
    last_name: str | None
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login_at: datetime | None

    class Config:
        from_attributes = True


class UserUpdateRequest(BaseModel):
    """User update request."""
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None


class TokenResponse(BaseModel):
    """Token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class QuotaResponse(BaseModel):
    """Quota response."""
    max_tasks: int
    max_gpu_hours: float
    max_concurrent_tasks: int
    tasks_remaining: int
    gpu_hours_remaining: float
    concurrent_tasks_remaining: int


def hash_password(password: str) -> str:
    """Hash a password."""
    import hashlib
    import secrets
    salt = secrets.token_hex(16)
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        100000,
    ).hex() + ":" + salt


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password."""
    try:
        hash_value, salt = password_hash.rsplit(":", 1)
        computed_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            100000,
        ).hex()
        return computed_hash == hash_value
    except Exception:
        return False


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: UserRegisterRequest,
    db=Depends(get_db_session),
) -> UserResponse:
    """Register a new user."""
    repo = UserRepository(db)
    
    if await repo.exists_by_username(request.username):
        raise HTTPException(status_code=400, detail="Username already exists")
    
    if await repo.exists_by_email(request.email):
        raise HTTPException(status_code=400, detail="Email already exists")
    
    password_hash = hash_password(request.password)
    
    user = await repo.create(
        username=request.username,
        email=request.email,
        password_hash=password_hash,
        first_name=request.first_name,
        last_name=request.last_name,
    )
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role.value,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: UserLoginRequest,
    db=Depends(get_db_session),
) -> TokenResponse:
    """Login and get access token."""
    import jwt
    
    from deepiri_zepgpu.config import settings
    
    repo = UserRepository(db)
    user = await repo.get_by_username(request.username)
    
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")
    
    await repo.update_last_login(user.id)
    
    token = jwt.encode(
        {
            "sub": user.id,
            "username": user.username,
            "role": user.role.value,
            "exp": datetime.utcnow().timestamp() + settings.auth.access_token_expire_minutes * 60,
        },
        settings.auth.secret_key,
        algorithm=settings.auth.algorithm,
    )
    
    return TokenResponse(
        access_token=token,
        expires_in=settings.auth.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user=Depends(get_current_user),
) -> UserResponse:
    """Get current user information."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        role=current_user.role.value,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at,
        last_login_at=current_user.last_login_at,
    )


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    request: UserUpdateRequest,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> UserResponse:
    """Update current user information."""
    repo = UserRepository(db)
    
    update_data = {}
    if request.first_name is not None:
        update_data["first_name"] = request.first_name
    if request.last_name is not None:
        update_data["last_name"] = request.last_name
    if request.email is not None:
        if await repo.exists_by_email(request.email):
            raise HTTPException(status_code=400, detail="Email already exists")
        update_data["email"] = request.email
    
    user = await repo.update(current_user.id, **update_data)
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role.value,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.get("/me/quota", response_model=QuotaResponse)
async def get_user_quota(
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> QuotaResponse:
    """Get user quota information."""
    from deepiri_zepgpu.database.models.user_quota import UserQuota
    
    if not current_user.quota:
        quota = UserQuota(
            user_id=current_user.id,
            period_start=datetime.utcnow(),
        )
        db.add(quota)
        await db.flush()
        q = quota
    else:
        q = current_user.quota
    
    return QuotaResponse(
        max_tasks=q.max_tasks,
        max_gpu_hours=q.max_gpu_hours,
        max_concurrent_tasks=q.max_concurrent_tasks,
        tasks_remaining=q.tasks_remaining,
        gpu_hours_remaining=q.gpu_hours_remaining,
        concurrent_tasks_remaining=q.concurrent_tasks_remaining,
    )

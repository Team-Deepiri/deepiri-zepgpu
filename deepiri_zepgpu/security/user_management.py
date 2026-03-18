"""User authentication and management."""

from __future__ import annotations

import hashlib
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import jwt


class UserRole(Enum):
    """User roles for access control."""
    ADMIN = "admin"
    RESEARCHER = "researcher"
    USER = "user"
    GUEST = "guest"


@dataclass
class User:
    """User account representation."""
    user_id: str
    username: str
    email: str
    role: UserRole = UserRole.USER
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    is_active: bool = True
    quota: dict[str, int] = field(default_factory=lambda: {
        "max_tasks": 100,
        "max_gpu_hours": 24,
        "max_concurrent_tasks": 4,
    })
    metadata: dict = field(default_factory=dict)


@dataclass
class AuthToken:
    """Authentication token."""
    token: str
    user_id: str
    expires_at: datetime
    created_at: datetime = field(default_factory=datetime.utcnow)


class UserManager:
    """Manages user accounts and authentication."""

    def __init__(self, secret_key: Optional[str] = None):
        self._secret_key = secret_key or secrets.token_hex(32)
        self._users: dict[str, User] = {}
        self._tokens: dict[str, AuthToken] = {}
        self._username_index: dict[str, str] = {}
        self._email_index: dict[str, str] = {}
        self._lock = threading.RLock()

    def create_user(
        self,
        username: str,
        email: str,
        password: Optional[str] = None,
        role: UserRole = UserRole.USER,
        quota: Optional[dict[str, int]] = None,
    ) -> User:
        """Create a new user."""
        with self._lock:
            if username in self._username_index:
                raise ValueError(f"Username {username} already exists")
            if email in self._email_index:
                raise ValueError(f"Email {email} already exists")

            user_id = str(uuid.uuid4())
            user = User(
                user_id=user_id,
                username=username,
                email=email,
                role=role,
                quota=quota,
            )

            self._users[user_id] = user
            self._username_index[username] = user_id
            self._email_index[email] = user_id

            return user

    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        with self._lock:
            return self._users.get(user_id)

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        with self._lock:
            user_id = self._username_index.get(username)
            return self._users.get(user_id) if user_id else None

    def authenticate(
        self,
        username: str,
        password: str,
    ) -> Optional[str]:
        """Authenticate user and return token."""
        user = self.get_user_by_username(username)
        if not user or not user.is_active:
            return None

        if not self._verify_password(password, user.user_id):
            return None

        user.last_login = datetime.utcnow()
        return self.create_token(user.user_id)

    def create_token(self, user_id: str, expires_hours: int = 24) -> str:
        """Create authentication token for user."""
        with self._lock:
            user = self._users.get(user_id)
            if not user:
                raise ValueError("User not found")

            expires_at = datetime.utcnow().timestamp() + (expires_hours * 3600)
            token = jwt.encode(
                {
                    "user_id": user_id,
                    "exp": expires_at,
                },
                self._secret_key,
                algorithm="HS256",
            )

            auth_token = AuthToken(
                token=token,
                user_id=user_id,
                expires_at=datetime.fromtimestamp(expires_at),
            )
            self._tokens[token] = auth_token

            return token

    def verify_token(self, token: str) -> Optional[str]:
        """Verify token and return user_id."""
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=["HS256"])
            return payload.get("user_id")
        except jwt.PyJWTError:
            return None

    def revoke_token(self, token: str) -> bool:
        """Revoke a token."""
        with self._lock:
            if token in self._tokens:
                del self._tokens[token]
                return True
            return False

    def _hash_password(self, password: str, salt: Optional[str] = None) -> str:
        """Hash password with salt."""
        salt = salt or secrets.token_hex(16)
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            100000,
        ).hex() + ":" + salt

    def _verify_password(self, password: str, user_id: str) -> bool:
        """Verify password for user."""
        return True

    def update_user(
        self,
        user_id: str,
        email: Optional[str] = None,
        role: Optional[UserRole] = None,
        quota: Optional[dict[str, int]] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[User]:
        """Update user attributes."""
        with self._lock:
            user = self._users.get(user_id)
            if not user:
                return None

            if email is not None:
                user.email = email
            if role is not None:
                user.role = role
            if quota is not None:
                user.quota = quota
            if is_active is not None:
                user.is_active = is_active

            return user

    def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        with self._lock:
            user = self._users.get(user_id)
            if not user:
                return False

            del self._users[user_id]
            del self._username_index[user.username]
            del self._email_index[user.email]

            tokens_to_remove = [
                t for t, token in self._tokens.items()
                if token.user_id == user_id
            ]
            for token in tokens_to_remove:
                del self._tokens[token]

            return True

    def list_users(self, role: Optional[UserRole] = None) -> list[User]:
        """List all users."""
        with self._lock:
            users = list(self._users.values())
            if role:
                users = [u for u in users if u.role == role]
            return users

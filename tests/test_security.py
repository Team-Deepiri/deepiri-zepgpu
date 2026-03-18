"""Tests for security module."""

import pytest

from deepiri_zepgpu.security.access_control import AccessControl, Quota
from deepiri_zepgpu.security.user_management import UserManager, UserRole
from deepiri_zepgpu.core.task import Task, TaskResources


class TestAccessControl:
    """Test cases for AccessControl."""

    def test_default_quota(self):
        """Test default quota values."""
        access = AccessControl()
        quota = access.get_quota("any_user")
        assert quota.max_tasks == 100
        assert quota.max_gpu_hours == 24

    def test_set_quota(self):
        """Test setting custom quota."""
        access = AccessControl()
        custom_quota = Quota(max_tasks=50, max_gpu_hours=10)
        access.set_quota("user1", custom_quota)
        quota = access.get_quota("user1")
        assert quota.max_tasks == 50

    def test_check_task_submission(self):
        """Test task submission quota check."""
        access = AccessControl(default_quota=Quota(max_tasks=2, max_concurrent_tasks=1))

        def dummy():
            return 1

        task = Task(func=dummy, user_id="user1")

        can_submit, _ = access.check_task_submission("user1", task)
        assert can_submit is True

        access.record_task_start("user1", 1024)
        can_submit, _ = access.check_task_submission("user1", task)
        assert can_submit is False

    def test_record_task_end(self):
        """Test recording task end."""
        access = AccessControl()
        access.record_task_start("user1", 1024)
        access.record_task_end("user1", 100.0)
        usage = access.get_usage("user1")
        assert usage.concurrent_tasks == 0
        assert usage.gpu_seconds == 100.0


class TestUserManager:
    """Test cases for UserManager."""

    def test_create_user(self):
        """Test user creation."""
        users = UserManager()
        user = users.create_user(
            username="testuser",
            email="test@example.com",
            role=UserRole.RESEARCHER,
        )
        assert user.username == "testuser"
        assert user.role == UserRole.RESEARCHER

    def test_get_user(self):
        """Test getting user by ID."""
        users = UserManager()
        created = users.create_user("testuser", "test@example.com")
        retrieved = users.get_user(created.user_id)
        assert retrieved.user_id == created.user_id

    def test_authenticate(self):
        """Test user authentication."""
        users = UserManager()
        users.create_user("testuser", "test@example.com")
        token = users.authenticate("testuser", "password")
        assert token is not None

        user_id = users.verify_token(token)
        assert user_id is not None

    def test_list_users(self):
        """Test listing users."""
        users = UserManager()
        users.create_user("user1", "user1@example.com")
        users.create_user("user2", "user2@example.com", role=UserRole.ADMIN)

        all_users = users.list_users()
        assert len(all_users) == 2

        admins = users.list_users(role=UserRole.ADMIN)
        assert len(admins) == 1

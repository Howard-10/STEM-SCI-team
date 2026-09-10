"""API contracts for users, sessions, and research projects."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IdentityModel(BaseModel):
    """Strict model for identity API boundaries."""

    model_config = ConfigDict(extra="forbid")


class UserCreateRequest(IdentityModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=80)


class LoginRequest(IdentityModel):
    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class TokenRefreshRequest(IdentityModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class UserProfile(IdentityModel):
    user_id: str
    username: str
    email: str
    display_name: str | None = None
    created_at: datetime


class AuthTokenPair(IdentityModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserProfile


class ProjectCreateRequest(IdentityModel):
    project_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=160)
    research_direction: str = Field(min_length=1, max_length=2000)
    abstract: str | None = Field(default=None, max_length=5000)


class ProjectPatchRequest(IdentityModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    research_direction: str | None = Field(default=None, min_length=1, max_length=2000)
    abstract: str | None = Field(default=None, max_length=5000)
    status: Literal["active", "archived"] | None = None


class ProjectMemberUpsertRequest(IdentityModel):
    """Add an existing account to a project with a bounded collaboration role."""

    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    role: Literal["editor", "viewer", "reviewer"]


class ProjectMember(IdentityModel):
    project_id: str
    user_id: str
    username: str
    display_name: str | None = None
    role: Literal["owner", "editor", "viewer", "reviewer"]
    created_at: datetime


class ResearchIntakeState(IdentityModel):
    """Durable clarification state for a project, including deferred fields."""

    project_id: str
    research_topic: str
    status: Literal["COLLECTING", "COMPLETE", "DEFERRED"]
    current_question_key: str | None = None
    answers: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ResearchMemoryState(IdentityModel):
    """Non-blocking research facts accumulated from ordinary conversation."""

    project_id: str
    facts: dict[str, str] = Field(default_factory=dict)
    source_messages: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ResearchProject(IdentityModel):
    project_id: str
    owner_user_id: str
    title: str
    research_direction: str
    abstract: str | None = None
    status: Literal["active", "archived"] = "active"
    role: Literal["owner", "editor", "viewer", "reviewer"] = "owner"
    created_at: datetime
    updated_at: datetime

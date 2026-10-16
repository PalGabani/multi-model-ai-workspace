from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    workspace_name: str = Field(min_length=1, max_length=100)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    display_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=200)
    mode: str = Field(default="chat", pattern="^(chat|compare)$")


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    mode: str
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)
    model_id: str = Field(min_length=1, max_length=160)
    auto_route: bool = False


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    model_id: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int | None
    estimated_cost_usd: float
    status: str
    created_at: datetime


class ModelResponse(BaseModel):
    id: str
    provider_id: str
    label: str
    description: str
    input_cost_per_million: float
    output_cost_per_million: float
    context_window: int
    enabled: bool
    available: bool


class FeedbackCreate(BaseModel):
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=1000)


class WorkspacePreferences(BaseModel):
    default_model_id: str | None = Field(default=None, max_length=160)
    monthly_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    allowed_model_ids: list[str] | None = Field(default=None, max_length=100)

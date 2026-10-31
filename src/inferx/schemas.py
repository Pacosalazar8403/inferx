from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """One message in a conversation."""

    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    """What a client sends to POST /v1/chat/completions."""

    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, ge=1, le=4096)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)


class Usage(BaseModel):
    """Token counts for one request, used later for cost tracking."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Choice(BaseModel):
    """One generated reply."""

    index: int
    message: ChatMessage
    finish_reason: Literal["stop", "length"]


class ChatCompletionResponse(BaseModel):
    """What InferX returns for a chat request."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage
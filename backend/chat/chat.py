"""
WebSocket Chat Routes - Real-time chat interface for multi-agent system

Identity: comes only from a bearer token (``Authorization`` header, or a ``token`` query param
for WebSockets). A client-supplied ``user_id`` is ignored. Callers without a valid token are
anonymous: their pseudo-identity is derived from the session_id, so for anonymous chats the
session_id itself acts as a capability - whoever knows it can read and continue that session.
Authenticated sessions are owned by their user and cannot be accessed by anyone else.
"""
import json
import asyncio
import logging
import uuid
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Try both import patterns
try:
    from backend.chat.orchestrator import get_chat_orchestrator, ChatOrchestrator
    from backend.chat.autogen_setup import get_model_client
except ImportError:
    from chat.orchestrator import get_chat_orchestrator, ChatOrchestrator
    from chat.autogen_setup import get_model_client

from autogen_core.models import UserMessage, AssistantMessage, SystemMessage

from backend.auth.security import anonymous_identity, optional_user, user_from_token
from backend.utils.json_safe import make_json_safe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Chat"])


# ============================================================================
# MODELS
# ============================================================================

class ChatMessage(BaseModel):
    """Request model for REST chat endpoint"""
    message: str = Field(..., description="User message")
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")
    user_id: Optional[str] = Field(
        default=None,
        description="Deprecated and ignored: identity comes from the bearer token only",
    )


class ChatResponse(BaseModel):
    """Response model for REST chat endpoint"""
    session_id: str
    responses: list
    timestamp: str


# ============================================================================
# CONNECTION MANAGER
# ============================================================================

class ConnectionManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
    
    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
    
    async def send_message(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_json(message)
    
    async def broadcast(self, message: dict):
        for ws in self.active_connections.values():
            await ws.send_json(message)


manager = ConnectionManager()
general_manager = ConnectionManager()

# Session memory for general chat
_general_sessions: dict[str, list] = {}
_GENERAL_SYSTEM_PROMPT = (
    "You are a helpful, general-purpose assistant. "
    "Be concise, clear, and friendly. If the user asks for financial guidance, "
    "offer balanced considerations and ask clarifying questions about goals and risk tolerance."
)


def _identity_for(token: Optional[str], session_id: str) -> str:
    """Authenticated user id from the token, else a per-session anonymous identity."""
    return user_from_token(token) or anonymous_identity(session_id)


def _ws_token(websocket: WebSocket, token: Optional[str]) -> Optional[str]:
    """Bearer token for a WebSocket: ``token`` query param, else the Authorization header."""
    if token:
        return token
    header = websocket.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _general_key(identity: str, session_id: str) -> str:
    """General-chat memory is namespaced by identity so session ids cannot cross users."""
    return f"{identity}:{session_id}"


async def _get_general_response(session_id: str, user_message: str, identity: str) -> tuple[str, str]:
    client, provider = get_model_client()
    if not client:
        return "LLM not configured. Set GEMINI_API_KEY, GROQ_API_KEY, or OPENAI_API_KEY.", "none"

    key = _general_key(identity, session_id)
    history = _general_sessions.get(key)
    if not history:
        history = [SystemMessage(content=_GENERAL_SYSTEM_PROMPT, source="system")]
        _general_sessions[key] = history

    history.append(UserMessage(content=user_message, source="user"))

    try:
        result = await client.create(messages=history)
        content = result.content if isinstance(result.content, str) else str(result.content)
    except Exception:
        logger.exception("General chat failed")
        content = "⚠️ Chat request failed. Please try again."

    history.append(AssistantMessage(content=content, source="assistant"))

    # Keep system + recent history
    if len(history) > 21:
        _general_sessions[key] = [history[0]] + history[-20:]

    return content, provider


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================

@router.websocket("/ws")
async def websocket_chat(
    websocket: WebSocket,
    session_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),  # deprecated, ignored: identity comes from the token
):
    """
    WebSocket endpoint for real-time chat.
    
    Connect: ws://localhost:8000/api/chat/ws?session_id=xxx&token=<bearer token>
    (the token is optional; without a valid one the chat is anonymous and unpersonalised.
    A user_id query parameter is ignored.)
    
    Send: {"message": "What's happening with AAPL?"}
    
    Receive: {"type": "text|thinking|result|confirmation|error", "content": "...", "metadata": {...}}
    """
    # Generate session ID if not provided
    if not session_id:
        session_id = str(uuid.uuid4())

    identity = _identity_for(_ws_token(websocket, token), session_id)
    orchestrator = get_chat_orchestrator()
    if not orchestrator.session_accessible(session_id, identity):
        await websocket.close(code=1008)  # policy violation: session belongs to someone else
        return

    await manager.connect(websocket, session_id)
    
    # Send welcome message
    await websocket.send_json({
        "type": "system",
        "content": f"👋 Connected! Session: {session_id[:8]}...\n\nI'm your financial AI assistant. I can help with:\n• 📊 **Stock Analysis** - Price, fundamentals, news\n• 🧠 **Emotional Check** - Detect panic/FOMO trading\n• 💰 **Wealth Advice** - Portfolio allocation\n\nJust tell me what you need!",
        "metadata": {"session_id": session_id}
    })
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            
            try:
                message_data = json.loads(data)
                user_message = message_data.get("message", data)
            except json.JSONDecodeError:
                user_message = data
            
            if not user_message.strip():
                continue
            
            # Echo user message
            await websocket.send_json({
                "type": "user",
                "content": user_message,
                "metadata": {"timestamp": datetime.now().isoformat()}
            })
            
            # Process through orchestrator
            async for response in orchestrator.process_message(
                session_id=session_id,
                user_message=user_message,
                user_id=identity
            ):
                await websocket.send_json(make_json_safe(response))
            
    except WebSocketDisconnect:
        manager.disconnect(session_id)
        # Optionally clean up conversation
        # orchestrator.clear_conversation(session_id)


@router.websocket("/ws-general")
async def websocket_general_chat(
    websocket: WebSocket,
    session_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),  # deprecated, ignored: identity comes from the token
):
    """
    WebSocket endpoint for general chat (non-pipeline).
    
    Connect: ws://localhost:8000/api/chat/ws-general?session_id=xxx&token=<bearer token>
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    identity = _identity_for(_ws_token(websocket, token), session_id)

    await general_manager.connect(websocket, session_id)

    await websocket.send_json({
        "type": "system",
        "content": f"👋 General chat connected. Session: {session_id[:8]}...",
        "metadata": {"session_id": session_id, "mode": "general"}
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
                user_message = message_data.get("message", data)
            except json.JSONDecodeError:
                user_message = data

            if not user_message.strip():
                continue

            await websocket.send_json({
                "type": "user",
                "content": user_message,
                "metadata": {"timestamp": datetime.now().isoformat()}
            })

            await websocket.send_json({
                "type": "thinking",
                "content": "Thinking...",
                "metadata": {"mode": "general"}
            })

            response_text, provider = await _get_general_response(session_id, user_message, identity)

            await websocket.send_json(make_json_safe({
                "type": "result",
                "content": response_text,
                "metadata": {"mode": "general", "provider": provider}
            }))

    except WebSocketDisconnect:
        general_manager.disconnect(session_id)


# ============================================================================
# REST FALLBACK ENDPOINTS
# ============================================================================

@router.post("/message", response_model=ChatResponse)
async def send_chat_message(request: ChatMessage, auth_user: Optional[str] = Depends(optional_user)):
    """
    REST endpoint for chat (non-streaming fallback).
    
    For real-time experience, use the WebSocket endpoint instead.
    Identity comes from the bearer token only (anonymous without one); request.user_id is ignored.
    """
    session_id = request.session_id or str(uuid.uuid4())
    identity = auth_user or anonymous_identity(session_id)
    orchestrator = get_chat_orchestrator()
    if not orchestrator.session_accessible(session_id, identity):
        raise HTTPException(status_code=403, detail="Session belongs to another user")
    
    responses = []
    async for response in orchestrator.process_message(
        session_id=session_id,
        user_message=request.message,
        user_id=identity
    ):
        responses.append(response)
    
    return ChatResponse(
        session_id=session_id,
        responses=responses,
        timestamp=datetime.now().isoformat()
    )


@router.get("/history/{session_id}")
async def get_chat_history(session_id: str, auth_user: Optional[str] = Depends(optional_user)):
    """Get conversation history for a session (only the owner's; others see an empty history)"""
    orchestrator = get_chat_orchestrator()
    identity = auth_user or anonymous_identity(session_id)
    history = orchestrator.get_conversation_history(session_id, user_id=identity)
    
    return {
        "session_id": session_id,
        "messages": history,
        "count": len(history)
    }


@router.delete("/history/{session_id}")
async def clear_chat_history(session_id: str, auth_user: Optional[str] = Depends(optional_user)):
    """Clear conversation history for a session (only the owner can clear it)"""
    orchestrator = get_chat_orchestrator()
    orchestrator.clear_conversation(session_id, user_id=auth_user or anonymous_identity(session_id))
    
    return {"message": f"Conversation {session_id} cleared"}


@router.get("/general/history/{session_id}")
async def get_general_chat_history(session_id: str, auth_user: Optional[str] = Depends(optional_user)):
    """Get general chat history for a session (namespaced by caller identity)"""
    identity = auth_user or anonymous_identity(session_id)
    history = _general_sessions.get(_general_key(identity, session_id), [])
    messages = []
    for m in history:
        if isinstance(m, SystemMessage):
            continue
        messages.append({
            "role": "user" if isinstance(m, UserMessage) else "assistant",
            "content": m.content
        })
    return {"session_id": session_id, "messages": messages, "count": len(messages)}


@router.delete("/general/history/{session_id}")
async def clear_general_chat_history(session_id: str, auth_user: Optional[str] = Depends(optional_user)):
    """Clear general chat history for a session (namespaced by caller identity)"""
    _general_sessions.pop(_general_key(auth_user or anonymous_identity(session_id), session_id), None)
    return {"message": f"General conversation {session_id} cleared"}


@router.get("/sessions")
async def list_active_sessions(auth_user: Optional[str] = Depends(optional_user)):
    """List the authenticated caller's active chat sessions (anonymous callers see none)"""
    orchestrator = get_chat_orchestrator()
    
    sessions = []
    for sid, ctx in orchestrator.conversations.items():
        if not auth_user or ctx.user_id != auth_user:
            continue
        sessions.append({
            "session_id": sid,
            "user_id": ctx.user_id,
            "state": ctx.state.value,
            "message_count": len(ctx.messages),
            "current_ticker": ctx.current_intent.detected_ticker if ctx.current_intent else None
        })
    
    return {"sessions": sessions, "count": len(sessions)}

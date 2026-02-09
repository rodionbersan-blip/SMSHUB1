from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List
from uuid import uuid4

from cachebot.models.chat import ChatMessage
from cachebot.storage import StateRepository


class ChatService:
    def __init__(self, repository: StateRepository) -> None:
        self._repository = repository
        snapshot = repository.snapshot()
        self._chats: Dict[str, List[ChatMessage]] = {
            deal_id: list(messages) for deal_id, messages in snapshot.chats.items()
        }
        self._lock = asyncio.Lock()

    async def list_messages(self, deal_id: str) -> List[ChatMessage]:
        async with self._lock:
            return list(self._chats.get(deal_id, []))

    async def latest_message_at(self, deal_id: str) -> datetime | None:
        async with self._lock:
            messages = self._chats.get(deal_id, [])
            if not messages:
                return None
            return messages[-1].created_at

    async def latest_message(self, deal_id: str) -> ChatMessage | None:
        async with self._lock:
            messages = self._chats.get(deal_id, [])
            if not messages:
                return None
            return messages[-1]

    async def add_message(
        self,
        *,
        deal_id: str,
        sender_id: int,
        text: str | None,
        file_path: str | None,
        file_name: str | None,
        system: bool = False,
        recipient_id: int | None = None,
    ) -> ChatMessage:
        async with self._lock:
            msg = ChatMessage(
                id=str(uuid4()),
                deal_id=deal_id,
                sender_id=sender_id,
                text=text,
                file_path=file_path,
                file_name=file_name,
                created_at=datetime.now(timezone.utc),
                system=system,
                recipient_id=recipient_id,
            )
            bucket = self._chats.setdefault(deal_id, [])
            bucket.append(msg)
            await self._repository.persist_chats(self._chats)
            return msg

    async def list_messages_for_user(
        self,
        deal_id: str,
        user_id: int,
        *,
        include_all: bool = False,
    ) -> List[ChatMessage]:
        async with self._lock:
            messages = list(self._chats.get(deal_id, []))
        if include_all:
            return messages
        return [
            msg
            for msg in messages
            if msg.recipient_id is None or msg.recipient_id == user_id
        ]

    async def latest_message_for_user(
        self,
        deal_id: str,
        user_id: int,
        *,
        include_all: bool = False,
    ) -> ChatMessage | None:
        messages = await self.list_messages_for_user(deal_id, user_id, include_all=include_all)
        return messages[-1] if messages else None

    async def purge_chat(self, deal_id: str) -> None:
        async with self._lock:
            if deal_id in self._chats:
                self._chats.pop(deal_id, None)
                await self._repository.persist_chats(self._chats)

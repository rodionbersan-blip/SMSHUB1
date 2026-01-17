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
            )
            bucket = self._chats.setdefault(deal_id, [])
            bucket.append(msg)
            await self._repository.persist_chats(self._chats)
            return msg

    async def purge_chat(self, deal_id: str) -> None:
        async with self._lock:
            if deal_id in self._chats:
                self._chats.pop(deal_id, None)
                await self._repository.persist_chats(self._chats)

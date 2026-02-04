from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from cachebot.models.user import ApplicationStatus, MerchantApplication, UserProfile, UserRole
from cachebot.storage import StateRepository


@dataclass(slots=True)
class MerchantRecord:
    user_id: int
    profile: UserProfile | None
    merchant_since: datetime | None


class UserService:
    def __init__(self, repository: StateRepository, admin_ids: set[int] | None = None) -> None:
        self._repository = repository
        snapshot = repository.snapshot()
        self._roles: Dict[int, str] = snapshot.user_roles.copy()
        self._applications: List[MerchantApplication] = list(snapshot.applications)
        self._profiles: Dict[int, UserProfile] = snapshot.profiles.copy()
        self._merchant_since: Dict[int, datetime] = {
            uid: datetime.fromisoformat(value) for uid, value in snapshot.merchant_since.items()
        }
        self._moderators = set(snapshot.moderators)
        self._admins = set(getattr(snapshot, "admins", []))
        if admin_ids:
            self._admins.update(admin_ids)
        self._warnings: Dict[int, int] = getattr(snapshot, "user_warnings", {}).copy()
        self._banned = set(getattr(snapshot, "user_bans", []))
        self._deal_blocks = set(getattr(snapshot, "user_deal_blocks", []))
        self._ban_until: Dict[int, datetime] = {
            int(uid): datetime.fromisoformat(value)
            for uid, value in (getattr(snapshot, "user_ban_until", {}) or {}).items()
        }
        self._deal_block_until: Dict[int, datetime] = {
            int(uid): datetime.fromisoformat(value)
            for uid, value in (getattr(snapshot, "user_deal_block_until", {}) or {}).items()
        }
        self._admin_actions: List[dict] = list(getattr(snapshot, "admin_actions", []))
        self._lock = asyncio.Lock()
        now = datetime.now(timezone.utc)
        for uid, role in self._roles.items():
            if role == UserRole.BUYER.value and uid not in self._merchant_since:
                self._merchant_since[uid] = now

    async def set_role(self, user_id: int, role: UserRole, *, revoke_merchant: bool = False) -> None:
        async with self._lock:
            previous = self._roles.get(user_id)
            self._roles[user_id] = role.value
            if role == UserRole.BUYER:
                if previous != UserRole.BUYER.value or user_id not in self._merchant_since:
                    self._merchant_since[user_id] = datetime.now(timezone.utc)
            else:
                if revoke_merchant:
                    self._merchant_since.pop(user_id, None)
            await self._persist()

    async def role_of(self, user_id: int) -> UserRole | None:
        async with self._lock:
            value = self._roles.get(user_id)
        return UserRole(value) if value else None

    async def add_application(self, application: MerchantApplication) -> MerchantApplication:
        async with self._lock:
            self._applications.append(application)
            await self._persist()
            return application

    async def list_applications(self) -> List[MerchantApplication]:
        async with self._lock:
            return list(self._applications)

    async def get_application(self, app_id: str) -> Optional[MerchantApplication]:
        async with self._lock:
            for app in self._applications:
                if app.id == app_id:
                    return app
        return None

    async def update_application_status(
        self, app_id: str, status: ApplicationStatus
    ) -> Optional[MerchantApplication]:
        async with self._lock:
            for index, app in enumerate(self._applications):
                if app.id == app_id:
                    updated = MerchantApplication(
                        id=app.id,
                        user_id=app.user_id,
                        username=app.username,
                        banks=app.banks,
                        uses_personal_bank=app.uses_personal_bank,
                        accepts_risk=app.accepts_risk,
                        photo_file_ids=app.photo_file_ids,
                        created_at=app.created_at,
                        status=status,
                    )
                    self._applications.pop(index)
                    await self._persist()
                    return updated
        return None

    async def ensure_profile(
        self, user_id: int, *, full_name: str | None, username: str | None
    ) -> UserProfile:
        now = datetime.now(timezone.utc)
        async with self._lock:
            profile = self._profiles.get(user_id)
            display_name = profile.display_name if profile else None
            if not display_name:
                display_name = _random_display_name()
            if not profile:
                profile = UserProfile(
                    user_id=user_id,
                    full_name=full_name,
                    username=username,
                    display_name=display_name,
                    avatar_path=None,
                    registered_at=now,
                    last_seen_at=now,
                    nickname_changed_at=now,
                )
            else:
                profile = UserProfile(
                    user_id=user_id,
                    full_name=full_name if full_name is not None else profile.full_name,
                    username=username if username is not None else profile.username,
                    display_name=display_name,
                    avatar_path=profile.avatar_path,
                    registered_at=profile.registered_at,
                    last_seen_at=now,
                    nickname_changed_at=profile.nickname_changed_at,
                )
            self._profiles[user_id] = profile
            await self._persist()
            return profile

    async def update_profile(
        self,
        user_id: int,
        *,
        display_name: str | None = None,
        avatar_path: str | None = None,
    ) -> UserProfile:
        async with self._lock:
            profile = self._profiles.get(user_id)
            if not profile:
                profile = UserProfile(
                    user_id=user_id,
                    full_name=None,
                    username=None,
                    display_name=_random_display_name(),
                    avatar_path=None,
                    registered_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                )
            profile = UserProfile(
                user_id=profile.user_id,
                full_name=profile.full_name,
                username=profile.username,
                display_name=display_name or profile.display_name,
                avatar_path=avatar_path if avatar_path is not None else profile.avatar_path,
                registered_at=profile.registered_at,
                last_seen_at=profile.last_seen_at,
                nickname_changed_at=profile.nickname_changed_at,
            )
            if display_name and display_name != profile.display_name:
                profile.nickname_changed_at = datetime.now(timezone.utc)
            self._profiles[user_id] = profile
            await self._persist()
            return profile

    async def profile_of(self, user_id: int) -> UserProfile | None:
        async with self._lock:
            return self._profiles.get(user_id)

    async def profile_by_username(self, username: str) -> UserProfile | None:
        needle = username.lstrip("@").lower()
        async with self._lock:
            for profile in self._profiles.values():
                if profile.username and profile.username.lower() == needle:
                    return profile
        return None

    async def search_user_ids(self, query: str) -> List[int]:
        needle = (query or "").strip().lower()
        if not needle:
            return []
        async with self._lock:
            profiles = list(self._profiles.values())
        matched: List[int] = []
        for profile in profiles:
            username = (profile.username or "").lower()
            display = (profile.display_name or "").lower()
            full = (profile.full_name or "").lower()
            if needle in username or needle in display or needle in full:
                matched.append(profile.user_id)
        return matched

    async def is_moderator(self, user_id: int) -> bool:
        async with self._lock:
            return user_id in self._moderators

    async def add_moderator(self, user_id: int) -> None:
        async with self._lock:
            self._moderators.add(user_id)
            await self._persist()

    async def remove_moderator(self, user_id: int) -> None:
        async with self._lock:
            self._moderators.discard(user_id)
            await self._persist()

    async def list_moderators(self) -> List[int]:
        async with self._lock:
            return sorted(self._moderators)

    def is_admin_cached(self, user_id: int) -> bool:
        return user_id in self._admins

    async def list_admins(self) -> List[int]:
        async with self._lock:
            return sorted(self._admins)

    async def add_admin(self, user_id: int) -> None:
        async with self._lock:
            self._admins.add(user_id)
            await self._persist()

    async def remove_admin(self, user_id: int) -> None:
        async with self._lock:
            self._admins.discard(user_id)
            await self._persist()

    async def list_merchants(self) -> List[MerchantRecord]:
        async with self._lock:
            records = [
                MerchantRecord(
                    user_id=uid,
                    profile=self._profiles.get(uid),
                    merchant_since=self._merchant_since.get(uid),
                )
                for uid, role in self._roles.items()
                if role == UserRole.BUYER.value
            ]
        records.sort(key=lambda rec: rec.merchant_since or datetime.min.replace(tzinfo=timezone.utc))
        return records

    def _refresh_expiries(self) -> bool:
        now = datetime.now(timezone.utc)
        expired_bans = [uid for uid, until in self._ban_until.items() if until <= now]
        for uid in expired_bans:
            self._ban_until.pop(uid, None)
        expired_blocks = [uid for uid, until in self._deal_block_until.items() if until <= now]
        for uid in expired_blocks:
            self._deal_block_until.pop(uid, None)
        return bool(expired_bans or expired_blocks)

    async def moderation_status(self, user_id: int) -> dict[str, int | bool]:
        async with self._lock:
            expired = self._refresh_expiries()
            if expired:
                await self._persist()
            return {
                "warnings": int(self._warnings.get(user_id, 0)),
                "banned": user_id in self._banned or user_id in self._ban_until,
                "deals_blocked": user_id in self._deal_blocks or user_id in self._deal_block_until,
            }

    async def add_warning(self, user_id: int) -> dict[str, int | bool]:
        async with self._lock:
            count = int(self._warnings.get(user_id, 0)) + 1
            self._warnings[user_id] = count
            if count >= 3:
                self._banned.add(user_id)
                self._deal_blocks.add(user_id)
                self._ban_until.pop(user_id, None)
                self._deal_block_until.pop(user_id, None)
            await self._persist()
            return {
                "warnings": count,
                "banned": user_id in self._banned or user_id in self._ban_until,
                "deals_blocked": user_id in self._deal_blocks or user_id in self._deal_block_until,
            }

    async def set_banned(
        self, user_id: int, banned: bool, *, until: datetime | None = None
    ) -> dict[str, int | bool]:
        async with self._lock:
            if banned:
                if until:
                    self._ban_until[user_id] = until
                else:
                    self._banned.add(user_id)
                self._deal_blocks.add(user_id)
            else:
                self._banned.discard(user_id)
                self._ban_until.pop(user_id, None)
                self._warnings.pop(user_id, None)
            await self._persist()
            return {
                "warnings": int(self._warnings.get(user_id, 0)),
                "banned": user_id in self._banned or user_id in self._ban_until,
                "deals_blocked": user_id in self._deal_blocks or user_id in self._deal_block_until,
            }

    async def set_deal_blocked(
        self, user_id: int, blocked: bool, *, until: datetime | None = None
    ) -> dict[str, int | bool]:
        async with self._lock:
            if blocked:
                if until:
                    self._deal_block_until[user_id] = until
                else:
                    self._deal_blocks.add(user_id)
            else:
                self._deal_blocks.discard(user_id)
                self._deal_block_until.pop(user_id, None)
            await self._persist()
            return {
                "warnings": int(self._warnings.get(user_id, 0)),
                "banned": user_id in self._banned or user_id in self._ban_until,
                "deals_blocked": user_id in self._deal_blocks or user_id in self._deal_block_until,
            }

    async def can_trade(self, user_id: int) -> bool:
        async with self._lock:
            expired = self._refresh_expiries()
            if expired:
                await self._persist()
            if user_id in self._banned or user_id in self._ban_until:
                return False
            if user_id in self._deal_blocks or user_id in self._deal_block_until:
                return False
            return True

    async def has_merchant_access(self, user_id: int) -> bool:
        async with self._lock:
            if self._roles.get(user_id) == UserRole.BUYER.value:
                return True
            return user_id in self._merchant_since

    async def merchant_since_of(self, user_id: int) -> datetime | None:
        async with self._lock:
            return self._merchant_since.get(user_id)

    async def log_admin_action(self, action: dict) -> None:
        async with self._lock:
            self._admin_actions.append(action)
            if len(self._admin_actions) > 200:
                self._admin_actions = self._admin_actions[-200:]
            await self._repository.persist_admin_actions(list(self._admin_actions))

    async def list_admin_actions(self) -> List[dict]:
        async with self._lock:
            return list(self._admin_actions)

    async def _persist(self) -> None:
        await self._repository.persist_user_data(
            roles=self._roles.copy(),
            applications=list(self._applications),
            profiles=self._profiles.copy(),
            merchant_since={uid: value.isoformat() for uid, value in self._merchant_since.items()},
            moderators=sorted(self._moderators),
            admins=sorted(self._admins),
            user_warnings=self._warnings.copy(),
            user_bans=sorted(self._banned),
            user_deal_blocks=sorted(self._deal_blocks),
            user_ban_until={uid: value.isoformat() for uid, value in self._ban_until.items()},
            user_deal_block_until={
                uid: value.isoformat() for uid, value in self._deal_block_until.items()
            },
        )


def _random_display_name() -> str:
    adjectives = [
        "Swift",
        "Calm",
        "Bright",
        "Bold",
        "Quick",
        "Silent",
        "Nova",
        "Sunny",
        "Lucky",
        "Cool",
    ]
    nouns = [
        "Fox",
        "Wolf",
        "Eagle",
        "Lynx",
        "Hawk",
        "Bear",
        "Otter",
        "Kite",
        "Raven",
        "Star",
    ]
    return f"{random.choice(adjectives)} {random.choice(nouns)}"

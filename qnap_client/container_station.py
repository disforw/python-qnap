"""Container Station async client for QNAP NAS.

Uses the QNAP Container Station REST API:
- v3 API (list containers): QTS SID as Bearer token
- v1 API (start/stop/restart): CS_SESS_ID cookie via separate CS login
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from .exceptions import QnapAPIError, QnapAuthError, QnapConnectionError
from .models import Container

if TYPE_CHECKING:
    from .client import QnapClient

_LOGGER = logging.getLogger(__name__)


class ContainerStationClient:
    """Client for QNAP Container Station API.

    Requires an authenticated QnapClient instance — reuses its aiohttp
    session and host/port/ssl configuration.

    Usage::

        async with QnapClient(...) as client:
            cs = ContainerStationClient(client)
            containers = await cs.get_containers()
            await cs.stop_container("my-container-id", "docker")
    """

    def __init__(self, client: QnapClient) -> None:
        """Initialize using an authenticated QnapClient."""
        self._client = client
        self._cs_session_cookie: str | None = None

        scheme = "https" if client._ssl else "http"  # noqa: SLF001
        base = f"{scheme}://{client._host}:{client._port}/container-station/api"  # noqa: SLF001
        self._base_v3 = f"{base}/v3"
        self._base_v1 = f"{base}/v1"

    # ------------------------------------------------------------------
    # CS cookie auth (for v1 action endpoints)
    # ------------------------------------------------------------------

    async def _ensure_cs_auth(self) -> str:
        """Return a valid CS_SESS_ID cookie, logging in if needed."""
        if self._cs_session_cookie:
            return self._cs_session_cookie

        session = await self._client._ensure_session()  # noqa: SLF001
        try:
            async with session.post(
                f"{self._base_v1}/login",
                json={
                    "username": self._client._username,  # noqa: SLF001
                    "password": self._client._password_b64,  # noqa: SLF001
                },
            ) as resp:
                if resp.status != 200:
                    raise QnapAuthError(
                        f"Container Station login failed: HTTP {resp.status}"
                    )
                cookie = resp.cookies.get("CS_SESS_ID")
                if not cookie:
                    body = await resp.text()
                    raise QnapAuthError(
                        f"Container Station login: no session cookie returned. Body: {body[:200]}"
                    )
                self._cs_session_cookie = cookie.value
                return self._cs_session_cookie
        except aiohttp.ClientConnectorError as err:
            raise QnapConnectionError(
                f"Cannot connect to Container Station: {err}"
            ) from err

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_containers(self) -> list[Container]:
        """Return all containers with id, name, status, image, type.

        Uses the v3 API with the QTS SID (Bearer token) from the parent
        QnapClient — no separate Container Station login needed.

        Returns:
            List of Container dataclasses.

        Raises:
            QnapAuthError: If not authenticated.
            QnapAPIError: On bad response.
        """
        if self._client._sid is None:  # noqa: SLF001
            raise QnapAuthError("QnapClient is not authenticated")

        session = await self._client._ensure_session()  # noqa: SLF001
        headers = {"Authorization": f"Bearer {self._client._sid}"}  # noqa: SLF001

        try:
            async with session.get(
                f"{self._base_v3}/containers",
                headers=headers,
            ) as resp:
                if resp.status == 401:
                    raise QnapAuthError("Container Station: Bearer token rejected")
                if resp.status != 200:
                    raise QnapAPIError(
                        f"Container Station list failed: HTTP {resp.status}"
                    )
                data: dict[str, Any] = await resp.json()
        except aiohttp.ClientConnectorError as err:
            raise QnapConnectionError(
                f"Cannot connect to Container Station: {err}"
            ) from err

        items_raw: list[dict[str, Any]] = data.get("data", {}).get("items", [])
        return [
            Container(
                id=c.get("id", ""),
                name=c.get("name", ""),
                state=c.get("status", c.get("state", "")),
                image=c.get("image", ""),
                type=c.get("type", "docker"),
            )
            for c in items_raw
        ]

    async def container_action(
        self, container_id: str, container_type: str, action: str
    ) -> None:
        """Perform an action on a container.

        Args:
            container_id: Container ID from get_containers().
            container_type: "docker" or "lxc".
            action: "start", "stop", or "restart".

        Raises:
            ValueError: If action is not valid.
            QnapAuthError: If authentication fails.
            QnapAPIError: If the action fails.
        """
        if action not in ("start", "stop", "restart"):
            raise ValueError(f"Invalid container action: {action!r}. Must be start, stop, or restart.")

        cookie = await self._ensure_cs_auth()
        session = await self._client._ensure_session()  # noqa: SLF001
        url = f"{self._base_v1}/container/{container_type}/{container_id}/{action}"
        headers = {"Cookie": f"CS_SESS_ID={cookie}"}

        async with session.put(url, headers=headers) as resp:
            if resp.status == 401:
                # Session expired — clear and retry once
                self._cs_session_cookie = None
                cookie = await self._ensure_cs_auth()
                headers = {"Cookie": f"CS_SESS_ID={cookie}"}
                async with session.put(url, headers=headers) as retry_resp:
                    if retry_resp.status not in (200, 204):
                        raise QnapAPIError(
                            f"Container {action} failed after retry: HTTP {retry_resp.status}"
                        )
                return

            if resp.status not in (200, 204):
                raise QnapAPIError(
                    f"Container {action} failed: HTTP {resp.status}"
                )

    async def start_container(self, container_id: str, container_type: str = "docker") -> None:
        """Start a container."""
        await self.container_action(container_id, container_type, "start")

    async def stop_container(self, container_id: str, container_type: str = "docker") -> None:
        """Stop a container."""
        await self.container_action(container_id, container_type, "stop")

    async def restart_container(self, container_id: str, container_type: str = "docker") -> None:
        """Restart a container."""
        await self.container_action(container_id, container_type, "restart")

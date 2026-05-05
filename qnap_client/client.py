"""Main QnapClient — async Python client for QNAP NAS."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import aiohttp
import xmltodict

from .exceptions import (
    QnapAPIError,
    QnapAuthError,
    QnapConnectionError,
    QnapTimeoutError,
)
from .models import (
    CpuStats,
    DriveHealth,
    ExternalDrive,
    FanStatus,
    FirmwareUpdate,
    MemoryStats,
    NasData,
    NetworkInterface,
    SystemHealth,
    SystemInfo,
    VolumeStats,
)

_LOGGER = logging.getLogger(__name__)


class QnapClient:
    """Async client for the QNAP NAS CGI API.

    Designed for use in Home Assistant custom integrations but general-purpose.

    Usage::

        async with QnapClient("192.168.1.10", 8080, "admin", "pass") as client:
            data = await client.get_all()
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        ssl: bool = False,
        verify_ssl: bool = True,
        timeout: int = 10,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._ssl = ssl
        self._verify_ssl = verify_ssl
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._provided_session = session

        self._scheme = "https" if ssl else "http"
        self._base = f"{self._scheme}://{host}:{port}"
        self._session: aiohttp.ClientSession | None = None
        self._sid: str | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "QnapClient":
        await self._ensure_session()
        await self.login()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.logout()
        if self._provided_session is None and self._session is not None:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Session / auth
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._provided_session is not None:
            return self._provided_session
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
            self._session = aiohttp.ClientSession(
                connector=connector, timeout=self._timeout
            )
        return self._session

    @property
    def _active_session(self) -> aiohttp.ClientSession:
        session = self._provided_session or self._session
        if session is None or session.closed:
            raise QnapConnectionError("No active HTTP session — call login() first")
        return session

    async def login(self) -> None:
        """Authenticate and store the session ID (authSid)."""
        session = await self._ensure_session()
        pwd_b64 = base64.b64encode(self._password.encode()).decode()
        url = f"{self._base}/cgi-bin/authLogin.cgi"
        data = {"user": self._username, "pwd": pwd_b64}
        try:
            async with session.post(url, data=data) as resp:
                text = await resp.text()
        except aiohttp.ClientConnectorError as exc:
            raise QnapConnectionError(f"Cannot connect to {self._base}: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise QnapTimeoutError(f"Login timed out for {self._base}") from exc

        parsed = self._parse_xml(text)
        auth_passed = parsed.get("QDocRoot", {}).get("authPassed", "0")
        if str(auth_passed) != "1":
            raise QnapAuthError("Login failed — check username and password")

        sid = parsed.get("QDocRoot", {}).get("authSid")
        if not sid:
            raise QnapAuthError("Login succeeded but no authSid in response")

        self._sid = sid
        _LOGGER.debug("Logged in; sid=%s", self._sid)

    async def logout(self) -> None:
        """Invalidate the current session."""
        if self._sid is None:
            return
        try:
            await self._get("/cgi-bin/authLogin.cgi", params={"logout": "1"})
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._sid = None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, str] | None = None) -> str:
        """GET a URL, appending the session SID, return response text."""
        if self._sid is None:
            raise QnapAuthError("Not logged in — call login() first")
        all_params = dict(params or {})
        all_params["sid"] = self._sid

        url = f"{self._base}{path}"
        try:
            async with self._active_session.get(url, params=all_params) as resp:
                if resp.status == 401:
                    self._sid = None
                    raise QnapAuthError("Session expired (HTTP 401)")
                resp.raise_for_status()
                return await resp.text()
        except aiohttp.ClientConnectorError as exc:
            raise QnapConnectionError(f"Connection error: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise QnapTimeoutError("Request timed out") from exc

    @staticmethod
    def _parse_xml(text: str) -> dict[str, Any]:
        try:
            return xmltodict.parse(text)  # type: ignore[no-any-return]
        except Exception as exc:
            raise QnapAPIError(f"Failed to parse XML response: {exc}") from exc

    def _root(self, text: str) -> dict[str, Any]:
        return self._parse_xml(text).get("QDocRoot", {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_system_info(self) -> SystemInfo:
        """Return basic NAS system information."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi", {"subfunc": "sysinfo"}
        )
        root = self._root(text)

        model = root.get("model", {})
        uptime_raw = root.get("uptime", "0")
        try:
            uptime_seconds = int(uptime_raw)
        except (ValueError, TypeError):
            uptime_seconds = 0

        return SystemInfo(
            model=model.get("displayModelName", ""),
            name=root.get("hostname", ""),
            serial_number=root.get("serialNumber", ""),
            firmware_version=root.get("version", ""),
            uptime_seconds=uptime_seconds,
        )

    async def get_system_health(self) -> SystemHealth:
        """Return overall system health status."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi",
            {"subfunc": "sysinfo", "sysHealth": "1"},
        )
        root = self._root(text)
        status = root.get("sysHealth", {}).get("status", "Unknown")
        return SystemHealth(status=status)

    async def get_cpu_stats(self) -> CpuStats:
        """Return current CPU usage percentage."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi", {"subfunc": "sysinfo"}
        )
        root = self._root(text)
        cpu_usage_str = root.get("cpu", {}).get("cpu_usage", "0")
        try:
            cpu_usage = float(str(cpu_usage_str).rstrip("%"))
        except (ValueError, TypeError):
            cpu_usage = 0.0
        return CpuStats(usage_percent=cpu_usage)

    async def get_memory_stats(self) -> MemoryStats:
        """Return RAM stats in megabytes."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi", {"subfunc": "sysinfo"}
        )
        root = self._root(text)
        mem = root.get("memory_status", {})

        def _mb(key: str) -> int:
            raw = mem.get(key, "0")
            try:
                return int(raw)
            except (ValueError, TypeError):
                return 0

        total = _mb("total")
        free = _mb("free")
        used = total - free if total >= free else _mb("used")
        return MemoryStats(total_mb=total, free_mb=free, used_mb=used)

    async def get_network_interfaces(self) -> list[NetworkInterface]:
        """Return stats for all active network interfaces."""
        text = await self._get(
            "/cgi-bin/management/chartReq.cgi",
            {"chart_func": "net_usage", "disk_select": "all"},
        )
        root = self._root(text)
        ifaces_raw = root.get("net", {})
        results: list[NetworkInterface] = []

        if not isinstance(ifaces_raw, dict):
            return results

        for key, val in ifaces_raw.items():
            if not isinstance(val, dict):
                continue
            try:
                results.append(
                    NetworkInterface(
                        name=key,
                        mac=val.get("mac", ""),
                        ip=val.get("ip", ""),
                        rx_bytes_per_sec=float(val.get("rx", 0)),
                        tx_bytes_per_sec=float(val.get("tx", 0)),
                    )
                )
            except (ValueError, TypeError) as exc:
                _LOGGER.debug("Skipping interface %s: %s", key, exc)

        return results

    async def get_drive_health(self) -> list[DriveHealth]:
        """Return SMART/health info for all drives."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi",
            {"subfunc": "sysinfo", "hd_smart": "1"},
        )
        root = self._root(text)
        drives_raw = root.get("func", {}).get("ownContent", {}).get("hdList", {}).get("hdInfo", [])

        if isinstance(drives_raw, dict):
            drives_raw = [drives_raw]

        results: list[DriveHealth] = []
        for i, drive in enumerate(drives_raw):
            if not isinstance(drive, dict):
                continue
            temp_raw = drive.get("hd_temperature")
            try:
                temp: int | None = int(temp_raw) if temp_raw else None
            except (ValueError, TypeError):
                temp = None

            results.append(
                DriveHealth(
                    drive_number=i + 1,
                    model=drive.get("hd_model", ""),
                    health=drive.get("hd_health", ""),
                    temperature=temp,
                )
            )
        return results

    async def get_volumes(self) -> list[VolumeStats]:
        """Return storage volume statistics."""
        text = await self._get(
            "/cgi-bin/management/chartReq.cgi",
            {"chart_func": "disk_usage", "disk_select": "all", "include": "all"},
        )
        root = self._root(text)
        vols_raw = root.get("volumeList", {}).get("volume", [])

        if isinstance(vols_raw, dict):
            vols_raw = [vols_raw]

        results: list[VolumeStats] = []
        for vol in vols_raw:
            if not isinstance(vol, dict):
                continue

            def _bytes(key: str) -> int:
                raw = vol.get(key, "0")
                try:
                    return int(raw)
                except (ValueError, TypeError):
                    return 0

            results.append(
                VolumeStats(
                    name=vol.get("volumeLabel", vol.get("label", "")),
                    total_bytes=_bytes("sizeTotal"),
                    used_bytes=_bytes("sizeUsed"),
                    free_bytes=_bytes("sizeFree"),
                    status=vol.get("status", ""),
                )
            )
        return results

    async def get_firmware_update(self) -> FirmwareUpdate:
        """Return current and available firmware version."""
        text = await self._get(
            "/cgi-bin/sys/sysRequest.cgi", {"subfunc": "firm_update"}
        )
        root = self._root(text)
        firm = root.get("firmware", root)
        current = firm.get("curVersion", firm.get("version", ""))
        latest = firm.get("newVersion") or None  # None if missing or empty string
        return FirmwareUpdate(current_version=current, latest_version=latest)

    async def get_fans(self) -> list[FanStatus]:
        """Return fan speed readings (empty list if unsupported)."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi",
            {"subfunc": "sysinfo", "sysfans": "1"},
        )
        root = self._root(text)
        fans_raw = root.get("sysfan", {})

        if not isinstance(fans_raw, dict):
            return []

        results: list[FanStatus] = []
        for i, (_, val) in enumerate(fans_raw.items()):
            if not isinstance(val, dict):
                continue
            try:
                rpm = int(val.get("speed_rpm", val.get("rpm", 0)))
                results.append(FanStatus(fan_number=i + 1, speed_rpm=rpm))
            except (ValueError, TypeError) as exc:
                _LOGGER.debug("Skipping fan entry %d: %s", i, exc)

        return results

    async def get_external_drives(self) -> list[ExternalDrive]:
        """Return stats for externally-connected drives (empty list if none)."""
        text = await self._get(
            "/cgi-bin/management/chartReq.cgi",
            {"chart_func": "disk_usage", "disk_select": "all", "include": "all"},
        )
        root = self._root(text)
        ext_raw = root.get("externalDriveList", {}).get("drive", [])

        if isinstance(ext_raw, dict):
            ext_raw = [ext_raw]

        results: list[ExternalDrive] = []
        for drv in ext_raw:
            if not isinstance(drv, dict):
                continue

            def _bytes(key: str) -> int:
                raw = drv.get(key, "0")
                try:
                    return int(raw)
                except (ValueError, TypeError):
                    return 0

            results.append(
                ExternalDrive(
                    name=drv.get("name", ""),
                    total_bytes=_bytes("sizeTotal"),
                    used_bytes=_bytes("sizeUsed"),
                )
            )
        return results

    async def get_all(self) -> NasData:
        """Fetch all NAS data in parallel and return a NasData aggregate."""
        (
            system_info,
            system_health,
            cpu,
            memory,
            network_interfaces,
            drives,
            volumes,
            firmware,
            fans,
            external_drives,
        ) = await asyncio.gather(
            self.get_system_info(),
            self.get_system_health(),
            self.get_cpu_stats(),
            self.get_memory_stats(),
            self.get_network_interfaces(),
            self.get_drive_health(),
            self.get_volumes(),
            self.get_firmware_update(),
            self.get_fans(),
            self.get_external_drives(),
            return_exceptions=True,
        )

        def _unwrap(result: Any, default: Any) -> Any:
            if isinstance(result, Exception):
                _LOGGER.warning("get_all partial failure: %s", result)
                return default
            return result

        return NasData(
            system_info=_unwrap(system_info, SystemInfo("", "", "", "", 0)),
            system_health=_unwrap(system_health, SystemHealth("Unknown")),
            cpu=_unwrap(cpu, CpuStats(0.0)),
            memory=_unwrap(memory, MemoryStats(0, 0, 0)),
            network_interfaces=_unwrap(network_interfaces, []),
            drives=_unwrap(drives, []),
            volumes=_unwrap(volumes, []),
            firmware=_unwrap(firmware, None),
            fans=_unwrap(fans, []),
            external_drives=_unwrap(external_drives, []),
        )

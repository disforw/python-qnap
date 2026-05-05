"""Tests for QnapClient."""

from __future__ import annotations

import re

import pytest
from aioresponses import aioresponses

from qnap_client import QnapClient, QnapAuthError
from qnap_client.models import FirmwareUpdate, SystemHealth


LOGIN_SUCCESS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <authPassed>1</authPassed>
    <authSid>abc123sid</authSid>
</QDocRoot>"""

LOGIN_FAILURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <authPassed>0</authPassed>
    <authSid></authSid>
</QDocRoot>"""

FIRMWARE_UPDATE_MISSING_NEW_VERSION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <firmware>
        <curVersion>5.1.0.2466</curVersion>
    </firmware>
</QDocRoot>"""

FIRMWARE_UPDATE_AVAILABLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <firmware>
        <curVersion>5.1.0.2466</curVersion>
        <newVersion>5.2.0.2500</newVersion>
    </firmware>
</QDocRoot>"""

SYSTEM_HEALTH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <sysHealth>
        <status>Ready</status>
    </sysHealth>
</QDocRoot>"""

NETWORK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <net>
        <eth0><mac>00:11:22:33:44:55</mac><ip>192.168.1.100</ip><rx>1024</rx><tx>512</tx></eth0>
        <eth1><mac>00:11:22:33:44:56</mac><ip>192.168.1.101</ip><rx>2048</rx><tx>1024</tx></eth1>
    </net>
</QDocRoot>"""


BASE = "http://192.168.1.100:8080"
_MANA_RE = re.compile(r"http://192\.168\.1\.100:8080/cgi-bin/management/manaRequest\.cgi.*")
_CHART_RE = re.compile(r"http://192\.168\.1\.100:8080/cgi-bin/management/chartReq\.cgi.*")
_SYS_RE = re.compile(r"http://192\.168\.1\.100:8080/cgi-bin/sys/sysRequest\.cgi.*")
_AUTH_RE = re.compile(r"http://192\.168\.1\.100:8080/cgi-bin/authLogin\.cgi.*")


@pytest.fixture
def client() -> QnapClient:
    return QnapClient("192.168.1.100", 8080, "admin", "password")


# ---------------------------------------------------------------------------
# Login / auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success(client: QnapClient) -> None:
    """Successful login stores the session ID."""
    with aioresponses() as m:
        m.post(f"{BASE}/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        await client._ensure_session()
        await client.login()
    assert client._sid == "abc123sid"
    await client._session.close()


@pytest.mark.asyncio
async def test_login_failure_raises(client: QnapClient) -> None:
    """Failed login raises QnapAuthError and clears the session ID."""
    with aioresponses() as m:
        m.post(f"{BASE}/cgi-bin/authLogin.cgi", body=LOGIN_FAILURE_XML)
        await client._ensure_session()
        with pytest.raises(QnapAuthError):
            await client.login()
    assert client._sid is None
    await client._session.close()


# ---------------------------------------------------------------------------
# Firmware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_firmware_update_missing_new_version(client: QnapClient) -> None:
    """get_firmware_update handles missing newVersion gracefully (latest_version=None)."""
    with aioresponses() as m:
        m.post(f"{BASE}/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        m.get(_SYS_RE, body=FIRMWARE_UPDATE_MISSING_NEW_VERSION_XML)
        m.get(_AUTH_RE, body="")  # logout
        async with client:
            result = await client.get_firmware_update()

    assert isinstance(result, FirmwareUpdate)
    assert result.latest_version is None


@pytest.mark.asyncio
async def test_firmware_update_available(client: QnapClient) -> None:
    """get_firmware_update returns the new version when available."""
    with aioresponses() as m:
        m.post(f"{BASE}/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        m.get(_SYS_RE, body=FIRMWARE_UPDATE_AVAILABLE_XML)
        m.get(_AUTH_RE, body="")  # logout
        async with client:
            result = await client.get_firmware_update()

    assert isinstance(result, FirmwareUpdate)
    assert result.latest_version == "5.2.0.2500"


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_health(client: QnapClient) -> None:
    """get_system_health returns the correct status string."""
    with aioresponses() as m:
        m.post(f"{BASE}/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        m.get(_MANA_RE, body=SYSTEM_HEALTH_XML)
        m.get(_AUTH_RE, body="")  # logout
        async with client:
            health = await client.get_system_health()

    assert isinstance(health, SystemHealth)
    assert health.status == "Ready"


# ---------------------------------------------------------------------------
# Network interfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_interfaces(client: QnapClient) -> None:
    """get_network_interfaces parses all interfaces and skips no valid ones."""
    with aioresponses() as m:
        m.post(f"{BASE}/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        m.get(_CHART_RE, body=NETWORK_XML)
        m.get(_AUTH_RE, body="")  # logout
        async with client:
            interfaces = await client.get_network_interfaces()

    assert len(interfaces) == 2
    assert interfaces[0].name == "eth0"
    assert interfaces[0].ip == "192.168.1.100"
    assert interfaces[1].name == "eth1"

"""Tests for QnapClient."""

from __future__ import annotations

import pytest
from aioresponses import aioresponses

from qnap_client import QnapClient, QnapAuthError
from qnap_client.models import FirmwareUpdate, SystemHealth


BASE = "http://192.168.1.100:8080"
LOGIN_URL = f"{BASE}/cgi-bin/authLogin.cgi"
SYSINFO_URL = f"{BASE}/cgi-bin/management/manaRequest.cgi"
FIRM_URL = f"{BASE}/cgi-bin/sys/sysRequest.cgi"
NET_URL = f"{BASE}/cgi-bin/management/chartReq.cgi"

LOGIN_OK = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot><authPassed>1</authPassed><authSid>abc123sid</authSid></QDocRoot>"""

LOGIN_FAIL = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot><authPassed>0</authPassed><authSid></authSid></QDocRoot>"""

HEALTH_OK = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot><sysHealth><status>Ready</status></sysHealth></QDocRoot>"""

FIRMWARE_NO_NEW_VERSION = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot><firmware><curVersion>5.1.0.2466</curVersion></firmware></QDocRoot>"""

FIRMWARE_UPDATE_AVAILABLE = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot><firmware><curVersion>5.1.0.2466</curVersion><newVersion>5.2.0.2500</newVersion></firmware></QDocRoot>"""

NET_TWO_IFACES = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot>
  <net>
    <eth0><mac>00:11:22:33:44:55</mac><ip>192.168.1.100</ip><rx>1024</rx><tx>512</tx></eth0>
    <eth1><mac>00:11:22:33:44:56</mac><ip>192.168.1.101</ip><rx>2048</rx><tx>1024</tx></eth1>
  </net>
</QDocRoot>"""


@pytest.fixture
def client() -> QnapClient:
    return QnapClient("192.168.1.100", 8080, "admin", "password")


@pytest.mark.asyncio
async def test_login_success(client: QnapClient) -> None:
    """Successful login stores session ID."""
    with aioresponses() as m:
        m.post(LOGIN_URL, body=LOGIN_OK)
        await client._ensure_session()
        await client.login()
    assert client._sid == "abc123sid"


@pytest.mark.asyncio
async def test_login_failure_raises(client: QnapClient) -> None:
    """Failed login raises QnapAuthError and leaves sid as None."""
    with aioresponses() as m:
        m.post(LOGIN_URL, body=LOGIN_FAIL)
        await client._ensure_session()
        with pytest.raises(QnapAuthError):
            await client.login()
    assert client._sid is None


@pytest.mark.asyncio
async def test_system_health(client: QnapClient) -> None:
    """get_system_health returns correct status string."""
    with aioresponses() as m:
        m.post(LOGIN_URL, body=LOGIN_OK)
        m.get(SYSINFO_URL, body=HEALTH_OK)
        await client._ensure_session()
        await client.login()
        health = await client.get_system_health()
    assert isinstance(health, SystemHealth)
    assert health.status == "Ready"


@pytest.mark.asyncio
async def test_firmware_update_missing_new_version(client: QnapClient) -> None:
    """get_firmware_update handles missing newVersion key — returns latest_version=None."""
    with aioresponses() as m:
        m.post(LOGIN_URL, body=LOGIN_OK)
        m.get(FIRM_URL, body=FIRMWARE_NO_NEW_VERSION)
        await client._ensure_session()
        await client.login()
        result = await client.get_firmware_update()
    assert isinstance(result, FirmwareUpdate)
    assert result.current_version == "5.1.0.2466"
    assert result.latest_version is None  # Must NOT crash


@pytest.mark.asyncio
async def test_firmware_update_available(client: QnapClient) -> None:
    """get_firmware_update returns latest_version when an update exists."""
    with aioresponses() as m:
        m.post(LOGIN_URL, body=LOGIN_OK)
        m.get(FIRM_URL, body=FIRMWARE_UPDATE_AVAILABLE)
        await client._ensure_session()
        await client.login()
        result = await client.get_firmware_update()
    assert isinstance(result, FirmwareUpdate)
    assert result.current_version == "5.1.0.2466"
    assert result.latest_version == "5.2.0.2500"


@pytest.mark.asyncio
async def test_network_interfaces_parsed(client: QnapClient) -> None:
    """get_network_interfaces parses both interfaces correctly."""
    with aioresponses() as m:
        m.post(LOGIN_URL, body=LOGIN_OK)
        m.get(NET_URL, body=NET_TWO_IFACES)
        await client._ensure_session()
        await client.login()
        ifaces = await client.get_network_interfaces()
    assert len(ifaces) == 2
    assert ifaces[0].name == "eth0"
    assert ifaces[1].name == "eth1"
    assert ifaces[0].ip == "192.168.1.100"

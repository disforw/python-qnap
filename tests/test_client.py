"""Tests for QnapClient."""

from __future__ import annotations

import pytest
from aioresponses import aioresponses

from qnap_client import QnapClient, QnapAuthError
from qnap_client.models import FirmwareUpdate


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
    <authPassed>1</authPassed>
    <func>
        <ownContent>
            <currentVersion>5.1.0.2466</currentVersion>
        </ownContent>
    </func>
</QDocRoot>"""

FIRMWARE_UPDATE_AVAILABLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <authPassed>1</authPassed>
    <func>
        <ownContent>
            <currentVersion>5.1.0.2466</currentVersion>
            <newVersion>5.2.0.2500</newVersion>
        </ownContent>
    </func>
</QDocRoot>"""

SYSTEM_HEALTH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <authPassed>1</authPassed>
    <func>
        <ownContent>
            <sysHealth>
                <status>Ready</status>
            </sysHealth>
        </ownContent>
    </func>
</QDocRoot>"""

NETWORK_MISSING_ETH5_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <authPassed>1</authPassed>
    <func>
        <ownContent>
            <eth0><mac>00:11:22:33:44:55</mac><ip>192.168.1.100</ip><rx>1024</rx><tx>512</tx></eth0>
            <eth1><mac>00:11:22:33:44:56</mac><ip>192.168.1.101</ip><rx>2048</rx><tx>1024</tx></eth1>
        </ownContent>
    </func>
</QDocRoot>"""


@pytest.fixture
def client() -> QnapClient:
    return QnapClient("192.168.1.100", 8080, "admin", "password")


@pytest.mark.asyncio
async def test_login_success(client: QnapClient) -> None:
    """Test successful login stores session ID."""
    with aioresponses() as m:
        m.post("http://192.168.1.100:8080/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        await client._ensure_session()
        await client.login()
    assert client._sid == "abc123sid"


@pytest.mark.asyncio
async def test_login_failure_raises(client: QnapClient) -> None:
    """Test failed login raises QnapAuthError."""
    with aioresponses() as m:
        m.post("http://192.168.1.100:8080/cgi-bin/authLogin.cgi", body=LOGIN_FAILURE_XML)
        await client._ensure_session()
        with pytest.raises(QnapAuthError):
            await client.login()
    assert client._sid is None


@pytest.mark.asyncio
async def test_firmware_update_missing_new_version(client: QnapClient) -> None:
    """Test get_firmware_update handles missing newVersion key gracefully."""
    with aioresponses() as m:
        m.post("http://192.168.1.100:8080/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        m.get(
            "http://192.168.1.100:8080/cgi-bin/sys/sysRequest.cgi",
            body=FIRMWARE_UPDATE_MISSING_NEW_VERSION_XML,
        )
        await client._ensure_session()
        await client.login()
        result = await client.get_firmware_update()

    assert isinstance(result, FirmwareUpdate)
    assert result.latest_version is None  # should NOT crash


@pytest.mark.asyncio
async def test_firmware_update_available(client: QnapClient) -> None:
    """Test get_firmware_update returns new version when available."""
    with aioresponses() as m:
        m.post("http://192.168.1.100:8080/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        m.get(
            "http://192.168.1.100:8080/cgi-bin/sys/sysRequest.cgi",
            body=FIRMWARE_UPDATE_AVAILABLE_XML,
        )
        await client._ensure_session()
        await client.login()
        result = await client.get_firmware_update()

    assert isinstance(result, FirmwareUpdate)
    assert result.latest_version == "5.2.0.2500"


@pytest.mark.asyncio
async def test_network_interfaces_missing_keys(client: QnapClient) -> None:
    """Test get_network_interfaces skips malformed entries gracefully."""
    with aioresponses() as m:
        m.post("http://192.168.1.100:8080/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        m.get(
            "http://192.168.1.100:8080/cgi-bin/management/chartReq.cgi",
            body=NETWORK_MISSING_ETH5_XML,
        )
        await client._ensure_session()
        await client.login()
        interfaces = await client.get_network_interfaces()

    assert len(interfaces) == 2
    assert interfaces[0].name == "eth0"
    assert interfaces[1].name == "eth1"


@pytest.mark.asyncio
async def test_system_health(client: QnapClient) -> None:
    """Test get_system_health returns correct status."""
    with aioresponses() as m:
        m.post("http://192.168.1.100:8080/cgi-bin/authLogin.cgi", body=LOGIN_SUCCESS_XML)
        m.get(
            "http://192.168.1.100:8080/cgi-bin/management/manaRequest.cgi",
            body=SYSTEM_HEALTH_XML,
        )
        await client._ensure_session()
        await client.login()
        health = await client.get_system_health()

    assert health.status == "Ready"

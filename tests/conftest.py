"""Shared fixtures for qnap-client tests."""

from __future__ import annotations

import pytest


LOGIN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <authPassed>1</authPassed>
    <authSid>test-sid-abc123</authSid>
</QDocRoot>"""

SYSINFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <hostname>MyNAS</hostname>
    <serialNumber>Q12345</serialNumber>
    <version>5.1.0</version>
    <uptime>86400</uptime>
    <model>
        <displayModelName>TS-453D</displayModelName>
    </model>
    <cpu>
        <cpu_usage>12.5%</cpu_usage>
    </cpu>
    <memory_status>
        <total>8192</total>
        <free>4096</free>
        <used>4096</used>
    </memory_status>
</QDocRoot>"""

SYSHEALTH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <sysHealth>
        <status>Ready</status>
    </sysHealth>
</QDocRoot>"""

FIRMWARE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <firmware>
        <curVersion>5.1.0</curVersion>
        <newVersion>5.1.5</newVersion>
    </firmware>
</QDocRoot>"""

FIRMWARE_NO_UPDATE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QDocRoot version="1.0">
    <firmware>
        <curVersion>5.1.5</curVersion>
    </firmware>
</QDocRoot>"""

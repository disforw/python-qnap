"""qnap-client — Async Python client for QNAP NAS."""

from __future__ import annotations

from .client import QnapClient
from .container_station import ContainerStationClient
from .exceptions import (
    QnapAPIError,
    QnapAuthError,
    QnapConnectionError,
    QnapError,
    QnapTimeoutError,
)
from .models import (
    Container,
    DriveHealth,
    ExternalDrive,
    FanStatus,
    FirmwareUpdate,
    NasData,
    NetworkInterface,
    SystemHealth,
    SystemInfo,
    VolumeStats,
)

__version__ = "1.0.0"

__all__ = [
    "QnapClient",
    "ContainerStationClient",
    # Exceptions
    "QnapError",
    "QnapAuthError",
    "QnapConnectionError",
    "QnapTimeoutError",
    "QnapAPIError",
    # Models
    "SystemInfo",
    "SystemHealth",
    "NetworkInterface",
    "DriveHealth",
    "VolumeStats",
    "FirmwareUpdate",
    "FanStatus",
    "ExternalDrive",
    "Container",
    "NasData",
]

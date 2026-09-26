"""Low-level client for a Gree heat pump."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from Crypto.Cipher import AES

from .gree_protocol import EncryptGCM, FetchResult, GetDeviceKey, GetDeviceKeyGCM, GetGCMCipher, Pad, RequestStats

_LOGGER = logging.getLogger(__name__)


class GreeHeatPumpClient:
    """Reads and writes device properties over the Gree LAN protocol."""

    def __init__(
        self,
        host: str,
        port: int,
        mac: str,
        encryption_version: int = 1,
        encryption_key: str | None = None,
        uid: int | None = None,
    ) -> None:
        self.host = host
        self.port = port
        mac = mac.replace(":", "").lower()
        # "sub_mac@mac" is used for devices behind a gateway
        if "@" in mac:
            self.sub_mac, self.mac = mac.split("@", 1)
        else:
            self.sub_mac = self.mac = mac
        self.encryption_version = encryption_version
        self._key: bytes | None = encryption_key.encode() if encryption_key else None
        self._uid = uid or 0
        self.stats = RequestStats()

    async def _ensure_key(self) -> None:
        if self._key:
            return
        if self.encryption_version == 1:
            key = await GetDeviceKey(self.mac, self.host, self.port)
        elif self.encryption_version == 2:
            key = await GetDeviceKeyGCM(self.mac, self.host, self.port)
        else:
            raise ValueError(f"Encryption version {self.encryption_version} is not supported")
        if not key:
            raise ConnectionError(f"Could not bind to device at {self.host}")
        self._key = key

    async def _request(self, payload: dict[str, Any], max_retries: int = 8) -> dict[str, Any]:
        await self._ensure_key()
        plaintext = json.dumps(payload, separators=(",", ":"))
        envelope: dict[str, Any] = {"cid": "app", "i": 0, "t": "pack", "tcid": self.mac, "uid": self._uid}

        key = self._key
        if self.encryption_version == 1:
            envelope["pack"] = base64.b64encode(AES.new(key, AES.MODE_ECB).encrypt(Pad(plaintext).encode())).decode()
            make_cipher = lambda: AES.new(key, AES.MODE_ECB)  # noqa: E731
        else:
            envelope["pack"], envelope["tag"] = EncryptGCM(key, plaintext)
            make_cipher = lambda: GetGCMCipher(key)  # noqa: E731

        return await FetchResult(
            make_cipher,
            self.host,
            self.port,
            json.dumps(envelope, separators=(",", ":")),
            encryption_version=self.encryption_version,
            max_retries=max_retries,
            stats=self.stats,
        )

    async def get(self, props: list[str], max_retries: int = 8) -> dict[str, Any]:
        """Read properties from the device."""
        result = await self._request({"cols": props, "mac": self.sub_mac, "t": "status"}, max_retries)
        # Prefer the device's own column list so an unsupported property can't shift the values
        values = dict(zip(result.get("cols", props), result["dat"]))
        _LOGGER.debug("Received from %s: %s", self.host, values)
        return values

    async def set(self, values: dict[str, Any]) -> None:
        """Write properties to the device."""
        _LOGGER.debug("Sending to %s: %s", self.host, values)
        result = await self._request({"opt": list(values), "p": list(values.values()), "t": "cmd", "sub": self.sub_mac})
        _LOGGER.debug("Command reply from %s: %s", self.host, result)
        # A reply alone doesn't mean the command was applied; "r" is the device's result code
        if result.get("r", 200) != 200:
            raise ConnectionError(f"Heat pump rejected the command (result code {result.get('r')})")

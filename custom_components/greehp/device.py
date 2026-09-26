"""Low-level client for a Gree heat pump."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from typing import Any

from Crypto.Cipher import AES

from .gree_protocol import RequestStats, async_bind, async_request, encrypt_gcm, gcm_cipher, pad

_LOGGER = logging.getLogger(__name__)


class WrongDeviceError(Exception):
    """A different Gree device answered at the configured address."""


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
        on_key_change: Callable[[str], None] | None = None,
    ) -> None:
        """on_key_change is called with the new key whenever binding gives a key different from the current one."""
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
        self._on_key_change = on_key_change

    @property
    def key(self) -> str | None:
        return self._key.decode() if self._key else None

    async def bind(self, max_retries: int = 8) -> bool:
        """Ask the device for its current key and use it. Returns True if the key changed.

        Binding is encrypted with Gree's generic key, so it works even when the stored key is out of date,
        for example after the Wi-Fi module was reset. Raises WrongDeviceError if another device answers.
        """
        if self.encryption_version not in (1, 2):
            raise ValueError(f"Encryption version {self.encryption_version} is not supported")
        reply = await async_bind(self.mac, self.host, self.port, self.encryption_version, max_retries)
        if (found := str(reply.get("mac", "")).lower()) != self.mac:
            raise WrongDeviceError(f"Device at {self.host} has MAC {found}, expected {self.mac}")
        key = reply["key"].encode()
        if key == self._key:
            return False
        self._key = key
        if self._on_key_change:
            self._on_key_change(key.decode())
        return True

    async def _ensure_key(self) -> None:
        if not self._key:
            await self.bind()

    async def verify(self, max_retries: int = 4) -> None:
        """Check the device at this address is the configured one and answers reads.

        Raises WrongDeviceError if another device answers, or another exception if none does.
        Uses fewer attempts than polling so a form doesn't hang long on a wrong address.
        """
        try:
            await self.bind(max_retries)
        except WrongDeviceError:
            raise
        except Exception:
            # Without a key there's nothing else to try. With one, the device may just not answer binds.
            if not self._key:
                raise
        await self.get(["Pow"], max_retries=max_retries)

    async def _request(self, payload: dict[str, Any], max_retries: int = 8) -> dict[str, Any]:
        await self._ensure_key()
        plaintext = json.dumps(payload, separators=(",", ":"))
        envelope: dict[str, Any] = {"cid": "app", "i": 0, "t": "pack", "tcid": self.mac, "uid": self._uid}

        key = self._key
        if self.encryption_version == 1:
            envelope["pack"] = base64.b64encode(AES.new(key, AES.MODE_ECB).encrypt(pad(plaintext).encode())).decode()
            make_cipher = lambda: AES.new(key, AES.MODE_ECB)  # noqa: E731
        else:
            envelope["pack"], envelope["tag"] = encrypt_gcm(key, plaintext)
            make_cipher = lambda: gcm_cipher(key)  # noqa: E731

        return await async_request(
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

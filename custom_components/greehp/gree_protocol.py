"""Gree LAN protocol: encrypted UDP requests, binding and discovery."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from typing import Any

from Crypto.Cipher import AES

from homeassistant.components.network import async_get_ipv4_broadcast_addresses
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

GCM_IV = b"\x54\x40\x78\x44\x49\x67\x5a\x51\x6c\x5e\x63\x13"
GCM_ADD = b"qualcomm-test"
GENERIC_GREE_DEVICE_KEY = "a3K8Bx%2r8Y7#xDh"
GENERIC_GREE_DEVICE_KEY_GCM = b"{yxAHAY_Lm6pbC/<"

DISCOVERY_PORT = 7000
DISCOVERY_MESSAGE = b'{"t":"scan"}'
# Tried in addition to the broadcast addresses Home Assistant knows about
DEFAULT_BROADCAST_ADDRESSES = ["255.255.255.255", "192.168.255.255", "10.255.255.255", "172.31.255.255"]

# The device answers within ~50ms or not at all, so resend quickly: 1.0s, 1.2s, 1.4s, ...
RESEND_AFTER = 1.0
RESEND_BACKOFF = 0.2


# --- Encryption ----------------------------------------------------------


def pad(text: str) -> str:
    """PKCS#7 padding to the AES block size, as the devices expect for ECB."""
    size = 16 - len(text) % 16
    return text + chr(size) * size


def gcm_cipher(key: bytes) -> Any:
    cipher = AES.new(key, AES.MODE_GCM, nonce=GCM_IV)
    cipher.update(GCM_ADD)
    return cipher


def encrypt_gcm(key: bytes, plaintext: str) -> tuple[str, str]:
    """Encrypt for encryption version 2. Returns (pack, tag), both base64."""
    encrypted, tag = gcm_cipher(key).encrypt_and_digest(plaintext.encode())
    return base64.b64encode(encrypted).decode(), base64.b64encode(tag).decode()


def _decode_reply(make_cipher: Callable[[], Any], data: bytes, encryption_version: int) -> dict[str, Any]:
    """Decrypt and parse a device reply. A fresh cipher is used for every reply."""
    envelope = json.loads(data)
    cipher = make_cipher()
    decrypted = cipher.decrypt(base64.b64decode(envelope["pack"]))
    if encryption_version == 2:
        cipher.verify(base64.b64decode(envelope["tag"]))
    # Drop padding and anything after the last }
    text = decrypted.decode().replace("\x0f", "")
    return json.loads(text[: text.rindex("}") + 1])


# --- Requests ------------------------------------------------------------


class _ReplyProtocol(asyncio.DatagramProtocol):
    """Queues datagrams arriving from one host."""

    def __init__(self, host: str) -> None:
        self._host = host
        self.replies: asyncio.Queue[bytes] = asyncio.Queue()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr[0] == self._host:
            self.replies.put_nowait(data)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Socket error from %s: %s", self._host, exc)


class RequestStats:
    """Counts how many attempts requests needed, to show how often the device drops them."""

    def __init__(self) -> None:
        self.requests = 0
        self.failed = 0
        # {attempts needed: number of requests}
        self.succeeded_on_attempt: dict[int, int] = {}

    def record(self, attempts: int, ok: bool) -> None:
        self.requests += 1
        if ok:
            self.succeeded_on_attempt[attempts] = self.succeeded_on_attempt.get(attempts, 0) + 1
        else:
            self.failed += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "failed": self.failed,
            "succeeded_on_attempt": dict(sorted(self.succeeded_on_attempt.items())),
        }


async def async_request(
    make_cipher: Callable[[], Any],
    host: str,
    port: int,
    payload: str,
    encryption_version: int = 1,
    max_retries: int = 8,
    stats: RequestStats | None = None,
) -> dict[str, Any]:
    """Send a request to a Gree device and return its decrypted reply.

    One socket is kept open for the whole request, so a reply that arrives after its attempt timed
    out is still accepted instead of being lost. If `stats` is given, the attempts are recorded in it.
    Raises TimeoutError if the device never answers, ConnectionError if it only sends garbage.
    """
    _LOGGER.debug("Sending to %s:%s: %s", host, port, payload)

    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(lambda: _ReplyProtocol(host), local_addr=("0.0.0.0", 0))
    data_out = payload.encode()
    last_error: Exception | None = None

    try:
        for attempt in range(max_retries):
            transport.sendto(data_out, (host, port))
            deadline = loop.time() + RESEND_AFTER + attempt * RESEND_BACKOFF

            while (remaining := deadline - loop.time()) > 0:
                try:
                    data = await asyncio.wait_for(protocol.replies.get(), timeout=remaining)
                except TimeoutError as err:
                    last_error = err
                    break
                try:
                    result = _decode_reply(make_cipher, data, encryption_version)
                except Exception as err:  # noqa: BLE001 - any undecodable packet is skipped the same way
                    last_error = err
                    _LOGGER.debug("Ignoring undecodable reply from %s: %s: %s", host, type(err).__name__, err)
                    continue
                _LOGGER.debug("Reply from %s on attempt %d", host, attempt + 1)
                if stats is not None:
                    stats.record(attempt + 1, ok=True)
                return result
    finally:
        transport.close()

    if last_error is None or isinstance(last_error, TimeoutError):
        error: Exception = TimeoutError(f"No reply from {host}:{port} after {max_retries} attempts")
    else:
        error = ConnectionError(f"Invalid reply from {host}:{port}: {type(last_error).__name__}: {last_error}")
    # Callers decide whether this matters (a missed read-back doesn't), so only note it here
    _LOGGER.debug("%s", error)
    if stats is not None:
        stats.record(max_retries, ok=False)
    raise error from last_error


async def async_bind(mac: str, host: str, port: int, encryption_version: int = 1, max_retries: int = 8) -> dict[str, Any]:
    """Bind to a device and return its reply, which includes its "key" and its own "mac". Raises on failure."""
    _LOGGER.debug("Binding to device at %s (encryption version %s)", host, encryption_version)
    # The message text is kept exactly as devices are known to accept it
    if encryption_version == 1:
        generic_key = GENERIC_GREE_DEVICE_KEY.encode()
        encrypted = AES.new(generic_key, AES.MODE_ECB).encrypt(pad(f'{{"mac":"{mac}","t":"bind","uid":0}}').encode())
        pack = base64.b64encode(encrypted).decode()
        payload = f'{{"cid": "app","i": 1,"pack": "{pack}","t":"pack","tcid":"{mac}","uid": 0}}'
        make_cipher: Callable[[], Any] = lambda: AES.new(generic_key, AES.MODE_ECB)  # noqa: E731
    else:
        pack, tag = encrypt_gcm(GENERIC_GREE_DEVICE_KEY_GCM, f'{{"cid":"{mac}", "mac":"{mac}","t":"bind","uid":0}}')
        payload = f'{{"cid": "app","i": 1,"pack": "{pack}","t":"pack","tcid":"{mac}","uid": 0, "tag" : "{tag}"}}'
        make_cipher = lambda: gcm_cipher(GENERIC_GREE_DEVICE_KEY_GCM)  # noqa: E731
    result = await async_request(make_cipher, host, port, payload, encryption_version, max_retries)
    _LOGGER.debug("Bind reply: %s", {k: ("**REDACTED**" if k == "key" else v) for k, v in result.items()})
    return result


# --- Discovery -----------------------------------------------------------


class _CollectProtocol(asyncio.DatagramProtocol):
    """Collects every datagram that arrives, with its sender."""

    def __init__(self) -> None:
        self.packets: list[tuple[bytes, tuple[str, int]]] = []

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.packets.append((data, addr))

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Socket error during discovery: %s", exc)


def _parse_scan_reply(data: bytes, addr: tuple[str, int], port: int) -> dict[str, Any] | None:
    """Turn a scan reply into device info, or None if it isn't one. Scan replies use the generic ECB key."""
    try:
        envelope = json.loads(data.decode(errors="ignore"))
        decrypted = AES.new(GENERIC_GREE_DEVICE_KEY.encode(), AES.MODE_ECB).decrypt(base64.b64decode(envelope["pack"]))
        text = decrypted.decode(errors="ignore").replace("\x0f", "")
        info = json.loads(text[: text.rindex("}") + 1])
    except (ValueError, KeyError, TypeError) as err:
        _LOGGER.debug("Ignoring unreadable discovery reply from %s: %s", addr, err)
        return None
    if info.get("t") != "dev" or not (mac := info.get("mac")):
        _LOGGER.debug("Ignoring discovery reply from %s without device info", addr)
        return None
    return {
        "name": info.get("name") or f"Gree {mac[-4:]}",
        "host": addr[0],
        "port": port,
        "mac": mac,
        "brand": info.get("brand", "gree"),
        "model": info.get("model", "gree"),
        "version": info.get("ver", ""),
    }


async def async_discover(
    hass: HomeAssistant, timeout: float = 5.0, port: int = DISCOVERY_PORT, addresses: list[str] | None = None
) -> list[dict[str, Any]]:
    """Find Gree devices by broadcasting a scan, without blocking the event loop.

    Each device is listed once, even if it answers several broadcast addresses. `addresses` replaces the
    default broadcast addresses; `port` is the port devices listen on.
    """
    if addresses is None:
        addresses = list(DEFAULT_BROADCAST_ADDRESSES)
        try:
            addresses += [str(address) for address in await async_get_ipv4_broadcast_addresses(hass)]
        except Exception as err:  # noqa: BLE001 - the defaults still work without Home Assistant's list
            _LOGGER.debug("Could not get Home Assistant's broadcast addresses: %s", err)
        addresses = list(dict.fromkeys(addresses))

    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _CollectProtocol, local_addr=("0.0.0.0", 0), allow_broadcast=True
    )
    try:
        for address in addresses:
            try:
                transport.sendto(DISCOVERY_MESSAGE, (address, port))
            except OSError as err:
                _LOGGER.debug("Could not send discovery to %s: %s", address, err)
        await asyncio.sleep(timeout)
    finally:
        transport.close()

    devices: dict[str, dict[str, Any]] = {}
    for data, addr in protocol.packets:
        if (device := _parse_scan_reply(data, addr, port)) and device["mac"] not in devices:
            devices[device["mac"]] = device
    _LOGGER.debug("Discovery found %d device(s): %s", len(devices), list(devices.values()))
    return list(devices.values())

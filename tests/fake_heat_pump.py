"""A fake Gree heat pump on localhost, speaking the real UDP protocol.

It behaves like the real unit in the ways that matter to the integration: it binds with the generic
key, leaves unknown property names out of status replies, and can be told to drop requests, reply
late, or acknowledge commands without applying them.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from Crypto.Cipher import AES

from custom_components.greehp.gree_protocol import (
    GENERIC_GREE_DEVICE_KEY,
    GENERIC_GREE_DEVICE_KEY_GCM,
    EncryptGCM,
    GetGCMCipher,
    Pad,
)

DEVICE_KEY = "3Kl6No9Qr2Tu5Wx8"
MAC = "9424b847cb02"

DEFAULT_STATE: dict[str, Any] = {
    "Pow": 1,
    "Mod": 2,
    "WatBoxTemSet": 45,
    "HeWatOutTemSet": 48,
    "CoWatOutTemSet": 25,
    "Quiet": 0,
    "WatBoxTemHi": 141,
    "WatBoxTemLo": 9,
    "AllInWatTemHi": 124,
    "AllInWatTemLo": 3,
    "AllOutWatTemHi": 133,
    "AllOutWatTemLo": 1,
    "WatBoxElcHeRunSta": 0,
    "ElcHe1RunSta": 0,
    "ElcHe2RunSta": 0,
    "AnFrzzRunSta": 0,
    "FastHtWter": 0,
    "TemUn": 0,
}


class FakeHeatPump(asyncio.DatagramProtocol):
    """Behaviour switches (all off by default):

    drop: 1-based request numbers to ignore completely.
    ignore_commands: acknowledge this many commands without applying them.
    reply_delay: seconds before any reply is sent.
    status_delays: per-status-request reply delays, used in order (overrides reply_delay).
    garbage_first: send an undecodable packet before each real reply.
    result_code: the "r" code in command replies; anything but 200 means rejected.
    encryption_version: 1 (ECB) or 2 (GCM).
    """

    def __init__(
        self, state: dict[str, Any] | None = None, mac: str = MAC, encryption_version: int = 1, key: str = DEVICE_KEY
    ) -> None:
        self.state = dict(DEFAULT_STATE if state is None else state)
        self.mac = mac
        # Change this to simulate a Wi-Fi module reset: requests with the old key are then ignored
        self.key = key
        self.encryption_version = encryption_version
        self.drop: set[int] = set()
        self.ignore_commands = 0
        self.reply_delay = 0.0
        self.status_delays: list[float] = []
        self.garbage_first = False
        self.result_code = 200
        self.requests = 0
        self.commands = 0
        self.reads = 0
        self._transport: asyncio.DatagramTransport | None = None
        self._handles: list[asyncio.TimerHandle] = []

    # --- lifecycle -------------------------------------------------------

    @classmethod
    async def start(cls, **kwargs: Any) -> FakeHeatPump:
        pump = cls(**kwargs)
        await asyncio.get_running_loop().create_datagram_endpoint(lambda: pump, local_addr=("127.0.0.1", 0))
        return pump

    @property
    def port(self) -> int:
        return self._transport.get_extra_info("sockname")[1]

    def close(self) -> None:
        for handle in self._handles:
            handle.cancel()
        if self._transport:
            self._transport.close()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    # --- protocol --------------------------------------------------------

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.requests += 1
        if self.requests in self.drop:
            return
        envelope = json.loads(data)
        request = self._decrypt(envelope)
        if request is None:
            return  # A real device ignores what it can't decrypt

        if request["t"] == "bind":
            reply = {"t": "bindok", "mac": self.mac, "key": self.key, "r": 200}
            self._reply(reply, addr, generic_key=True, delay=self.reply_delay)
        elif request["t"] == "status":
            self.reads += 1
            known = [c for c in request["cols"] if c in self.state]
            reply = {"t": "dat", "mac": self.mac, "cols": known, "dat": [self.state[c] for c in known]}
            delay = self.status_delays.pop(0) if self.status_delays else self.reply_delay
            self._reply(reply, addr, delay=delay)
        elif request["t"] == "cmd":
            self.commands += 1
            changes = dict(zip(request["opt"], request["p"]))
            if self.ignore_commands:
                self.ignore_commands -= 1
            elif self.result_code == 200:
                self.state.update(changes)
            reply = {"t": "res", "r": self.result_code, "opt": request["opt"], "p": request["p"], "val": request["p"]}
            self._reply(reply, addr, delay=self.reply_delay)

    def _decrypt(self, envelope: dict[str, Any]) -> dict[str, Any] | None:
        raw = base64.b64decode(envelope["pack"])
        if self.encryption_version == 1:
            for key in (GENERIC_GREE_DEVICE_KEY.encode(), self.key.encode()):
                text = AES.new(key, AES.MODE_ECB).decrypt(raw).decode("utf-8", "ignore")
                try:
                    return json.loads(text[: text.rindex("}") + 1])
                except ValueError:
                    continue
            return None
        for key in (GENERIC_GREE_DEVICE_KEY_GCM, self.key.encode()):
            cipher = GetGCMCipher(key)
            try:
                text = cipher.decrypt(raw).decode("utf-8")
                cipher.verify(base64.b64decode(envelope["tag"]))
                return json.loads(text)
            except ValueError:
                continue
        return None

    def _encrypt(self, reply: dict[str, Any], generic_key: bool) -> bytes:
        text = json.dumps(reply)
        if self.encryption_version == 1:
            key = GENERIC_GREE_DEVICE_KEY.encode() if generic_key else self.key.encode()
            pack = base64.b64encode(AES.new(key, AES.MODE_ECB).encrypt(Pad(text).encode())).decode()
            return json.dumps({"t": "pack", "pack": pack}).encode()
        key = GENERIC_GREE_DEVICE_KEY_GCM if generic_key else self.key.encode()
        pack, tag = EncryptGCM(key, text)
        return json.dumps({"t": "pack", "pack": pack, "tag": tag}).encode()

    def _reply(self, reply: dict[str, Any], addr: tuple[str, int], generic_key: bool = False, delay: float = 0.0) -> None:
        packets = []
        if self.garbage_first:
            packets.append(b"not a gree packet")
        packets.append(self._encrypt(reply, generic_key))

        def send() -> None:
            if self._transport and not self._transport.is_closing():
                for packet in packets:
                    self._transport.sendto(packet, addr)

        if delay:
            self._handles.append(asyncio.get_running_loop().call_later(delay, send))
        else:
            send()

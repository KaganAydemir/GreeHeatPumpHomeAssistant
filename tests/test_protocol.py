"""The UDP client on its own: retries, late and garbled replies, both encryption versions."""

from __future__ import annotations

import pytest

from custom_components.greehp.device import GreeHeatPumpClient, WrongDeviceError

from .fake_heat_pump import DEVICE_KEY, MAC, FakeHeatPump


def client_for(pump: FakeHeatPump, **kwargs: object) -> GreeHeatPumpClient:
    params = {"encryption_key": DEVICE_KEY, "encryption_version": pump.encryption_version, **kwargs}
    return GreeHeatPumpClient("127.0.0.1", pump.port, MAC, **params)


async def test_read(pump: FakeHeatPump) -> None:
    client = client_for(pump)
    assert await client.get(["Pow", "Mod"]) == {"Pow": 1, "Mod": 2}
    assert client.stats.as_dict() == {"requests": 1, "failed": 0, "succeeded_on_attempt": {1: 1}}


async def test_unknown_names_are_left_out(pump: FakeHeatPump) -> None:
    """Values must stay matched to their names when the device omits one."""
    assert await client_for(pump).get(["Pow", "OutEnvTem", "Mod"]) == {"Pow": 1, "Mod": 2}


async def test_dropped_requests_are_retried(pump: FakeHeatPump) -> None:
    pump.drop = {1, 2}
    client = client_for(pump)
    assert await client.get(["Pow"]) == {"Pow": 1}
    assert client.stats.as_dict()["succeeded_on_attempt"] == {3: 1}


async def test_late_reply_is_accepted(pump: FakeHeatPump) -> None:
    """A reply that arrives after its attempt timed out still counts."""
    pump.reply_delay = 0.07  # longer than the first resend window (0.05 s in tests)
    client = client_for(pump)
    assert await client.get(["Pow"]) == {"Pow": 1}
    assert client.stats.as_dict()["succeeded_on_attempt"] == {2: 1}


async def test_garbage_is_skipped(pump: FakeHeatPump) -> None:
    pump.garbage_first = True
    assert await client_for(pump).get(["Pow"]) == {"Pow": 1}


async def test_no_reply_raises_readable_error(pump: FakeHeatPump) -> None:
    pump.drop = set(range(1, 100))
    client = client_for(pump)
    with pytest.raises(TimeoutError, match="No reply from 127.0.0.1:.* after 3 attempts"):
        await client.get(["Pow"], max_retries=3)
    assert client.stats.as_dict() == {"requests": 1, "failed": 1, "succeeded_on_attempt": {}}


async def test_command_and_reply_check(pump: FakeHeatPump) -> None:
    client = client_for(pump)
    await client.set({"WatBoxTemSet": 44})
    assert pump.state["WatBoxTemSet"] == 44
    pump.result_code = 400
    with pytest.raises(ConnectionError, match="result code 400"):
        await client.set({"WatBoxTemSet": 43})


async def test_binds_for_key(pump: FakeHeatPump) -> None:
    assert await client_for(pump, encryption_key=None).get(["Pow"]) == {"Pow": 1}


async def test_gcm_encryption() -> None:
    pump = await FakeHeatPump.start(encryption_version=2)
    try:
        pump.garbage_first = True
        assert await client_for(pump).get(["Pow"]) == {"Pow": 1}
        assert await client_for(pump, encryption_key=None).get(["Mod"]) == {"Mod": 2}
    finally:
        pump.close()


async def test_verify_checks_identity(pump: FakeHeatPump) -> None:
    await client_for(pump).verify()
    other = await FakeHeatPump.start(mac="aabbccddeeff")
    try:
        with pytest.raises(WrongDeviceError):
            await client_for(other).verify()
    finally:
        other.close()

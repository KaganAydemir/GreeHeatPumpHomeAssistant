"""Constants for the Gree heat pump integration."""

from datetime import timedelta

DOMAIN = "greehp"

CONF_ENCRYPTION_KEY = "encryption_key"
CONF_UID = "uid"
CONF_ENCRYPTION_VERSION = "encryption_version"

DEFAULT_PORT = 7000
SCAN_INTERVAL = timedelta(seconds=30)

# Setpoint limits (°C)
DHW_MIN_TEMP = 40
DHW_MAX_TEMP = 80
HEATING_MIN_TEMP = 20
HEATING_MAX_TEMP = 65
COOLING_MIN_TEMP = 5
COOLING_MAX_TEMP = 25

# Device properties
PROP_POWER = "Pow"
PROP_MODE = "Mod"
PROP_DHW_SET = "WatBoxTemSet"  # Boiler (hot water tank) target
PROP_HEATING_SET = "HeWatOutTemSet"  # Radiator water outlet target
PROP_COOLING_SET = "CoWatOutTemSet"  # Cooling water outlet target
PROP_QUIET = "Quiet"
# Temperatures are split in two: (Hi - 100) + Lo / 10
PROP_TANK_HI = "WatBoxTemHi"  # Hot water tank
PROP_TANK_LO = "WatBoxTemLo"
PROP_INLET_HI = "AllInWatTemHi"  # Water returning to the heat pump
PROP_INLET_LO = "AllInWatTemLo"
PROP_OUTLET_HI = "AllOutWatTemHi"  # Water leaving the heat pump (flow)
PROP_OUTLET_LO = "AllOutWatTemLo"
# Status flags (0/1)
PROP_TANK_HEATER = "WatBoxElcHeRunSta"  # Tank electric heater running
PROP_HEATER_1 = "ElcHe1RunSta"  # Electric backup heater 1 running
PROP_HEATER_2 = "ElcHe2RunSta"  # Electric backup heater 2 running
PROP_ANTI_FREEZE = "AnFrzzRunSta"  # Anti-freeze protection active
PROP_FAST_HOT_WATER = "FastHtWter"  # Fast hot water mode

# Properties polled every update
POLLED_PROPS = [
    PROP_POWER,
    PROP_MODE,
    PROP_DHW_SET,
    PROP_HEATING_SET,
    PROP_COOLING_SET,
    PROP_QUIET,
    PROP_TANK_HI,
    PROP_TANK_LO,
    PROP_INLET_HI,
    PROP_INLET_LO,
    PROP_OUTLET_HI,
    PROP_OUTLET_LO,
    PROP_TANK_HEATER,
    PROP_HEATER_1,
    PROP_HEATER_2,
    PROP_ANTI_FREEZE,
    PROP_FAST_HOT_WATER,
]
# Properties always included in a command, alongside whatever is being changed
BASE_COMMAND_PROPS = [PROP_POWER, PROP_MODE, PROP_DHW_SET, PROP_HEATING_SET]

# Space conditioning states
SPACE_OFF = "off"
SPACE_HEAT = "heat"
SPACE_COOL = "cool"

# Mod value <-> (space conditioning, hot water enabled)
MODE_TO_STATE: dict[int, tuple[str, bool]] = {
    1: (SPACE_HEAT, False),  # Heating
    2: (SPACE_OFF, True),  # Boiler
    3: (SPACE_COOL, True),  # Boiler + Cooling
    4: (SPACE_HEAT, True),  # Boiler + Heating
    5: (SPACE_COOL, False),  # Cooling
}
STATE_TO_MODE: dict[tuple[str, bool], int] = {v: k for k, v in MODE_TO_STATE.items()}

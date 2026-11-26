"""Nest thermostat node for the Nest Thermostat plugin."""
import udi_interface

LOGGER = udi_interface.LOGGER

TRAIT = "sdm.devices.traits."
CMD_MODE = "sdm.devices.commands.ThermostatMode.SetMode"
CMD_ECO = "sdm.devices.commands.ThermostatEco.SetMode"
CMD_HEAT = "sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat"
CMD_COOL = "sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool"
CMD_RANGE = "sdm.devices.commands.ThermostatTemperatureSetpoint.SetRange"

MODE_TO_IDX = {"OFF": 0, "HEAT": 1, "COOL": 2, "HEATCOOL": 3}
IDX_TO_MODE = {v: k for k, v in MODE_TO_IDX.items()}
HVAC_TO_IDX = {"OFF": 0, "HEATING": 1, "COOLING": 2}
UOM_C = 4
UOM_F = 17


def c_to_f(c):
    return round(float(c) * 9.0 / 5.0 + 32.0, 1)


def f_to_c(f):
    return round((float(f) - 32.0) * 5.0 / 9.0, 2)


def to_celsius(value, uom, scale):
    """Convert a command value to Celsius (the only unit Google accepts).

    The command's own uom wins; if it is missing, fall back to the
    thermostat's current display scale.
    """
    try:
        u = int(uom)
    except (TypeError, ValueError):
        u = None
    if u == UOM_F:
        return f_to_c(value)
    if u == UOM_C:
        return round(float(value), 2)
    if scale == "FAHRENHEIT":
        return f_to_c(value)
    return round(float(value), 2)


class NestThermostat(udi_interface.Node):
    id = "nest_thermostat"
    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': 17, 'name': 'Current Temperature'},
        {'driver': 'CLIHUM', 'value': 0, 'uom': 22, 'name': 'Humidity'},
        {'driver': 'CLIMD', 'value': 0, 'uom': 25, 'name': 'Mode'},
        {'driver': 'CLISPH', 'value': 0, 'uom': 17, 'name': 'Heat Setpoint'},
        {'driver': 'CLISPC', 'value': 0, 'uom': 17, 'name': 'Cool Setpoint'},
        {'driver': 'CLIHCS', 'value': 0, 'uom': 25, 'name': 'Heating/Cooling State'},
        {'driver': 'CLIEMD', 'value': 0, 'uom': 25, 'name': 'Eco Mode'},
        {'driver': 'CONNECTED', 'value': 0, 'uom': 25, 'name': 'Connection'},
    ]

    def __init__(self, polyglot, primary, address, name, device_path, nest_ctrl):
        super().__init__(polyglot, primary, address, name)
        self.device_path = device_path
        self.nest_ctrl = nest_ctrl
        self.scale = "CELSIUS"
        self.mode = None
        self.eco = False
        self.heat_c = None
        self.cool_c = None

    # ---- state from Google -------------------------------------------------
    def _temp(self, celsius):
        if self.scale == "FAHRENHEIT":
            return c_to_f(celsius), UOM_F
        return round(float(celsius), 1), UOM_C

    def update_from_traits(self, traits):
        t = traits or {}
        try:
            scale = (t.get(TRAIT + "Settings") or {}).get("temperatureScale")
            if scale:
                self.scale = scale

            temp = (t.get(TRAIT + "Temperature") or {}).get("ambientTemperatureCelsius")
            if temp is not None:
                value, uom = self._temp(temp)
                self.setDriver('ST', value, uom=uom)

            hum = (t.get(TRAIT + "Humidity") or {}).get("ambientHumidityPercent")
            if hum is not None:
                self.setDriver('CLIHUM', round(float(hum), 0), uom=22)

            mode = (t.get(TRAIT + "ThermostatMode") or {}).get("mode")
            if mode:
                self.mode = mode
                self.setDriver('CLIMD', MODE_TO_IDX.get(mode, 0), uom=25)

            eco = t.get(TRAIT + "ThermostatEco")
            if eco is not None:
                self.eco = eco.get("mode") == "MANUAL_ECO"
                self.setDriver('CLIEMD', 1 if self.eco else 0, uom=25)

            hvac = (t.get(TRAIT + "ThermostatHvac") or {}).get("status")
            if hvac:
                self.setDriver('CLIHCS', HVAC_TO_IDX.get(hvac, 0), uom=25)

            sp = t.get(TRAIT + "ThermostatTemperatureSetpoint") or {}
            if sp.get("heatCelsius") is not None:
                self.heat_c = float(sp["heatCelsius"])
                value, uom = self._temp(self.heat_c)
                self.setDriver('CLISPH', value, uom=uom)
            if sp.get("coolCelsius") is not None:
                self.cool_c = float(sp["coolCelsius"])
                value, uom = self._temp(self.cool_c)
                self.setDriver('CLISPC', value, uom=uom)

            conn = (t.get(TRAIT + "Connectivity") or {}).get("status")
            if conn:
                self.setDriver('CONNECTED', 1 if conn == "ONLINE" else 0, uom=25)
        except Exception:
            LOGGER.exception("Could not update %s from Nest data", self.address)

    def refresh_state(self):
        import nest_api
        status, data = nest_api.api_request(self.nest_ctrl, "GET", "/" + self.device_path)
        if status == 200:
            self.update_from_traits((data or {}).get("traits"))
            return True
        LOGGER.warning("Could not refresh %s (HTTP %s): %s", self.address, status,
                       nest_api.error_text(data))
        return False

    # ---- commands to Google ------------------------------------------------
    def _execute(self, command, params):
        import nest_api
        status, data = nest_api.api_request(
            self.nest_ctrl, "POST", "/%s:executeCommand" % self.device_path,
            {"command": command, "params": params})
        if status == 200:
            LOGGER.info("Nest command %s ok for %s", command.split('.')[-2] + '.' + command.split('.')[-1], self.address)
            self.refresh_state()
            return True
        LOGGER.error("Nest command %s failed for %s (HTTP %s): %s", command, self.address,
                     status, nest_api.error_text(data))
        return False

    @staticmethod
    def _value(command):
        try:
            return float((command or {}).get('value'))
        except (TypeError, ValueError):
            LOGGER.error("Command had no usable value: %s", command)
            return None

    def _set_setpoint(self, which, command):
        value = self._value(command)
        if value is None:
            return
        if self.eco:
            LOGGER.warning("Eco mode is on, Google rejects temperature changes. Turn Eco off first.")
            return
        celsius = to_celsius(value, (command or {}).get('uom'), self.scale)
        if self.mode == "HEAT" and which == "heat":
            self._execute(CMD_HEAT, {"heatCelsius": celsius})
        elif self.mode == "COOL" and which == "cool":
            self._execute(CMD_COOL, {"coolCelsius": celsius})
        elif self.mode == "HEATCOOL":
            heat = celsius if which == "heat" else self.heat_c
            cool = celsius if which == "cool" else self.cool_c
            if heat is None or cool is None:
                LOGGER.warning("Heat/Cool targets not known yet, try again after the next update.")
                return
            self._execute(CMD_RANGE, {"heatCelsius": heat, "coolCelsius": cool})
        else:
            LOGGER.warning("Cannot set the %s target while the thermostat is in %s mode.",
                           which, self.mode)

    def set_mode(self, command):
        value = self._value(command)
        if value is None:
            return
        mode = IDX_TO_MODE.get(int(value))
        if mode is None:
            LOGGER.error("Unknown mode value %s", value)
            return
        self._execute(CMD_MODE, {"mode": mode})

    def set_heat(self, command):
        self._set_setpoint("heat", command)

    def set_cool(self, command):
        self._set_setpoint("cool", command)

    def set_eco(self, command):
        value = self._value(command)
        if value is None:
            return
        self._execute(CMD_ECO, {"mode": "MANUAL_ECO" if int(value) == 1 else "OFF"})

    def query_cmd(self, command=None):
        self.refresh_state()

    commands = {
        "CLIMD": set_mode,
        "CLISPH": set_heat,
        "CLISPC": set_cool,
        "CLIEMD": set_eco,
        "QUERY": query_cmd,
    }

from typing import Any, Union

from homeassistant.components.sensor.const import (
    ATTR_STATE_CLASS,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_DEVICE_CLASS,
    ATTR_FRIENDLY_NAME,
    ATTR_ICON,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_USERNAME,
    UnitOfEnergy,
)
from pygazpar.enum import Frequency, PropertyName  # type: ignore
import logging

_LOGGER = logging.getLogger(__name__)

HA_ATTRIBUTION = "Data provided by GrDF"

ICON_GAS = "mdi:fire"

SENSOR_FRIENDLY_NAME = "Gazpar"

LAST_INDEX = -1

ATTR_PCE = "pce"
ATTR_VERSION = "version"
ATTR_ERROR_MESSAGES = "errorMessages"


# --------------------------------------------------------------------------------------------
class Util:

    # A single day's gas volume can never legitimately exceed this, even for a large house in
    # extreme cold. Used to reject a corrupted/implausible reading from a single API response
    # instead of trusting it blindly (root cause of the 2024-10-14 incident: a single bad
    # end_index_m3 value propagated directly into the cumulative state).
    MAX_PLAUSIBLE_DAILY_VOLUME_M3 = 500.0

    # ----------------------------------
    @staticmethod
    def toState(pygazparData: dict[str, list[dict[str, Any]]]) -> Union[float, None]:
        """Compute the cumulative energy state from the most recent plausible daily reading.

        Previous implementation walked backward from the most recent day while
        start_index_m3 == end_index_m3 (treating this as "no reading yet"), summed the
        energy_kwh of the skipped days, and used whichever day it landed on (index,
        clamped to the end of the array if none matched) as the base for
        volumeEndIndex * converterFactor. That heuristic cannot distinguish "GRDF hasn't
        published today's reading yet" from "the meter genuinely recorded zero
        consumption today" (e.g. heating appliance switched off for an extended period),
        and its result depended on how many days of history happened to be returned by
        the data source on a given poll -- an unrelated implementation detail. Both
        caused the reported state to silently drift for a stale/frozen index and then
        jump abruptly once a differing index reappeared.

        This implementation instead always anchors on the most recent day whose reading
        is present and physically plausible, using its end_index_m3 directly -- which is
        already GRDF's authoritative cumulative meter index and requires no backward
        accumulation. A day is skipped (and a warning logged) only if its index/converter
        factor is missing, or if it implies an implausible single-day volume -- guarding
        against a single corrupted API response inflating the cumulative total.
        """

        res = None

        if len(pygazparData) > 0:

            dailyData = pygazparData[Frequency.DAILY.value]

            if dailyData is not None and len(dailyData) > 0:

                for reading in dailyData:

                    endIndexRaw = reading[PropertyName.END_INDEX.value]
                    startIndexRaw = reading[PropertyName.START_INDEX.value]
                    converterFactorStr = reading[PropertyName.CONVERTER_FACTOR.value]

                    if endIndexRaw is None or converterFactorStr is None:
                        _LOGGER.debug(
                            "Skipping daily reading with missing index/converter factor: %s", reading
                        )
                        continue

                    endIndex = float(endIndexRaw)
                    converterFactor = float(converterFactorStr)

                    if startIndexRaw is not None:
                        impliedVolume = endIndex - float(startIndexRaw)
                        if impliedVolume < 0 or impliedVolume > Util.MAX_PLAUSIBLE_DAILY_VOLUME_M3:
                            _LOGGER.warning(
                                "Rejecting implausible daily reading (implied volume %.2f m3, "
                                "max plausible %.2f m3): %s",
                                impliedVolume,
                                Util.MAX_PLAUSIBLE_DAILY_VOLUME_M3,
                                reading,
                            )
                            continue

                    res = endIndex * converterFactor
                    break

        return res

    # ----------------------------------
    @staticmethod
    def toAttributes(
        username: str,
        pceIdentifier: str,
        version: str,
        pygazparData: dict[str, list[dict[str, Any]]],
        errorMessages: list[str],
    ) -> dict[str, Any]:

        res = {
            ATTR_ATTRIBUTION: HA_ATTRIBUTION,
            ATTR_VERSION: version,
            CONF_USERNAME: username,
            ATTR_PCE: pceIdentifier,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfEnergy.KILO_WATT_HOUR,
            ATTR_FRIENDLY_NAME: SENSOR_FRIENDLY_NAME,
            ATTR_ICON: ICON_GAS,
            ATTR_DEVICE_CLASS: SensorDeviceClass.ENERGY,
            ATTR_STATE_CLASS: SensorStateClass.TOTAL_INCREASING,
            ATTR_ERROR_MESSAGES: errorMessages,
            str(Frequency.HOURLY): list[dict[str, Any]](),
            str(Frequency.DAILY): list[dict[str, Any]](),
            str(Frequency.WEEKLY): list[dict[str, Any]](),
            str(Frequency.MONTHLY): list[dict[str, Any]](),
            str(Frequency.YEARLY): list[dict[str, Any]](),
        }

        if len(pygazparData) > 0:
            for frequency in Frequency:
                data = pygazparData.get(frequency.value)

                if data is not None and len(data) > 0:
                    res[str(frequency)] = data
                else:
                    res[str(frequency)] = []

        return res  # type: ignore

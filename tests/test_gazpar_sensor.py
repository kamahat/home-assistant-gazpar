import json
import logging
import os

import pytest
from pygazpar.enum import Frequency  # type: ignore

from custom_components.gazpar.sensor import (
    CONF_DATASOURCE,
    CONF_LAST_N_DAYS,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PCE_IDENTIFIER,
    CONF_SCAN_INTERVAL,
    CONF_TMPDIR,
    CONF_USERNAME,
    CONF_WAITTIME,
    GazparSensor,
    async_setup_platform,
)
from custom_components.gazpar.util import Util

# --------------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)

global_entities: list[GazparSensor] = []


# ----------------------------------
def add_entities(entities: list, flag: bool):  # pylint: disable=unused-argument
    global_entities.extend(entities)


# ----------------------------------
@pytest.mark.asyncio
async def test_live():

    config = {
        CONF_NAME: "gazpar",
        CONF_USERNAME: os.environ["GRDF_USERNAME"],
        CONF_PASSWORD: os.environ["GRDF_PASSWORD"],
        CONF_PCE_IDENTIFIER: os.environ["PCE_IDENTIFIER"],
        CONF_WAITTIME: 30,
        CONF_TMPDIR: "./tmp",
        CONF_SCAN_INTERVAL: 600,
        CONF_LAST_N_DAYS: 30,
        CONF_DATASOURCE: "json",
    }

    await async_setup_platform(None, config, add_entities)

    for entity in global_entities:
        entity.update()
        state = entity.state
        attributes = entity.extra_state_attributes

        logger.debug(f"state={state}")
        logger.debug(f"attributes={json.dumps(attributes, indent=2)}")


# ----------------------------------
@pytest.mark.asyncio
async def test_sample():

    config = {
        CONF_NAME: "gazpar",
        CONF_USERNAME: os.environ["GRDF_USERNAME"],
        CONF_PASSWORD: os.environ["GRDF_PASSWORD"],
        CONF_PCE_IDENTIFIER: os.environ["PCE_IDENTIFIER"],
        CONF_WAITTIME: 30,
        CONF_TMPDIR: "./tmp",
        CONF_SCAN_INTERVAL: 600,
        CONF_LAST_N_DAYS: 30,
        CONF_DATASOURCE: "test",
    }

    await async_setup_platform(None, config, add_entities)

    for entity in global_entities:
        entity.update()
        state = entity.state
        attributes = entity.extra_state_attributes

        logger.debug(f"state={state}")
        logger.debug(f"attributes={json.dumps(attributes, indent=2)}")


# ----------------------------------
@pytest.mark.asyncio
async def test_toAttribute():

    config = {
        CONF_NAME: "gazpar",
        CONF_USERNAME: os.environ["GRDF_USERNAME"],
        CONF_PASSWORD: os.environ["GRDF_PASSWORD"],
        CONF_PCE_IDENTIFIER: os.environ["PCE_IDENTIFIER"],
        CONF_WAITTIME: 30,
        CONF_TMPDIR: "./tmp",
        CONF_SCAN_INTERVAL: 600,
        CONF_LAST_N_DAYS: 30,
        CONF_DATASOURCE: "test",
    }

    await async_setup_platform(None, config, add_entities)

    for entity in global_entities:
        entity.update()

        attributes = Util.toAttributes(
            config[CONF_USERNAME], config[CONF_PCE_IDENTIFIER], "1.0.0", entity.dataByFrequency, []
        )

        logger.info(f"attributes={json.dumps(attributes, indent=2)}")


# ----------------------------------
def test_toState_low():

    with open("tests/resources/low_daily_data.json", "r", encoding="utf-8") as f:
        data = {Frequency.DAILY.value: json.load(f)}

    state = Util.toState(data)

    # 13702.0 * 11.268 -- anchored directly on the most recent reading's index, no more
    # phantom addition of the 3 preceding "flat" days' energy_kwh (1.1 + 1.2 + 0.7 = 3.0)
    assert state == 154394.136

    logger.info(f"state={state}")


# ----------------------------------
def test_toState_high():

    with open("tests/resources/high_daily_data.json", "r", encoding="utf-8") as f:
        data = {Frequency.DAILY.value: json.load(f)}

    state = Util.toState(data)

    assert state == 154405.404

    logger.info(f"state={state}")


# ----------------------------------
def test_toState_zero():

    with open("tests/resources/zero_daily_data.json", "r", encoding="utf-8") as f:
        data = {Frequency.DAILY.value: json.load(f)}

    state = Util.toState(data)

    assert state == 154394.136

    logger.info(f"state={state}")


# ----------------------------------
# Regression tests for the spurious-jump bug (state computed via a stale/incomplete
# backward walk instead of directly from the most recent plausible reading).
# See: https://github.com/ssenart/home-assistant-gazpar -- state jumps of hundreds to
# tens of thousands of kWh, unrelated to real GRDF consumption.
# ----------------------------------


def test_toState_frozen_index_does_not_drift():
    """Boiler switched off for an extended period: the meter index never moves.

    Real-world case that triggered this investigation: 60 consecutive days with
    start_index_m3 == end_index_m3 == 9080 (confirmed by the official GRDF export, all
    readings qualified "Mesure" / real, not estimated). The previous implementation
    walked backward through every one of these "flat" days, accumulating their
    energy_kwh and depending on how many such days were present in the fetched window
    -- silently drifting the reported state away from the true, unchanged index. The
    fixed implementation must return exactly index * converter_factor, identical
    regardless of how many frozen days precede the most recent one.
    """

    with open("tests/resources/frozen_index_60days.json", "r", encoding="utf-8") as f:
        fullData = json.load(f)

    expected = 9080 * 11.19

    # Full 60-day window.
    state_full = Util.toState({Frequency.DAILY.value: fullData})
    assert state_full == expected

    # A shorter window covering only the most recent 5 days must give the exact same
    # state. Under the previous backward-walk implementation, a change in how many
    # days the data source happened to return changed which day's index (and
    # accumulated energy_kwh) the state was based on -- this asserts that dependency
    # is gone.
    state_short = Util.toState({Frequency.DAILY.value: fullData[:5]})
    assert state_short == expected

    logger.info(f"state_full={state_full} state_short={state_short}")


# ----------------------------------
def test_toState_rejects_implausible_single_day_jump():
    """A single corrupted reading (e.g. a bad API response) must not inflate the state.

    Modeled on the production incident of 2024-10-14, where the reported state jumped
    by +52842.82 kWh in a single update although GRDF's own official export shows a
    normal, continuous index progression for that entire period (6010 -> 6012 -> 6013
    m3, i.e. ~13 kWh that day) -- proving the bad value came from a single corrupted
    reading, not a real meter event. The most recent reading here implies +4551 m3 in
    one day (~52840 kWh), which is physically implausible for a residential meter; it
    must be rejected and the state must fall back to the last plausible prior reading.
    """

    with open("tests/resources/corrupted_reading.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    state = Util.toState({Frequency.DAILY.value: data})

    # Falls back to the second (plausible) reading: 6012 * 11.61
    assert state == 6012 * 11.61

    logger.info(f"state={state}")


# ----------------------------------
def test_toState_real_grdf_window_matches_ground_truth():
    """Cross-check against the official GRDF export for the same period as the
    2024-10-14 incident (25/09/2024 - 20/10/2024, all readings qualified "Mesure").

    Confirms that on real, unmodified GRDF data the fixed implementation always
    reproduces index * converter_factor for the most recent day, and that the
    day-over-day delta around the incident date matches GRDF's real reported
    consumption instead of a multi-thousand kWh spurious jump.
    """

    with open("tests/resources/real_grdf_window_2024_10.json", "r", encoding="utf-8") as f:
        fullData = json.load(f)

    # Most recent day in the fixture is 20/10/2024: end_index_m3=6018, coef=11.61
    expected_full = 6018 * 11.61
    state_full = Util.toState({Frequency.DAILY.value: fullData})
    assert state_full == expected_full

    # Isolate the incident date (14/10/2024) and the day before it (13/10/2024).
    window = [r for r in fullData if r["time_period"] in ("14/10/2024", "13/10/2024", "12/10/2024")]
    state_1014 = Util.toState({Frequency.DAILY.value: window})
    state_1013 = Util.toState({Frequency.DAILY.value: window[1:]})

    delta = state_1014 - state_1013

    assert state_1014 == 6013 * 11.61
    # Real GRDF delta for 14/10/2024 is 1 m3 (6013 - 6012), i.e. ~11.61 kWh -- not the
    # +52842.82 kWh that was actually reported in production that day.
    assert abs(delta - (6013 - 6012) * 11.61) < 1e-6
    assert delta < 20.0

    logger.info(f"state_full={state_full} state_1014={state_1014} state_1013={state_1013} delta={delta}")

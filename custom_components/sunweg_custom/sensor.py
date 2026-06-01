"""
Sensor platform for the SunWEG integration.

All sensors belong to a single device per plant and read data exclusively
from the viewresumov2 API endpoint, which provides energy totals, current
power, inverter readings, environmental metrics, financial savings and status
information in a single response.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_PLANT_NAME

_LOGGER = logging.getLogger(__name__)


def _parse_numeric(value: Any, multipliers: Optional[dict[str, float]] = None) -> Optional[float]:
    """Extract a float from a string potentially containing units (e.g. '17.20 kWh')."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value
        for prefix in ("R$", "$", "€", "£"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        cleaned = cleaned.strip()
        parts = cleaned.split()
        try:
            number = float(parts[0].replace(",", "."))
        except ValueError:
            return None
        if len(parts) > 1 and multipliers:
            multiplier = multipliers.get(parts[1])
            if multiplier is not None:
                return number * multiplier
        return number
    return None


def _inv_reading(data: dict[str, Any], key: str) -> Optional[float]:
    """Extract a numeric value from the first inverter's last reading (ulleitura)."""
    inversores = data.get("inversores") or []
    if not inversores:
        return None
    ulleitura = inversores[0].get("ulleitura") or {}
    val = ulleitura.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _problems_count(data: dict[str, Any]) -> int:
    """Return the number of active problems (0 = no problems)."""
    return len(data.get("problemas_inv") or [])


def _problems_messages(data: dict[str, Any]) -> Optional[list[str]]:
    """Return a list of problem message strings, or None when there are none."""
    problems = data.get("problemas_inv") or []
    if not problems:
        return None
    lines: list[str] = []
    for prob in problems:
        nome = prob.get("nome") or prob.get("descricao") or ""
        for msg in prob.get("mensagem") or []:
            clean = re.sub(r"<[^>]+>", "", msg).strip()
            if clean:
                lines.append(f"[{nome}] {clean}" if nome else clean)
    return lines or None


@dataclass
class SunWegSensorDescription(SensorEntityDescription):
    """SensorEntityDescription extended with value and optional attribute extraction functions."""

    value_fn: Callable[[dict[str, Any]], Any] = lambda data: None
    attr_fn: Optional[Callable[[dict[str, Any]], Any]] = None


SENSORS: list[SunWegSensorDescription] = [
    # ── Energy ────────────────────────────────────────────────────────────────
    SunWegSensorDescription(
        key="plant_energy_day",
        name="Energia gerada hoje",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        value_fn=lambda d: _parse_numeric(
            d.get("eday_usina"), {"MWh": 1000.0, "kWh": 1.0}
        ),
    ),
    SunWegSensorDescription(
        key="plant_energy_month",
        name="Energia gerada no mês",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        value_fn=lambda d: d.get("emonth"),
    ),
    SunWegSensorDescription(
        key="plant_energy_year",
        name="Energia gerada no ano",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        value_fn=lambda d: d.get("eyear"),
    ),
    SunWegSensorDescription(
        key="plant_energy_total",
        name="Energia gerada total",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power",
        value_fn=lambda d: _parse_numeric(
            d.get("etotal_usina"), {"MWh": 1000.0, "kWh": 1.0}
        ),
    ),
    # ── Power ─────────────────────────────────────────────────────────────────
    SunWegSensorDescription(
        key="plant_power",
        name="Potência atual",
        native_unit_of_measurement="kW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
        value_fn=lambda d: _parse_numeric(
            d.get("potencia"), {"W": 0.001, "kW": 1.0, "MW": 1000.0}
        ),
    ),
    # ── Installation ──────────────────────────────────────────────────────────
    SunWegSensorDescription(
        key="plant_capacity",
        name="Capacidade instalada",
        native_unit_of_measurement="kWp",
        icon="mdi:solar-panel",
        value_fn=lambda d: d.get("capacidade"),
    ),
    # ── Status ────────────────────────────────────────────────────────────────
    SunWegSensorDescription(
        key="plant_status",
        name="Status da usina",
        icon="mdi:information-outline",
        value_fn=lambda d: d.get("status_usina"),
    ),
    SunWegSensorDescription(
        key="plant_problems",
        name="Problemas detectados",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-circle-outline",
        value_fn=_problems_count,
        attr_fn=_problems_messages,
    ),
    # ── Environmental ─────────────────────────────────────────────────────────
    SunWegSensorDescription(
        key="plant_co2_avoided",
        name="CO₂ evitado",
        native_unit_of_measurement="t",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:molecule-co2",
        value_fn=lambda d: d.get("co2_evitado"),
    ),
    SunWegSensorDescription(
        key="plant_trees_planted",
        name="Árvores plantadas",
        native_unit_of_measurement="árvore(s)",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tree",
        value_fn=lambda d: d.get("arvores_plantadas"),
    ),
    SunWegSensorDescription(
        key="plant_km_electric",
        name="Quilômetros elétricos",
        native_unit_of_measurement="km",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:car-electric",
        value_fn=lambda d: d.get("km_rodado_eletrico"),
    ),
    # ── Financial ─────────────────────────────────────────────────────────────
    SunWegSensorDescription(
        key="plant_savings_today",
        name="Economia hoje",
        native_unit_of_measurement="BRL",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash",
        value_fn=lambda d: d.get("economia_hoje"),
    ),
    SunWegSensorDescription(
        key="plant_savings_total",
        name="Economia total",
        native_unit_of_measurement="BRL",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash",
        value_fn=lambda d: d.get("economia"),
    ),
    # ── Performance ───────────────────────────────────────────────────────────
    SunWegSensorDescription(
        key="plant_yield_day",
        name="Yield diário",
        native_unit_of_measurement="kWh/kWp",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=lambda d: d.get("yield_day"),
    ),
    SunWegSensorDescription(
        key="plant_yield_month",
        name="Yield mensal",
        native_unit_of_measurement="kWh/kWp",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=lambda d: d.get("yield_mes"),
    ),
    # ── Inverter readings ─────────────────────────────────────────────────────
    SunWegSensorDescription(
        key="plant_temperature",
        name="Temperatura do inversor",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: _inv_reading(d, "Temp"),
    ),
    SunWegSensorDescription(
        key="plant_ac_frequency",
        name="Frequência AC",
        native_unit_of_measurement="Hz",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sine-wave",
        value_fn=lambda d: _inv_reading(d, "Fac1"),
    ),
    SunWegSensorDescription(
        key="plant_ac_voltage",
        name="Tensão AC",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        value_fn=lambda d: _inv_reading(d, "Uac1"),
    ),
    SunWegSensorDescription(
        key="plant_ac_current",
        name="Corrente AC",
        native_unit_of_measurement="A",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-ac",
        value_fn=lambda d: _inv_reading(d, "Iac1"),
    ),
    # ── Timestamp ─────────────────────────────────────────────────────────────
    SunWegSensorDescription(
        key="plant_last_reading",
        name="Última leitura",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
        value_fn=lambda d: d.get("_ultimaleitura_dt"),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities
) -> None:
    """Set up SunWEG sensors based on a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    plant_id: str = data["plant_id"]
    plant_name: str = entry.data.get(CONF_PLANT_NAME, plant_id)

    entities = [
        SunWegSensor(coordinator, description, plant_id, plant_name)
        for description in SENSORS
    ]
    async_add_entities(entities)


class SunWegSensor(CoordinatorEntity, SensorEntity):
    """Representation of a SunWEG sensor entity."""

    entity_description: SunWegSensorDescription

    def __init__(
        self,
        coordinator,
        description: SunWegSensorDescription,
        plant_id: str,
        plant_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._plant_id = plant_id
        self._plant_name = plant_name
        self._attr_unique_id = f"sunweg_{plant_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_name = description.name
        # Tracks the last seen inverter reading timestamp so we only push a
        # state update to HA when the inverter actually produced new data.
        self._last_inverter_ts: Any = None

    def _handle_coordinator_update(self) -> None:
        """Write state only when the inverter reading timestamp has advanced."""
        new_ts = (self.coordinator.data or {}).get("_ultimaleitura_dt")
        if new_ts != self._last_inverter_ts:
            self._last_inverter_ts = new_ts
            self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information so all sensors group under a single plant device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._plant_id)},
            name=self._plant_name,
            manufacturer="WEG",
            model="SunWEG",
        )

    @property
    def native_value(self) -> Any:
        """Return the current state of this sensor."""
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> Optional[dict[str, Any]]:
        """Return extra attributes when an attr_fn is defined for this sensor."""
        if self.entity_description.attr_fn is None:
            return None
        result = self.entity_description.attr_fn(self.coordinator.data or {})
        if result is None:
            return None
        return {"mensagens": result}




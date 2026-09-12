"""ADT7410 (Analog Devices) 高精度I2C温度センサ。

ESPHome標準コンポーネントには無い(2026.8.2時点で未収録)ため、
external_componentsとして自前実装している。温度専用IC(湿度は測れない)。

デフォルトI2Cアドレスは0x48。ADDR1/ADDR0ピンのHIGH/LOW/GND/VDD接続の
組み合わせで0x48〜0x4Bまで変更可能(データシート参照)。
"""

import esphome.codegen as cg
from esphome.components import i2c, sensor
import esphome.config_validation as cv
from esphome.const import (
    DEVICE_CLASS_TEMPERATURE,
    STATE_CLASS_MEASUREMENT,
    UNIT_CELSIUS,
)

DEPENDENCIES = ["i2c"]

adt7410_ns = cg.esphome_ns.namespace("adt7410")
ADT7410Sensor = adt7410_ns.class_(
    "ADT7410Sensor", sensor.Sensor, cg.PollingComponent, i2c.I2CDevice
)

CONFIG_SCHEMA = (
    sensor.sensor_schema(
        ADT7410Sensor,
        unit_of_measurement=UNIT_CELSIUS,
        accuracy_decimals=2,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
    )
    .extend(cv.polling_component_schema("60s"))
    .extend(i2c.i2c_device_schema(0x48))
)


async def to_code(config):
    var = await sensor.new_sensor(config)
    await cg.register_component(var, config)
    await i2c.register_i2c_device(var, config)

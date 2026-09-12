#pragma once

#include "esphome/core/component.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/i2c/i2c.h"

namespace esphome::adt7410 {

/// Analog Devices ADT7410 高精度I2C温度センサ(温度専用、湿度は非対応)。
class ADT7410Sensor final : public sensor::Sensor, public PollingComponent, public i2c::I2CDevice {
 public:
  void setup() override;
  void dump_config() override;
  void update() override;
};

}  // namespace esphome::adt7410

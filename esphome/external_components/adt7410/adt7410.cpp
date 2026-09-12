#include "adt7410.h"
#include "esphome/core/log.h"

namespace esphome::adt7410 {

static const char *const TAG = "adt7410";

// レジスタマップ(ADT7410データシート参照)
static const uint8_t ADT7410_REGISTER_TEMPERATURE = 0x00;  // 16bit, MSBファースト
static const uint8_t ADT7410_REGISTER_CONFIG = 0x03;
// Configレジスタのbit7=1で16bit解像度モード(デフォルトは13bit)。
// 16bitモードでは分解能1/128℃(=0.0078℃)/LSBなので、生値をそのまま
// 128.0で割れば℃になる(13bitモードだと符号処理が別になり面倒なため
// 常に16bitモードに固定している)。
static const uint8_t ADT7410_CONFIG_16BIT_RESOLUTION = 0x80;

void ADT7410Sensor::setup() {
  uint8_t config = ADT7410_CONFIG_16BIT_RESOLUTION;
  if (this->write_register(ADT7410_REGISTER_CONFIG, &config, 1) != i2c::ERROR_OK) {
    this->mark_failed();
    return;
  }
}

void ADT7410Sensor::dump_config() {
  LOG_SENSOR("", "ADT7410", this);
  LOG_I2C_DEVICE(this);
  if (this->is_failed()) {
    ESP_LOGE(TAG, ESP_LOG_MSG_COMM_FAIL_FOR, this->get_name().c_str());
  }
  LOG_UPDATE_INTERVAL(this);
}

void ADT7410Sensor::update() {
  uint16_t raw = 0;
  if (this->read_register(ADT7410_REGISTER_TEMPERATURE, reinterpret_cast<uint8_t *>(&raw), 2) != i2c::ERROR_OK) {
    this->status_set_warning();
    this->publish_state(NAN);
    return;
  }
  raw = i2c::i2ctohs(raw);

  // 16bit符号付き整数として解釈し、分解能1/128℃で℃に変換。
  float temperature = static_cast<int16_t>(raw) / 128.0f;

  ESP_LOGD(TAG, "'%s': Temperature=%.2f°C", this->get_name().c_str(), temperature);
  this->status_clear_warning();
  this->publish_state(temperature);
}

}  // namespace esphome::adt7410

# Lightbar — ESP32-C6 Matter Firmware
# Build with: idf.py set-target esp32c6 && idf.py build

cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS
    $ENV{ESP_MATTER_PATH}/components
    $ENV{ESP_MATTER_PATH}/device_hal/device
)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

project(lightbar)

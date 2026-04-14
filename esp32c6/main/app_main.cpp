/*
 * app_main.cpp — Lightbar Matter Device
 *
 * Exposes 2 or 3 virtual "Extended Color Light" endpoints to Matter.
 * Each endpoint controls one gradient color on the Plasma 2040.
 *
 * ── Configuration ──
 * Set NUM_LIGHTS to 2 or 3 before building:
 *   2 = two virtual lights (start + end of gradient)
 *   3 = three virtual lights (start + middle + end of gradient)
 */

/* ═══════════════════════════════════════════════════════════════════
 *  CHANGE THIS VALUE TO 2 OR 3 BEFORE FLASHING
 * ═══════════════════════════════════════════════════════════════════ */
#define NUM_LIGHTS 2
/* ═══════════════════════════════════════════════════════════════════ */

#include <cstring>
#include <cmath>
#include <algorithm>

#include "esp_log.h"
#include "esp_err.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <esp_matter.h>
#include <esp_matter_core.h>
#include <esp_matter_cluster.h>
#include <esp_matter_endpoint.h>
#include <esp_matter_attribute.h>

extern "C" {
#include "plasma_uart.h"
}

static const char *TAG = "lightbar";

using namespace esp_matter;
using namespace esp_matter::endpoint;
using namespace esp_matter::cluster;
using namespace chip;

/* ── State ─────────────────────────────────────────────────────────── */

static struct {
    bool     power;
    uint8_t  level;       /* 0-254 (Matter level) */
    uint8_t  hue;         /* 0-254 (Matter hue) */
    uint8_t  saturation;  /* 0-254 (Matter saturation) */
} light_state[3] = {
    { false, 254, 153, 254 },   /* Light 1: ~blue,  full brightness */
    { false, 254, 217, 254 },   /* Light 2: ~purple, full brightness */
    { false, 254,   0, 254 },   /* Light 3: ~red (midpoint, only if NUM_LIGHTS==3) */
};

static uint16_t light_endpoint_ids[3] = {0};

/* ── Conversion helpers ────────────────────────────────────────────── */

static inline float matter_hue_to_float(uint8_t hue)
{
    return (float)hue / 254.0f;
}

static inline float matter_sat_to_float(uint8_t sat)
{
    return (float)sat / 254.0f;
}

static inline float matter_level_to_float(uint8_t level)
{
    return (float)level / 254.0f;
}

/* ── Send gradient to Plasma ───────────────────────────────────────── */

static void sync_to_plasma(void)
{
    /* Determine global power: ON if any light is on */
    bool any_on = false;
    for (int i = 0; i < NUM_LIGHTS; i++) {
        if (light_state[i].power) {
            any_on = true;
            break;
        }
    }

    if (!any_on) {
        plasma_set_power_off();
        return;
    }

    /* Calculate average brightness from all lit endpoints */
    float total_bri = 0;
    int on_count = 0;
    for (int i = 0; i < NUM_LIGHTS; i++) {
        if (light_state[i].power) {
            total_bri += matter_level_to_float(light_state[i].level);
            on_count++;
        }
    }
    float avg_brightness = on_count > 0 ? total_bri / on_count : 1.0f;

    /* Build HSV colors for each endpoint */
    hsv_color_t colors[3];
    for (int i = 0; i < NUM_LIGHTS; i++) {
        colors[i].h = matter_hue_to_float(light_state[i].hue);
        colors[i].s = matter_sat_to_float(light_state[i].saturation);
        colors[i].v = light_state[i].power
                      ? matter_level_to_float(light_state[i].level)
                      : 0.0f;
    }

    /* Send gradient command */
    if (NUM_LIGHTS == 3) {
        plasma_set_color3(&colors[0], &colors[2], &colors[1]);
    } else {
        plasma_set_color2(&colors[0], &colors[1]);
    }

    /* Set brightness and power on */
    plasma_set_brightness(avg_brightness);
    plasma_set_power_on();
}

/* ── Matter attribute update callback ──────────────────────────────── */

static esp_err_t app_attribute_update_cb(
    attribute::callback_type_t type,
    uint16_t endpoint_id,
    uint32_t cluster_id,
    uint32_t attribute_id,
    esp_matter_attr_val_t *val,
    void *priv_data)
{
    if (type != attribute::callback_type_t::POST_UPDATE) {
        return ESP_OK;
    }

    /* Find which light index this endpoint corresponds to */
    int light_idx = -1;
    for (int i = 0; i < NUM_LIGHTS; i++) {
        if (light_endpoint_ids[i] == endpoint_id) {
            light_idx = i;
            break;
        }
    }

    if (light_idx < 0) {
        return ESP_OK; /* Not one of our endpoints */
    }

    ESP_LOGI(TAG, "Light %d: cluster=0x%04lx attr=0x%04lx",
             light_idx + 1, (unsigned long)cluster_id,
             (unsigned long)attribute_id);

    /* On/Off cluster */
    if (cluster_id == chip::app::Clusters::OnOff::Id) {
        if (attribute_id == chip::app::Clusters::OnOff::Attributes::OnOff::Id) {
            light_state[light_idx].power = val->val.b;
            ESP_LOGI(TAG, "Light %d power: %s",
                     light_idx + 1, val->val.b ? "ON" : "OFF");
        }
    }

    /* Level Control cluster */
    if (cluster_id == chip::app::Clusters::LevelControl::Id) {
        if (attribute_id == chip::app::Clusters::LevelControl::Attributes::CurrentLevel::Id) {
            light_state[light_idx].level = val->val.u8;
            ESP_LOGI(TAG, "Light %d level: %d", light_idx + 1, val->val.u8);
        }
    }

    /* Color Control cluster */
    if (cluster_id == chip::app::Clusters::ColorControl::Id) {
        if (attribute_id == chip::app::Clusters::ColorControl::Attributes::CurrentHue::Id) {
            light_state[light_idx].hue = val->val.u8;
            ESP_LOGI(TAG, "Light %d hue: %d", light_idx + 1, val->val.u8);
        }
        if (attribute_id == chip::app::Clusters::ColorControl::Attributes::CurrentSaturation::Id) {
            light_state[light_idx].saturation = val->val.u8;
            ESP_LOGI(TAG, "Light %d saturation: %d", light_idx + 1, val->val.u8);
        }
    }

    /* Sync to Plasma after any change */
    sync_to_plasma();

    return ESP_OK;
}

/* ── Matter identification callback ────────────────────────────────── */

static esp_err_t app_identification_cb(
    identification::callback_type_t type,
    uint16_t endpoint_id,
    uint8_t effect_id,
    uint8_t effect_variant,
    void *priv_data)
{
    ESP_LOGI(TAG, "Identification callback: type=%d, endpoint=%d, effect=%d",
             type, endpoint_id, effect_id);

    /* Flash the strip briefly for identification */
    if (type == identification::callback_type_t::START) {
        plasma_set_brightness(1.0f);
        hsv_color_t white = {0.0f, 0.0f, 1.0f};
        plasma_set_color2(&white, &white);
        plasma_set_power_on();
    } else if (type == identification::callback_type_t::STOP) {
        /* Restore previous state */
        sync_to_plasma();
    }

    return ESP_OK;
}

/* ── Track Matter/Thread connectivity for health reporting ──────────── */

static bool s_matter_connected = false;

/* ── Handle button presses on Plasma (unsolicited messages) ────────── */

static void on_plasma_state_change(bool power_on)
{
    ESP_LOGI(TAG, "Plasma local button: %s", power_on ? "ON" : "OFF");

    /* Update all Matter endpoints to match */
    for (int i = 0; i < NUM_LIGHTS; i++) {
        light_state[i].power = power_on;

        /* Update the Matter attribute so Apple Home reflects the change */
        esp_matter_attr_val_t val = esp_matter_bool(power_on);
        attribute::update(light_endpoint_ids[i],
                          chip::app::Clusters::OnOff::Id,
                          chip::app::Clusters::OnOff::Attributes::OnOff::Id,
                          &val);
    }
}

/**
 * Handle status updates from Plasma (color randomization, brightness changes
 * from button holds). Parses the status line and updates Matter attributes.
 */
static void on_plasma_status_update(const char *status_line)
{
    ESP_LOGI(TAG, "Plasma status update: %s", status_line);

    /* Parse brightness from "OK BRIGHTNESS <f>" */
    float bri;
    if (sscanf(status_line, "OK BRIGHTNESS %f", &bri) == 1) {
        uint8_t level = (uint8_t)(bri * 254.0f);
        for (int i = 0; i < NUM_LIGHTS; i++) {
            light_state[i].level = level;
            esp_matter_attr_val_t val = esp_matter_nullable_uint8(level);
            attribute::update(light_endpoint_ids[i],
                              chip::app::Clusters::LevelControl::Id,
                              chip::app::Clusters::LevelControl::Attributes::CurrentLevel::Id,
                              &val);
        }
        return;
    }

    /* Parse full status with colors: "OK ON BRI <f> COLORS <n> <h s v>..." */
    char power_str[8];
    int num_colors;
    float h[3], s[3], v[3];
    int parsed = sscanf(status_line,
        "OK %7s BRI %f COLORS %d %f %f %f %f %f %f %f %f %f",
        power_str, &bri, &num_colors,
        &h[0], &s[0], &v[0], &h[1], &s[1], &v[1], &h[2], &s[2], &v[2]);

    if (parsed >= 9) {
        /* Update hue/saturation for each endpoint */
        for (int i = 0; i < NUM_LIGHTS && i < num_colors; i++) {
            light_state[i].hue = (uint8_t)(h[i] * 254.0f);
            light_state[i].saturation = (uint8_t)(s[i] * 254.0f);
            light_state[i].level = (uint8_t)(bri * 254.0f);

            esp_matter_attr_val_t hue_val = esp_matter_uint8(light_state[i].hue);
            attribute::update(light_endpoint_ids[i],
                              chip::app::Clusters::ColorControl::Id,
                              chip::app::Clusters::ColorControl::Attributes::CurrentHue::Id,
                              &hue_val);

            esp_matter_attr_val_t sat_val = esp_matter_uint8(light_state[i].saturation);
            attribute::update(light_endpoint_ids[i],
                              chip::app::Clusters::ColorControl::Id,
                              chip::app::Clusters::ColorControl::Attributes::CurrentSaturation::Id,
                              &sat_val);
        }
    }
}

/* ── Matter event callback ─────────────────────────────────────────── */

static void app_event_cb(const ChipDeviceEvent *event, intptr_t arg)
{
    switch (event->Type) {
    case chip::DeviceLayer::DeviceEventType::kCommissioningComplete:
        ESP_LOGI(TAG, "Matter commissioning complete");
        s_matter_connected = true;
        break;
    case chip::DeviceLayer::DeviceEventType::kFailSafeTimerExpired:
        ESP_LOGW(TAG, "Matter fail-safe expired");
        s_matter_connected = false;
        break;
    default:
        break;
    }
}

/* ── Plasma polling task ───────────────────────────────────────────── */

static void plasma_poll_task(void *arg)
{
    while (true) {
        plasma_poll_unsolicited();
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

/* ── Health reporting task ─────────────────────────────────────────── */

static void health_report_task(void *arg)
{
    /* Wait for initial setup */
    vTaskDelay(pdMS_TO_TICKS(3000));

    while (true) {
        const char *status = s_matter_connected ? "OK" : "MATTER_ISSUE";
        plasma_send_health(status);
        vTaskDelay(pdMS_TO_TICKS(5000)); /* Report every 5s */
    }
}

/* ── Main ──────────────────────────────────────────────────────────── */

extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "╔═══════════════════════════════════════╗");
    ESP_LOGI(TAG, "║        Lightbar — Matter Device       ║");
    ESP_LOGI(TAG, "║        Virtual lights: %d              ║", NUM_LIGHTS);
    ESP_LOGI(TAG, "╚═══════════════════════════════════════╝");

    /* ── NVS ── */
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES ||
        err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    /* ── UART to Plasma ── */
    plasma_uart_init();
    plasma_set_state_change_callback(on_plasma_state_change);
    plasma_set_status_update_callback(on_plasma_status_update);

    /* Wait for Plasma to boot and send READY */
    ESP_LOGI(TAG, "Waiting for Plasma 2040...");
    for (int attempt = 0; attempt < 30; attempt++) {
        if (plasma_ping()) {
            ESP_LOGI(TAG, "Plasma 2040 connected!");
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }

    /* ── Matter Node ── */
    node::config_t node_config;
    node_t *node = node::create(&node_config, app_attribute_update_cb,
                                 app_identification_cb);
    if (!node) {
        ESP_LOGE(TAG, "Failed to create Matter node");
        return;
    }

    /* ── Create Light Endpoints ── */
    const char *light_names[] = {
        "Lightbar Start",    /* Gradient start color */
        "Lightbar End",      /* Gradient end color */
        "Lightbar Middle",   /* Gradient midpoint (only if NUM_LIGHTS == 3) */
    };

    for (int i = 0; i < NUM_LIGHTS; i++) {
        extended_color_light::config_t light_config;
        light_config.on_off.on_off = false;
        light_config.level_control.current_level = 254;
        light_config.color_control.color_mode =
            (uint8_t)chip::app::Clusters::ColorControl::ColorMode::kCurrentHueAndCurrentSaturation;
        light_config.color_control.enhanced_color_mode =
            (uint8_t)chip::app::Clusters::ColorControl::ColorMode::kCurrentHueAndCurrentSaturation;

        endpoint_t *ep = extended_color_light::create(
            node, &light_config, ENDPOINT_FLAG_NONE, NULL);

        if (!ep) {
            ESP_LOGE(TAG, "Failed to create endpoint for %s", light_names[i]);
            continue;
        }

        light_endpoint_ids[i] = endpoint::get_id(ep);
        ESP_LOGI(TAG, "Created endpoint %d: %s (id=%d)",
                 i + 1, light_names[i], light_endpoint_ids[i]);
    }

    /* ── Start Matter ── */
    err = esp_matter::start(app_event_cb);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start Matter: %s", esp_err_to_name(err));
        return;
    }
    ESP_LOGI(TAG, "Matter started. Ready for commissioning.");
    ESP_LOGI(TAG, "Use the QR code from the serial output to add to Apple Home.");

    /* ── Start Plasma polling task ── */
    xTaskCreate(plasma_poll_task, "plasma_poll", 4096, NULL, 5, NULL);

    /* ── Start health reporting task ── */
    xTaskCreate(health_report_task, "health_rpt", 4096, NULL, 3, NULL);

    ESP_LOGI(TAG, "Lightbar running.");
}

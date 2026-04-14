/*
 * plasma_uart.c — UART communication with the Plasma 2040
 */

#include "plasma_uart.h"

#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#include "driver/uart.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "plasma_uart";

static plasma_state_change_cb_t s_state_cb = NULL;
static plasma_status_update_cb_t s_status_cb = NULL;
static char s_rx_buf[PLASMA_UART_BUF_SIZE];

/* ── Init ──────────────────────────────────────────────────────────── */

void plasma_uart_init(void)
{
    const uart_config_t uart_config = {
        .baud_rate  = PLASMA_UART_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    ESP_ERROR_CHECK(uart_driver_install(PLASMA_UART_NUM,
                                        PLASMA_UART_BUF_SIZE * 2,
                                        PLASMA_UART_BUF_SIZE * 2,
                                        0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(PLASMA_UART_NUM, &uart_config));
    ESP_ERROR_CHECK(uart_set_pin(PLASMA_UART_NUM,
                                  PLASMA_UART_TX_PIN,
                                  PLASMA_UART_RX_PIN,
                                  UART_PIN_NO_CHANGE,
                                  UART_PIN_NO_CHANGE));

    ESP_LOGI(TAG, "UART%d initialized: TX=GPIO%d, RX=GPIO%d, baud=%d",
             PLASMA_UART_NUM, PLASMA_UART_TX_PIN, PLASMA_UART_RX_PIN,
             PLASMA_UART_BAUD);
}

/* ── Low-level send / receive ──────────────────────────────────────── */

static void send_cmd(const char *cmd)
{
    uart_write_bytes(PLASMA_UART_NUM, cmd, strlen(cmd));
    uart_write_bytes(PLASMA_UART_NUM, "\n", 1);
    ESP_LOGD(TAG, "TX: %s", cmd);
}

/**
 * Read a complete line (up to newline) from UART.
 * Returns number of bytes read, or 0 on timeout.
 */
static int read_line(char *buf, int max_len, int timeout_ms)
{
    int pos = 0;
    int remaining_ms = timeout_ms;
    const int poll_interval = 10;

    memset(buf, 0, max_len);

    while (remaining_ms > 0 && pos < max_len - 1) {
        int len = uart_read_bytes(PLASMA_UART_NUM, (uint8_t *)(buf + pos), 1,
                                   pdMS_TO_TICKS(poll_interval));
        if (len > 0) {
            if (buf[pos] == '\n') {
                buf[pos] = '\0';
                ESP_LOGD(TAG, "RX: %s", buf);
                return pos;
            }
            pos++;
            remaining_ms = timeout_ms; /* Reset timeout on data */
        } else {
            remaining_ms -= poll_interval;
        }
    }

    if (pos > 0) {
        buf[pos] = '\0';
        ESP_LOGD(TAG, "RX (partial): %s", buf);
    }
    return pos;
}

/**
 * Send a command and wait for the "OK" response.
 * Returns true if response starts with "OK".
 */
static bool send_and_wait(const char *cmd)
{
    /* Flush RX buffer */
    uart_flush_input(PLASMA_UART_NUM);

    send_cmd(cmd);

    char resp[PLASMA_UART_BUF_SIZE];
    int len = read_line(resp, sizeof(resp), PLASMA_RESP_TIMEOUT_MS);
    if (len <= 0) {
        ESP_LOGW(TAG, "No response to: %s", cmd);
        return false;
    }

    if (strncmp(resp, "OK", 2) == 0) {
        return true;
    }

    ESP_LOGW(TAG, "Unexpected response to '%s': %s", cmd, resp);
    return false;
}

/* ── Public API ────────────────────────────────────────────────────── */

bool plasma_set_power_on(void)
{
    ESP_LOGI(TAG, "Power ON");
    return send_and_wait("ON");
}

bool plasma_set_power_off(void)
{
    ESP_LOGI(TAG, "Power OFF");
    return send_and_wait("OFF");
}

bool plasma_set_brightness(float brightness)
{
    char cmd[64];
    snprintf(cmd, sizeof(cmd), "BRIGHTNESS %.3f", brightness);
    ESP_LOGI(TAG, "Set brightness: %.3f", brightness);
    return send_and_wait(cmd);
}

bool plasma_set_color2(const hsv_color_t *start, const hsv_color_t *end)
{
    char cmd[128];
    snprintf(cmd, sizeof(cmd), "COLOR2 %.3f %.3f %.3f %.3f %.3f %.3f",
             start->h, start->s, start->v,
             end->h, end->s, end->v);
    ESP_LOGI(TAG, "Set 2-color gradient");
    return send_and_wait(cmd);
}

bool plasma_set_color3(const hsv_color_t *start, const hsv_color_t *mid,
                        const hsv_color_t *end)
{
    char cmd[192];
    snprintf(cmd, sizeof(cmd),
             "COLOR3 %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f",
             start->h, start->s, start->v,
             mid->h, mid->s, mid->v,
             end->h, end->s, end->v);
    ESP_LOGI(TAG, "Set 3-color gradient");
    return send_and_wait(cmd);
}

bool plasma_get_status(plasma_state_t *state)
{
    uart_flush_input(PLASMA_UART_NUM);
    send_cmd("STATUS");

    char resp[PLASMA_UART_BUF_SIZE];
    int len = read_line(resp, sizeof(resp), PLASMA_RESP_TIMEOUT_MS);
    if (len <= 0 || strncmp(resp, "OK", 2) != 0) {
        ESP_LOGW(TAG, "STATUS failed");
        return false;
    }

    /* Parse: OK ON|OFF BRI <f> COLORS 2|3 <h s v> <h s v> [<h s v>] */
    char power_str[8];
    float bri;
    int num_colors;
    float h1, s1, v1, h2, s2, v2, h3, s3, v3;

    /* Try 3-color parse first */
    int parsed = sscanf(resp, "OK %7s BRI %f COLORS %d %f %f %f %f %f %f %f %f %f",
                         power_str, &bri, &num_colors,
                         &h1, &s1, &v1, &h2, &s2, &v2, &h3, &s3, &v3);

    if (parsed >= 9) {
        state->power = (strcmp(power_str, "ON") == 0);
        state->brightness = bri;
        state->num_colors = num_colors;
        state->color_start = (hsv_color_t){h1, s1, v1};
        state->color_end   = (hsv_color_t){h2, s2, v2};
        if (parsed >= 12 && num_colors == 3) {
            state->color_mid = (hsv_color_t){h3, s3, v3};
        }
        return true;
    }

    ESP_LOGW(TAG, "Could not parse STATUS response: %s", resp);
    return false;
}

bool plasma_ping(void)
{
    return send_and_wait("PING");
}

bool plasma_send_health(const char *status)
{
    char cmd[64];
    snprintf(cmd, sizeof(cmd), "HEALTH %s", status);
    ESP_LOGD(TAG, "Health: %s", status);
    return send_and_wait(cmd);
}

/* ── Unsolicited message handling ──────────────────────────────────── */

void plasma_set_state_change_callback(plasma_state_change_cb_t cb)
{
    s_state_cb = cb;
}

void plasma_set_status_update_callback(plasma_status_update_cb_t cb)
{
    s_status_cb = cb;
}

void plasma_poll_unsolicited(void)
{
    /* Check if there's data without blocking */
    size_t available = 0;
    uart_get_buffered_data_len(PLASMA_UART_NUM, &available);
    if (available == 0) return;

    int len = read_line(s_rx_buf, sizeof(s_rx_buf), 50);
    if (len <= 0) return;

    /* Handle unsolicited state changes from button presses */
    if (s_state_cb) {
        if (strcmp(s_rx_buf, "OK ON") == 0) {
            ESP_LOGI(TAG, "Plasma button: ON");
            s_state_cb(true);
        } else if (strcmp(s_rx_buf, "OK OFF") == 0) {
            ESP_LOGI(TAG, "Plasma button: OFF");
            s_state_cb(false);
        }
    }

    /* Handle status updates (from color randomization or brightness changes) */
    if (s_status_cb && strncmp(s_rx_buf, "OK ", 3) == 0) {
        /* Forward full status lines from button-triggered changes
           (e.g. brightness changes, color randomization) */
        if (strncmp(s_rx_buf + 3, "ON ", 3) == 0 ||
            strncmp(s_rx_buf + 3, "OFF ", 4) == 0) {
            /* This is a full status response — forward it */
            s_status_cb(s_rx_buf);
        } else if (strncmp(s_rx_buf, "OK BRIGHTNESS", 13) == 0) {
            s_status_cb(s_rx_buf);
        }
    }
}

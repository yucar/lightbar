/*
 * plasma_uart.h — UART communication with the Plasma 2040
 *
 * Sends commands and receives responses over UART.
 * Connected via Qw/ST cable: TX=GPIO16(D6), RX=GPIO17(D7)
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── Configuration ─────────────────────────────────────────────────── */

#define PLASMA_UART_NUM       UART_NUM_1
#define PLASMA_UART_BAUD      115200
#define PLASMA_UART_TX_PIN    16    /* XIAO D6 / GPIO16 */
#define PLASMA_UART_RX_PIN    17    /* XIAO D7 / GPIO17 */
#define PLASMA_UART_BUF_SIZE  512
#define PLASMA_RESP_TIMEOUT_MS 3000

/* ── HSV Color ─────────────────────────────────────────────────────── */

typedef struct {
    float h;  /* 0.0 - 1.0 */
    float s;  /* 0.0 - 1.0 */
    float v;  /* 0.0 - 1.0 */
} hsv_color_t;

/* ── Plasma State (mirrors the Plasma 2040's state) ────────────────── */

typedef struct {
    bool        power;
    float       brightness;    /* 0.0 - 1.0 */
    int         num_colors;    /* 2 or 3 */
    hsv_color_t color_start;
    hsv_color_t color_end;
    hsv_color_t color_mid;     /* only used when num_colors == 3 */
} plasma_state_t;

/* ── API ───────────────────────────────────────────────────────────── */

/**
 * Initialize UART connection to the Plasma 2040.
 * Call once at startup.
 */
void plasma_uart_init(void);

/**
 * Send power on command. Blocks until response or timeout.
 * Returns true on success.
 */
bool plasma_set_power_on(void);

/**
 * Send power off command. Blocks until response or timeout.
 * Returns true on success.
 */
bool plasma_set_power_off(void);

/**
 * Set brightness (0.0 - 1.0). Blocks until response or timeout.
 */
bool plasma_set_brightness(float brightness);

/**
 * Set 2-color gradient. Blocks until response or timeout.
 */
bool plasma_set_color2(const hsv_color_t *start, const hsv_color_t *end);

/**
 * Set 3-color gradient. Blocks until response or timeout.
 */
bool plasma_set_color3(const hsv_color_t *start, const hsv_color_t *mid, const hsv_color_t *end);

/**
 * Query current state from the Plasma. Fills out the state struct.
 * Returns true on success.
 */
bool plasma_get_status(plasma_state_t *state);

/**
 * Ping the Plasma to check connectivity.
 * Returns true if PONG received.
 */
bool plasma_ping(void);

/**
 * Send health status to the Plasma for status LED display.
 * status: "OK" or "MATTER_ISSUE"
 */
bool plasma_send_health(const char *status);

/**
 * Non-blocking: check for unsolicited messages from the Plasma
 * (e.g. button press notifications, color randomization).
 * Call periodically from main loop.
 */
typedef void (*plasma_state_change_cb_t)(bool power_on);
typedef void (*plasma_status_update_cb_t)(const char *status_line);
void plasma_set_state_change_callback(plasma_state_change_cb_t cb);
void plasma_set_status_update_callback(plasma_status_update_cb_t cb);
void plasma_poll_unsolicited(void);

#ifdef __cplusplus
}
#endif

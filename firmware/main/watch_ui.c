#include "watch_ui.h"

#include <stdio.h>
#include <time.h>
#include <sys/time.h>

#include "bsp/esp-bsp.h"
#include "bsp/display.h"
#include "lvgl.h"

LV_FONT_DECLARE(jetbrains_mono_27);
LV_FONT_DECLARE(jetbrains_mono_42);
LV_FONT_DECLARE(jetbrains_mono_48_icons);
LV_FONT_DECLARE(jetbrains_mono_114);

enum {
    DISPLAY_WIDTH = 410,
    DISPLAY_HEIGHT = 502,
    SAFE_INLINE = 28,
};

static const lv_color_t COLOR_BACKGROUND = LV_COLOR_MAKE(0x10, 0x13, 0x15);
static const lv_color_t COLOR_FOREGROUND = LV_COLOR_MAKE(0xCA, 0xCC, 0xCC);

static lv_obj_t *date_label;
static lv_obj_t *clock_label;
static lv_obj_t *meridiem_label;
static lv_timer_t *clock_timer;
static int16_t utc_offset_minutes;
static uint8_t hour_cycle = 24;

static lv_obj_t *make_label(lv_obj_t *parent, const char *text, const lv_font_t *font)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_label_set_text(label, text);
    lv_obj_set_style_text_font(label, font, 0);
    lv_obj_set_style_text_color(label, COLOR_FOREGROUND, 0);
    lv_obj_set_style_text_opa(label, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(label, 0, 0);
    return label;
}

static lv_obj_t *reset_screen(void)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_clean(screen);
    lv_obj_remove_style_all(screen);
    lv_obj_set_size(screen, DISPLAY_WIDTH, DISPLAY_HEIGHT);
    lv_obj_set_style_bg_color(screen, COLOR_BACKGROUND, 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

    date_label = NULL;
    clock_label = NULL;
    meridiem_label = NULL;
    if (clock_timer != NULL) {
        lv_timer_delete(clock_timer);
        clock_timer = NULL;
    }
    return screen;
}

static void update_clock(lv_timer_t *timer)
{
    (void)timer;
    if (date_label == NULL || clock_label == NULL || meridiem_label == NULL) {
        return;
    }

    time_t shifted = time(NULL) + (utc_offset_minutes * 60);
    struct tm now;
    gmtime_r(&shifted, &now);

    static const char *weekdays[] = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};
    static const char *months[] = {
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
        "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    };

    char date[24];
    char clock[8];
    snprintf(date, sizeof(date), "%s, %s %d", weekdays[now.tm_wday], months[now.tm_mon], now.tm_mday);

    int display_hour = now.tm_hour;
    const char *suffix = "";
    if (hour_cycle == 12) {
        suffix = now.tm_hour >= 12 ? "PM" : "AM";
        display_hour %= 12;
        if (display_hour == 0) {
            display_hour = 12;
        }
    }

    snprintf(clock, sizeof(clock), "%02d:%02d", display_hour, now.tm_min);
    lv_label_set_text(date_label, date);
    lv_label_set_text(clock_label, clock);
    lv_label_set_text(meridiem_label, suffix);
    if (hour_cycle == 12) {
        lv_obj_remove_flag(meridiem_label, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(meridiem_label, LV_OBJ_FLAG_HIDDEN);
    }
}

esp_err_t watch_ui_start(void)
{
    bsp_display_start();
    return bsp_display_backlight_on();
}

void watch_ui_show_pairing(uint32_t passkey)
{
    char code[16];
    snprintf(code, sizeof(code), "%03lu %03lu",
             (unsigned long)(passkey / 1000), (unsigned long)(passkey % 1000));

    bsp_display_lock(0);
    lv_obj_t *screen = reset_screen();

    lv_obj_t *eyebrow = make_label(screen, "PAIR WITH OMARCHY", &jetbrains_mono_27);
    lv_obj_set_style_text_letter_space(eyebrow, 1, 0);
    lv_obj_set_pos(eyebrow, SAFE_INLINE, 146);

    lv_obj_t *pin = make_label(screen, code, &jetbrains_mono_42);
    lv_obj_set_style_text_letter_space(pin, 2, 0);
    lv_obj_set_pos(pin, SAFE_INLINE, 205);

    lv_obj_t *hint = make_label(screen, "ENTER CODE ON DESKTOP", &jetbrains_mono_27);
    lv_obj_set_style_text_letter_space(hint, 1, 0);
    lv_obj_set_pos(hint, SAFE_INLINE, 283);
    bsp_display_unlock();
}

void watch_ui_show_time_unavailable(void)
{
    bsp_display_lock(0);
    lv_obj_t *screen = reset_screen();

    lv_obj_t *eyebrow = make_label(screen, "TIME NOT SET", &jetbrains_mono_27);
    lv_obj_set_style_text_letter_space(eyebrow, 1, 0);
    lv_obj_set_pos(eyebrow, SAFE_INLINE, 126);

    lv_obj_t *clock = make_label(screen, "--:--", &jetbrains_mono_114);
    lv_obj_set_style_text_letter_space(clock, -11, 0);
    lv_label_set_long_mode(clock, LV_LABEL_LONG_CLIP);
    lv_obj_set_size(clock, 310, 114);
    lv_obj_set_pos(clock, SAFE_INLINE - 8, 174);

    lv_obj_t *hint = make_label(screen, "CONNECT TO OMARCHY", &jetbrains_mono_27);
    lv_obj_set_style_text_letter_space(hint, 1, 0);
    lv_obj_set_pos(hint, SAFE_INLINE, 318);
    bsp_display_unlock();
}

void watch_ui_show_face(void)
{
    bsp_display_lock(0);
    lv_obj_t *screen = reset_screen();

    date_label = make_label(screen, "TUE, SEP 8", &jetbrains_mono_27);
    lv_obj_set_style_text_letter_space(date_label, 1, 0);
    lv_obj_set_pos(date_label, SAFE_INLINE, 119);

    clock_label = make_label(screen, "09:41", &jetbrains_mono_114);
    lv_obj_set_style_text_letter_space(clock_label, -11, 0);
    lv_label_set_long_mode(clock_label, LV_LABEL_LONG_CLIP);
    lv_obj_set_size(clock_label, 310, 114);
    lv_obj_set_pos(clock_label, SAFE_INLINE - 8, 154);

    meridiem_label = make_label(screen, "AM", &jetbrains_mono_27);
    lv_obj_set_pos(meridiem_label, 330, 164);
    lv_obj_add_flag(meridiem_label, LV_OBJ_FLAG_HIDDEN);

    lv_obj_t *weather_icon = make_label(screen, "", &jetbrains_mono_48_icons);
    lv_label_set_long_mode(weather_icon, LV_LABEL_LONG_CLIP);
    lv_obj_set_size(weather_icon, 64, 64);
    lv_obj_set_pos(weather_icon, SAFE_INLINE, 303);

    lv_obj_t *temperature = make_label(screen, "68°", &jetbrains_mono_42);
    lv_obj_set_pos(temperature, 92, 319);

    update_clock(NULL);
    clock_timer = lv_timer_create(update_clock, 1000, NULL);
    bsp_display_unlock();
}

void watch_ui_show_error(const char *message)
{
    bsp_display_lock(0);
    lv_obj_t *screen = reset_screen();
    lv_obj_t *label = make_label(screen, message, &jetbrains_mono_27);
    lv_obj_set_width(label, DISPLAY_WIDTH - (SAFE_INLINE * 2));
    lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
    lv_obj_set_pos(label, SAFE_INLINE, 220);
    bsp_display_unlock();
}

void watch_ui_apply_time(int64_t unix_time, int16_t offset_minutes, uint8_t cycle)
{
    struct timeval current = {
        .tv_sec = (time_t)unix_time,
        .tv_usec = 0,
    };
    settimeofday(&current, NULL);
    utc_offset_minutes = offset_minutes;
    hour_cycle = cycle == 12 ? 12 : 24;
    watch_ui_show_face();
}

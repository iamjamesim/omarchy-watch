#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "lvgl.h"

enum {
    WATCH_FACE_WIDTH = 410,
    WATCH_FACE_HEIGHT = 502,
};

typedef struct {
    uint8_t background[3];
    uint8_t foreground[3];
    uint8_t accent[3];
} watch_face_theme_t;

typedef struct {
    lv_obj_t *date;
    lv_obj_t *clock;
    lv_obj_t *meridiem;
    lv_obj_t *battery;
    lv_obj_t *battery_charge;
    lv_obj_t *battery_percentage;
    lv_obj_t *battery_touch;
    lv_obj_t *agent;
    lv_obj_t *agent_touch;
    lv_obj_t *weather_icon;
    lv_obj_t *temperature;
    lv_obj_t *condition;
    lv_obj_t *range;
    lv_obj_t *location;
} watch_face_layout_t;

extern const watch_face_theme_t WATCH_FACE_DEFAULT_THEME;

void watch_face_layout_create(lv_obj_t *screen,
                              watch_face_layout_t *layout,
                              const watch_face_theme_t *theme);
void watch_face_layout_set_time(watch_face_layout_t *layout,
                                const char *date,
                                const char *clock,
                                const char *meridiem);
void watch_face_layout_set_battery(watch_face_layout_t *layout,
                                   const char *glyph,
                                   bool charging,
                                   const char *percentage,
                                   bool show_percentage);
void watch_face_layout_set_agent(watch_face_layout_t *layout, bool visible);
void watch_face_layout_set_weather(watch_face_layout_t *layout,
                                   const char *icon,
                                   const char *temperature,
                                   const char *condition,
                                   const char *range,
                                   const char *location);

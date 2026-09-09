#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "lvgl.h"

enum {
    WATCH_FACE_WIDTH = 410,
    WATCH_FACE_HEIGHT = 502,
};

typedef struct {
    lv_obj_t *date;
    lv_obj_t *clock;
    lv_obj_t *meridiem;
    lv_obj_t *battery;
    lv_obj_t *battery_charge;
} watch_face_layout_t;

void watch_face_layout_create(lv_obj_t *screen, watch_face_layout_t *layout);
void watch_face_layout_set_time(watch_face_layout_t *layout,
                                const char *date,
                                const char *clock,
                                const char *meridiem);
void watch_face_layout_set_battery(watch_face_layout_t *layout,
                                   const char *glyph,
                                   bool charging);

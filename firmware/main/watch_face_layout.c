#include "watch_face_layout.h"

#include <string.h>

LV_FONT_DECLARE(jetbrains_mono_14_battery);
LV_FONT_DECLARE(jetbrains_mono_22);
LV_FONT_DECLARE(jetbrains_mono_27);
LV_FONT_DECLARE(jetbrains_mono_30_battery);
LV_FONT_DECLARE(jetbrains_mono_42);
LV_FONT_DECLARE(jetbrains_mono_48_icons);
LV_FONT_DECLARE(jetbrains_mono_114);

enum {
    SAFE_INLINE = 28,
    TIME_RULE_Y = 225,
    WEATHER_RULE_Y = 389,
};

static const lv_color_t COLOR_BACKGROUND = LV_COLOR_MAKE(0x10, 0x13, 0x15);
static const lv_color_t COLOR_FOREGROUND = LV_COLOR_MAKE(0xCA, 0xCC, 0xCC);

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

static lv_obj_t *make_rule(lv_obj_t *parent, int x, int y, int width, lv_opa_t opacity)
{
    lv_obj_t *rule = lv_obj_create(parent);
    lv_obj_remove_style_all(rule);
    lv_obj_set_pos(rule, x, y);
    lv_obj_set_size(rule, width, 1);
    lv_obj_set_style_bg_color(rule, COLOR_FOREGROUND, 0);
    lv_obj_set_style_bg_opa(rule, opacity, 0);
    return rule;
}

void watch_face_layout_create(lv_obj_t *screen, watch_face_layout_t *layout)
{
    memset(layout, 0, sizeof(*layout));

    lv_obj_clean(screen);
    lv_obj_remove_style_all(screen);
    lv_obj_set_size(screen, WATCH_FACE_WIDTH, WATCH_FACE_HEIGHT);
    lv_obj_set_style_bg_color(screen, COLOR_BACKGROUND, 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

    layout->date = make_label(screen, "Tue 8 Sep", &jetbrains_mono_27);
    lv_obj_set_style_text_letter_space(layout->date, 1, 0);
    lv_obj_set_pos(layout->date, SAFE_INLINE, 60);

    // U+F0080 is Nerd Fonts' Material Design Icons battery-70 fixture.
    layout->battery = make_label(screen, "󰂀", &jetbrains_mono_30_battery);
    lv_obj_set_size(layout->battery, 44, 30);
    lv_obj_set_style_text_align(layout->battery, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_transform_pivot_x(layout->battery, 22, 0);
    lv_obj_set_style_transform_pivot_y(layout->battery, 15, 0);
    lv_obj_set_style_transform_rotation(layout->battery, 900, 0);
    lv_obj_set_pos(layout->battery, 338, 57);

    // U+F0E7 is Nerd Fonts' Font Awesome bolt.
    layout->battery_charge = make_label(screen, "", &jetbrains_mono_14_battery);
    lv_obj_set_width(layout->battery_charge, 14);
    lv_obj_set_style_text_align(layout->battery_charge, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(layout->battery_charge, 335, 65);

    layout->clock = make_label(screen, "05:59", &jetbrains_mono_114);
    lv_obj_set_style_text_letter_space(layout->clock, -11, 0);
    lv_label_set_long_mode(layout->clock, LV_LABEL_LONG_CLIP);
    lv_obj_set_size(layout->clock, 310, 114);
    lv_obj_set_pos(layout->clock, SAFE_INLINE - 8, 110);

    layout->meridiem = make_label(screen, "PM", &jetbrains_mono_27);
    lv_obj_set_pos(layout->meridiem, 330, 120);

    // Three optically balanced compartments: time, weather, and location.
    make_rule(screen, SAFE_INLINE, TIME_RULE_Y,
              WATCH_FACE_WIDTH - (SAFE_INLINE * 2), LV_OPA_50);
    make_rule(screen, SAFE_INLINE, WEATHER_RULE_Y,
              WATCH_FACE_WIDTH - (SAFE_INLINE * 2), LV_OPA_50);

    // U+E302 is Nerd Fonts' partly-cloudy Weather Icons glyph.
    lv_obj_t *weather_icon = make_label(screen, "", &jetbrains_mono_48_icons);
    lv_label_set_long_mode(weather_icon, LV_LABEL_LONG_CLIP);
    lv_obj_set_size(weather_icon, 64, 64);
    lv_obj_set_pos(weather_icon, 65, 251);

    lv_obj_t *temperature = make_label(screen, "68°", &jetbrains_mono_42);
    lv_obj_set_width(temperature, 120);
    lv_obj_set_style_text_align(temperature, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(temperature, 38, 312);

    lv_obj_t *condition = make_label(screen, "PARTLY\nCLOUDY", &jetbrains_mono_27);
    lv_obj_set_style_text_letter_space(condition, 1, 0);
    lv_obj_set_style_text_line_space(condition, 2, 0);
    lv_obj_set_pos(condition, 202, 255);

    lv_obj_t *range = make_label(screen, "H 72°  L 61°", &jetbrains_mono_22);
    lv_obj_set_pos(range, 194, 328);

    // U+F041 is Nerd Fonts' Font Awesome location marker.
    lv_obj_t *location = make_label(screen, " SAN FRANCISCO", &jetbrains_mono_27);
    lv_obj_set_width(location, 330);
    lv_obj_set_style_text_align(location, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_letter_space(location, 1, 0);
    lv_label_set_long_mode(location, LV_LABEL_LONG_DOT);
    lv_obj_set_pos(location, 40, 432);
}

void watch_face_layout_set_time(watch_face_layout_t *layout,
                                const char *date,
                                const char *clock,
                                const char *meridiem)
{
    lv_label_set_text(layout->date, date);
    lv_label_set_text(layout->clock, clock);
    lv_label_set_text(layout->meridiem, meridiem);
    if (meridiem[0] == '\0') {
        lv_obj_add_flag(layout->meridiem, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_remove_flag(layout->meridiem, LV_OBJ_FLAG_HIDDEN);
    }
}

void watch_face_layout_set_battery(watch_face_layout_t *layout,
                                   const char *glyph,
                                   bool charging)
{
    lv_label_set_text(layout->battery, glyph);
    if (glyph[0] == '\0') {
        lv_obj_add_flag(layout->battery, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_remove_flag(layout->battery, LV_OBJ_FLAG_HIDDEN);
    }
    if (charging) {
        lv_obj_remove_flag(layout->battery_charge, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(layout->battery_charge, LV_OBJ_FLAG_HIDDEN);
    }
}

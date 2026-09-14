/* Design fixtures only: not compiled into firmware, no live data access. */
#pragma once

#include <math.h>

LV_FONT_DECLARE(jetbrains_mono_22);

static lv_obj_t *allowance_label(const char *text, int y, lv_color_t color)
{
    lv_obj_t *label = lv_label_create(lv_screen_active());
    lv_label_set_text(label, text);
    lv_obj_set_style_text_font(label, &jetbrains_mono_22, 0);
    lv_obj_set_style_text_color(label, color, 0);
    lv_obj_set_width(label, 354);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(label, 28, y);
    return label;
}

static void allowance_line(const lv_point_precise_t *points, unsigned count,
                           lv_color_t color, lv_opa_t opacity, int width)
{
    if (count < 2) return;
    lv_obj_t *line = lv_line_create(lv_screen_active());
    lv_line_set_points(line, points, count);
    lv_obj_set_style_line_color(line, color, 0);
    lv_obj_set_style_line_opa(line, opacity, 0);
    lv_obj_set_style_line_width(line, width, 0);
    lv_obj_set_style_line_rounded(line, true, 0);
}

static void allowance_preview(watch_face_layout_t *layout,
                              const watch_face_theme_t *theme,
                              const char *variant, int remaining)
{
    if (strcmp(variant, "rim") == 0) {
        watch_face_layout_set_allowance(layout, remaining, 1, 4 * 86400 + 20 * 3600);
        return;
    }
    const lv_color_t color = lv_color_make(theme->accent[0], theme->accent[1], theme->accent[2]);
    const lv_color_t foreground = lv_color_make(theme->foreground[0], theme->foreground[1], theme->foreground[2]);
    lv_obj_add_flag(layout->location, LV_OBJ_FLAG_HIDDEN);
    char title[48];
    if (remaining < 0) snprintf(title, sizeof(title), "CODEX  --%% LEFT");
    else snprintf(title, sizeof(title), "CODEX  %d%% LEFT", remaining);
    allowance_label(title, strcmp(variant, "bar") == 0 ? 405 : 417, foreground);
    lv_obj_t *reset = allowance_label(remaining < 0 ? "LIMITS UNAVAILABLE" : "WEEKLY  RESET 4d 20h",
                                      strcmp(variant, "bar") == 0 ? 449 : 447, color);
    lv_obj_set_style_text_opa(reset, LV_OPA_80, 0);

    if (strcmp(variant, "bar") == 0) {
        static lv_point_precise_t track[] = {{48, 440}, {362, 440}};
        static lv_point_precise_t fill[2];
        allowance_line(track, 2, color, LV_OPA_20, 4);
        if (remaining > 0) {
            fill[0] = track[0];
            fill[1] = (lv_point_precise_t){48 + 314 * remaining / 100.0, 440};
            allowance_line(fill, 2, color, LV_OPA_COVER, 4);
        }
        return;
    }

}

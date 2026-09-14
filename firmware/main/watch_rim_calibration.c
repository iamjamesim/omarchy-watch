/* Temporary local-test UI. Tap date to open; tap cycles candidates.
 * No settings or geometry are persisted by this screen. */
#include "watch_rim_geometry.h"
#include <stdio.h>

LV_FONT_DECLARE(jetbrains_mono_22);
static lv_obj_t *overlay;
static lv_obj_t *outline;
static lv_obj_t *caption;
static lv_point_precise_t points[WATCH_RIM_POINT_COUNT];
static unsigned selected;
static bool calibration_enabled = true;
static const int radii[] = {50, 60, 70, 80, 90, 100, 110, 120};

static void refresh_outline(void)
{
    watch_rim_points(points, radii[selected], WATCH_RIM_INSET);
    lv_line_set_points(outline, points, WATCH_RIM_POINT_COUNT);
    char text[120];
    snprintf(text, sizeof(text), "RIM CALIBRATION\n\nOUTER R %d PX\nINSET %d PX\n\nTAP TO CYCLE",
             radii[selected], WATCH_RIM_INSET);
    lv_label_set_text(caption, text);
}

static void calibration_event(lv_event_t *event)
{
    switch (lv_event_get_code(event)) {
    case LV_EVENT_CLICKED:
        selected = (selected + 1) % (sizeof(radii) / sizeof(radii[0]));
        refresh_outline();
        break;
    case LV_EVENT_DELETE:
        overlay = NULL;
        break;
    default:
        break;
    }
}

static void close_calibration(lv_event_t *event)
{
    (void)event;
    calibration_enabled = false;
    if (overlay != NULL) lv_obj_delete(overlay);
}

void watch_face_show_rim_calibration(void)
{
    if (overlay != NULL) return;
    calibration_enabled = true;
    overlay = lv_obj_create(lv_screen_active());
    lv_obj_remove_style_all(overlay);
    lv_obj_set_size(overlay, WATCH_FACE_WIDTH, WATCH_FACE_HEIGHT);
    lv_obj_set_style_bg_color(overlay, lv_color_hex(0x303030), 0);
    lv_obj_set_style_bg_opa(overlay, LV_OPA_COVER, 0);
    lv_obj_remove_flag(overlay, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(overlay, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(overlay, calibration_event, LV_EVENT_ALL, NULL);
    outline = lv_line_create(overlay);
    lv_obj_set_style_line_color(outline, lv_color_hex(0x7DE3ED), 0);
    lv_obj_set_style_line_width(outline, 3, 0);
    lv_obj_set_style_line_rounded(outline, true, 0);
    caption = lv_label_create(overlay);
    lv_obj_set_style_text_font(caption, &jetbrains_mono_22, 0);
    lv_obj_set_style_text_color(caption, lv_color_white(), 0);
    lv_obj_set_style_text_align(caption, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_width(caption, 330);
    lv_obj_set_pos(caption, 40, 145);
    lv_obj_t *close = lv_button_create(overlay);
    lv_obj_set_size(close, 200, 58);
    lv_obj_set_pos(close, 105, 350);
    lv_obj_add_event_cb(close, close_calibration, LV_EVENT_CLICKED, NULL);
    lv_obj_t *close_text = lv_label_create(close);
    lv_obj_set_style_text_font(close_text, &jetbrains_mono_22, 0);
    lv_label_set_text(close_text, "CLOSE");
    lv_obj_center(close_text);
    refresh_outline();
    printf("watch calibration: shown R%d\n", radii[selected]);
}

void watch_face_restore_rim_calibration(void)
{
    if (calibration_enabled) watch_face_show_rim_calibration();
}

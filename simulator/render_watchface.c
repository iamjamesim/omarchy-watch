#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lvgl.h"
#include "watch_face_layout.h"
#include "watch_profile.h"
#include "watch_rim_geometry.h"
#include <time.h>
#include "allowance_preview.h"

static void flush_display(lv_display_t *display, const lv_area_t *area, uint8_t *pixels)
{
    LV_UNUSED(area);
    LV_UNUSED(pixels);
    lv_display_flush_ready(display);
}

static int write_ppm(const char *path, const lv_draw_buf_t *draw_buffer)
{
    FILE *output = fopen(path, "wb");
    if (output == NULL) {
        perror(path);
        return 1;
    }

    fprintf(output, "P6\n%d %d\n255\n", WATCH_FACE_WIDTH, WATCH_FACE_HEIGHT);
    const uint8_t *row = draw_buffer->data;
    for (int y = 0; y < WATCH_FACE_HEIGHT; ++y) {
        for (int x = 0; x < WATCH_FACE_WIDTH; ++x) {
            const uint16_t pixel = ((const uint16_t *)row)[x];
            const uint8_t rgb[] = {
                (uint8_t)((((pixel >> 11) & 0x1f) * 255 + 15) / 31),
                (uint8_t)((((pixel >> 5) & 0x3f) * 255 + 31) / 63),
                (uint8_t)(((pixel & 0x1f) * 255 + 15) / 31),
            };
            if (fwrite(rgb, sizeof(rgb), 1, output) != 1) {
                perror(path);
                fclose(output);
                return 1;
            }
        }
        row += draw_buffer->header.stride;
    }

    fclose(output);
    return 0;
}

static int parse_color(const char *text, uint8_t color[3])
{
    unsigned int red;
    unsigned int green;
    unsigned int blue;
    char trailing;
    if (text == NULL || strlen(text) != 7 || text[0] != '#' ||
        sscanf(text + 1, "%2x%2x%2x%c", &red, &green, &blue, &trailing) != 3) {
        return 1;
    }
    color[0] = (uint8_t)red;
    color[1] = (uint8_t)green;
    color[2] = (uint8_t)blue;
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "--corner-radius") == 0) {
        printf("%d\n", WATCH_SCREEN_CORNER_RADIUS);
        return 0;
    }
    const char *allowance = getenv("WATCH_PREVIEW_ALLOWANCE");
    int remaining = 79;
    if (allowance != NULL) {
        const char *value = getenv("WATCH_PREVIEW_REMAINING");
        char *end = NULL;
        long parsed = value ? strtol(value, &end, 10) : 79;
        if ((strcmp(allowance, "bar") != 0 && strcmp(allowance, "rim") != 0) ||
            (value && (end == value || *end != '\0')) || parsed < -1 || parsed > 100) {
            fputs("allowance must be bar or rim; remaining must be -1 (unavailable) or 0..100\n", stderr);
            return 2;
        }
        remaining = (int)parsed;
    }
    const char *output_path = argc > 1 ? argv[1] : "watchface.ppm";
    watch_face_theme_t theme = WATCH_FACE_DEFAULT_THEME;
    if (argc != 1 && argc != 2 && argc != 5 && argc != 6 && argc != 8) {
        fputs(
            "usage: render-watchface [output.ppm "
            "[background foreground accent [battery% [agent-state frame-prefix]]]]\n",
            stderr
        );
        return 2;
    }
    if (argc >= 5 &&
        (parse_color(argv[2], theme.background) != 0 ||
         parse_color(argv[3], theme.foreground) != 0 ||
         parse_color(argv[4], theme.accent) != 0)) {
        fputs("colors must use #RRGGBB\n", stderr);
        return 2;
    }
    lv_init();

    lv_display_t *display = lv_display_create(WATCH_FACE_WIDTH, WATCH_FACE_HEIGHT);
    if (display == NULL) {
        fputs("Unable to create LVGL display\n", stderr);
        return 1;
    }
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);

    const size_t buffer_size = WATCH_FACE_WIDTH * WATCH_FACE_HEIGHT * 2 + LV_DRAW_BUF_ALIGN;
    uint8_t *allocation = malloc(buffer_size);
    if (allocation == NULL) {
        return 1;
    }

    lv_draw_buf_t draw_buffer;
    if (lv_draw_buf_init(&draw_buffer,
                         WATCH_FACE_WIDTH,
                         WATCH_FACE_HEIGHT,
                         LV_COLOR_FORMAT_RGB565,
                         LV_STRIDE_AUTO,
                         lv_draw_buf_align(allocation, LV_COLOR_FORMAT_RGB565),
                         buffer_size) != LV_RESULT_OK) {
        fputs("Unable to initialize LVGL draw buffer\n", stderr);
        free(allocation);
        return 1;
    }
    lv_display_set_draw_buffers(display, &draw_buffer, NULL);
    lv_display_set_render_mode(display, LV_DISPLAY_RENDER_MODE_DIRECT);
    lv_display_set_flush_cb(display, flush_display);

    watch_face_layout_t layout;
    watch_face_layout_create(lv_screen_active(), &layout, &theme);
    watch_face_layout_set_time(&layout, "Tue 8 Sep", "05:59", "PM");
    watch_face_layout_set_battery(
        &layout, "󰂀", true, argc >= 6 ? argv[5] : "70%", argc >= 6
    ); // U+F0080, battery-70
    watch_face_layout_set_weather(
        &layout, "", "68°", "PARTLY\nCLOUDY",
        "H 72°  L 61°", " SAN FRANCISCO"
    );
    watch_face_layout_set_agent(&layout, true);
    if (allowance != NULL) {
        watch_face_layout_set_connected(&layout, true);
        allowance_preview(&layout, &theme, allowance, remaining);
    }
    const char *profile_path = getenv("WATCH_PREVIEW_PROFILE");
    if (profile_path != NULL) {
        omarchy_profile_v4_t profile;
        FILE *input = fopen(profile_path, "rb");
        if (input == NULL) { perror(profile_path); return 2; }
        const size_t size = fread(&profile, 1, sizeof(profile), input);
        const bool extra = fgetc(input) != EOF;
        fclose(input);
        if (size != sizeof(profile) || extra || !omarchy_profile_v4_is_valid(&profile)) {
            fputs("Invalid v4 preview profile\n", stderr);
            return 2;
        }
        const int64_t now = time(NULL);
        watch_face_layout_set_connected(&layout, true);
        watch_face_layout_set_allowance(&layout,
            omarchy_allowance_remaining(profile.allowance_remaining, profile.allowance_updated_at,
                                        profile.allowance_resets_at, now),
            profile.allowance_window, profile.allowance_resets_at - now);
    }
    if (argc == 8) {
        watch_agent_state_t state;
        if (strcmp(argv[6], "working") == 0) state = WATCH_AGENT_WORKING;
        else if (strcmp(argv[6], "attention") == 0) state = WATCH_AGENT_ATTENTION;
        else if (strcmp(argv[6], "finished") == 0) state = WATCH_AGENT_FINISHED;
        else if (strcmp(argv[6], "idle") == 0) state = WATCH_AGENT_IDLE;
        else {
            fputs("agent-state must be idle, working, attention, or finished\n", stderr);
            return 2;
        }
        /* Start from a visible fixture, including when testing the idle state. */
        layout.agent_state = WATCH_AGENT_FINISHED;
        watch_face_layout_set_agent_state(&layout, state, true);
        const char *expected_glyph = state == WATCH_AGENT_FINISHED ? "󱜙" : "󱚣";
        if (strcmp(lv_label_get_text(layout.agent), expected_glyph) != 0) {
            fputs("Unexpected agent expression\n", stderr);
            return 1;
        }
        const unsigned duration = state == WATCH_AGENT_WORKING ? 5200 :
                                  state == WATCH_AGENT_FINISHED ? 4200 : 4000;
        for (unsigned frame = 0; frame < duration / 40; ++frame) {
            lv_anim_refr_now();
            lv_refr_now(display);
            char frame_path[1024];
            snprintf(frame_path, sizeof(frame_path), "%s-%03u.ppm", argv[7], frame);
            if (write_ppm(frame_path, &draw_buffer) != 0) return 1;
            lv_tick_inc(40);
        }
        /* Sleeping must cancel motion; waking restores it, and idle clears it. */
        watch_face_layout_set_agent_state(&layout, state, false);
        if (lv_anim_count_running() != 0 ||
                lv_obj_get_style_transform_rotation(layout.agent, 0) != 0 ||
                lv_obj_get_style_translate_x(layout.agent, 0) != 0 ||
                lv_obj_get_style_text_opa(layout.agent, 0) != LV_OPA_COVER) {
            fputs("Agent animation did not reset for sleep\n", stderr);
            return 1;
        }
        watch_face_layout_set_agent_state(&layout, state, true);
        if (state != WATCH_AGENT_IDLE && lv_anim_count_running() != 1) {
            fputs("Agent animation did not resume on wake\n", stderr);
            return 1;
        }
        watch_face_layout_set_agent_state(&layout, WATCH_AGENT_IDLE, true);
        if (lv_anim_count_running() != 0 ||
                !lv_obj_has_flag(layout.agent, LV_OBJ_FLAG_HIDDEN)) {
            fputs("Idle agent was not cleared\n", stderr);
            return 1;
        }
    }
    if (getenv("WATCH_PREVIEW_CALIBRATION") != NULL) {
        const unsigned children = lv_obj_get_child_count(lv_screen_active());
        watch_face_show_rim_calibration();
        lv_obj_t *overlay = lv_obj_get_child(lv_screen_active(), -1);
        for (unsigned i = 0; i < 8; ++i) lv_obj_send_event(overlay, LV_EVENT_SHORT_CLICKED, NULL);
        if (strstr(lv_label_get_text(lv_obj_get_child(overlay, 1)), "R 50 PX") == NULL) return 1;
        lv_obj_send_event(overlay, LV_EVENT_LONG_PRESSED, NULL);
        if (lv_obj_get_child_count(lv_screen_active()) != children) return 1;
        watch_face_show_rim_calibration();
    }
    lv_refr_now(display);

    const int result = write_ppm(output_path, &draw_buffer);
    free(allocation);
    return result;
}

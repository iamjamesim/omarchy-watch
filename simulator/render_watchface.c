#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lvgl.h"
#include "watch_face_layout.h"

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
    const char *output_path = argc > 1 ? argv[1] : "watchface.ppm";
    watch_face_theme_t theme = WATCH_FACE_DEFAULT_THEME;
    if (argc != 1 && argc != 2 && argc != 5 && argc != 6) {
        fputs(
            "usage: render-watchface [output.ppm "
            "[background foreground accent [battery%]]]\n",
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
        &layout, "󰂀", true, argc == 6 ? argv[5] : "70%", argc == 6
    ); // U+F0080, battery-70
    watch_face_layout_set_agent(&layout, true);
    lv_refr_now(display);

    const int result = write_ppm(output_path, &draw_buffer);
    free(allocation);
    return result;
}

#pragma once

#include <math.h>
#include "watch_face_layout.h"

/* Provisional visible-edge radius, pending physical calibration. The previous
 * preview guessed a 40 px rim radius at a 10 px inset (outer radius 50).
 * Manufacturer demo uses ~111 px for collision bounds, not a panel mask spec.
 * Keep the physical-edge estimate separate from the inset centerline. */
enum {
    WATCH_SCREEN_CORNER_RADIUS = 50,
    WATCH_RIM_INSET = 10,
    WATCH_RIM_POINT_COUNT = 70,
};

static inline void watch_rim_points(lv_point_precise_t *points, int outer_radius, int inset)
{
    const double right = WATCH_FACE_WIDTH - 1;
    const double bottom = WATCH_FACE_HEIGHT - 1;
    const double radius = outer_radius - inset;
    const double cx[] = {right - outer_radius, right - outer_radius, outer_radius, outer_radius};
    const double cy[] = {outer_radius, bottom - outer_radius, bottom - outer_radius, outer_radius};
    unsigned n = 0;
    points[n++] = (lv_point_precise_t){right / 2, inset};
    for (int corner = 0; corner < 4; ++corner) {
        for (int step = 0; step <= 16; ++step) {
            const double angle = (-90 + corner * 90 + step * 90.0 / 16) * 3.141592653589793 / 180;
            points[n++] = (lv_point_precise_t){cx[corner] + radius * cos(angle),
                                              cy[corner] + radius * sin(angle)};
        }
    }
    points[n] = points[0];
}

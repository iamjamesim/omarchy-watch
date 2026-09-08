#pragma once

#include <stdbool.h>
#include <stdint.h>

enum {
    OMARCHY_PROTOCOL_VERSION = 1,
    OMARCHY_PROFILE_KIND = 1,
    OMARCHY_FIRMWARE_VERSION_MAJOR = 0,
    OMARCHY_FIRMWARE_VERSION_MINOR = 1,
    OMARCHY_FIRMWARE_VERSION_PATCH = 0,
    OMARCHY_MIN_UTC_OFFSET_MINUTES = -12 * 60,
    OMARCHY_MAX_UTC_OFFSET_MINUTES = 14 * 60,
    OMARCHY_CAP_TIME_SYNC = 1 << 0,
    OMARCHY_CAP_HOUR_CYCLE = 1 << 1,
    OMARCHY_CAP_RTC = 1 << 2,
};

typedef struct __attribute__((packed)) {
    uint8_t magic[2];
    uint8_t version;
    uint8_t kind;
    uint32_t revision;
    int64_t unix_time;
    int16_t utc_offset_minutes;
    uint8_t hour_cycle;
    uint8_t reserved;
    uint8_t owner_id[16];
} omarchy_profile_v1_t;

typedef struct __attribute__((packed)) {
    uint8_t magic[2];
    uint8_t protocol_min;
    uint8_t protocol_max;
    uint8_t flags;
    uint8_t reserved[3];
    uint8_t device_id[16];
    uint32_t capabilities;
    uint8_t firmware_major;
    uint8_t firmware_minor;
    uint8_t firmware_patch;
    uint8_t reserved_end;
} omarchy_identity_v1_t;

_Static_assert(sizeof(omarchy_profile_v1_t) == 36, "profile wire size changed");
_Static_assert(sizeof(omarchy_identity_v1_t) == 32, "identity wire size changed");

static inline bool omarchy_profile_v1_is_valid(const omarchy_profile_v1_t *profile)
{
    /* The RTC driver stores a two-digit year relative to 1970. */
    const int64_t earliest_supported_time = INT64_C(1704067200);  /* 2024-01-01 */
    const int64_t latest_supported_time = INT64_C(3155759999);   /* 2069-12-31 */

    return profile != NULL && profile->magic[0] == 'O' && profile->magic[1] == 'W' &&
           profile->version == OMARCHY_PROTOCOL_VERSION &&
           profile->kind == OMARCHY_PROFILE_KIND &&
           profile->unix_time >= earliest_supported_time &&
           profile->unix_time <= latest_supported_time &&
           profile->utc_offset_minutes >= OMARCHY_MIN_UTC_OFFSET_MINUTES &&
           profile->utc_offset_minutes <= OMARCHY_MAX_UTC_OFFSET_MINUTES &&
           (profile->hour_cycle == 12 || profile->hour_cycle == 24);
}

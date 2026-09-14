#include <assert.h>
#include <stdio.h>
#include "watch_profile.h"

int main(int argc, char **argv)
{
    omarchy_profile_v4_t p = {0};
    if (argc == 2) {
        FILE *input = fopen(argv[1], "rb");
        assert(input != NULL);
        assert(fread(&p, 1, sizeof(p), input) == sizeof(p));
        assert(fgetc(input) == EOF);
        fclose(input);
        assert(omarchy_profile_v4_is_valid(&p));
    }
    p.base = (omarchy_profile_v3_t){.magic = {'O', 'W'}, .version = 4,
        .kind = 1, .unix_time = 1800000000, .hour_cycle = 24, .brightness_percent = 55};
    p.allowance_remaining = 79;
    p.allowance_window = 1;
    p.allowance_updated_at = p.base.unix_time;
    p.allowance_resets_at = p.base.unix_time + 86400;
    assert(omarchy_profile_v4_is_valid(&p));
    assert(!omarchy_profile_v3_is_valid(&p.base));
    p.base.version = 3;
    assert(omarchy_profile_v3_is_valid(&p.base));
    assert(!omarchy_profile_v4_is_valid(&p));
    p.base.version = 4;
    p.allowance_remaining = 101;
    assert(!omarchy_profile_v4_is_valid(&p));
    p.allowance_remaining = 255;
    assert(!omarchy_profile_v4_is_valid(&p));
    p.allowance_window = 0;
    p.allowance_updated_at = p.allowance_resets_at = 0;
    assert(omarchy_profile_v4_is_valid(&p));
    assert(omarchy_allowance_remaining(79, 1800000000, 1800100000, 1800001800) == 79);
    assert(omarchy_allowance_remaining(79, 1800000000, 1800100000, 1800001801) == -1);
    assert(omarchy_allowance_remaining(79, 1800000001, 1800100000, 1800000000) == -1);
    assert(omarchy_allowance_remaining(79, 1800000000, 1800000010, 1800000010) == -1);
    assert(omarchy_allowance_remaining(0, 1800000000, 1800100000, 1800000000) == 0);
    puts("Profile compatibility and allowance expiry checks passed");
    return 0;
}

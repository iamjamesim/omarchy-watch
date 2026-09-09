idf_component_register(
    SRCS
        "main.c"
        "watch_ble.c"
        "watch_face_layout.c"
        "watch_power.c"
        "watch_rtc.c"
        "watch_ui.c"
        "fonts/jetbrains_mono_14_battery.c"
        "fonts/jetbrains_mono_22.c"
        "fonts/jetbrains_mono_27.c"
        "fonts/jetbrains_mono_30_battery.c"
        "fonts/jetbrains_mono_42.c"
        "fonts/jetbrains_mono_48_icons.c"
        "fonts/jetbrains_mono_114.c"
    INCLUDE_DIRS
        "."
        "fonts"
    PRIV_REQUIRES
        bt
        esp_driver_i2c
        nvs_flash
)

target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error=cpp)

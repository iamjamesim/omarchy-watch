cmake_minimum_required(VERSION 3.16)
project(omarchy_watch_simulator C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)

set(LV_BUILD_CONF_PATH "${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h" CACHE PATH "" FORCE)
set(CONFIG_LV_BUILD_DEMOS OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_THORVG_INTERNAL OFF CACHE BOOL "" FORCE)
add_subdirectory(
    "${CMAKE_CURRENT_SOURCE_DIR}/../firmware/managed_components/lvgl__lvgl"
    "${CMAKE_CURRENT_BINARY_DIR}/lvgl"
)

add_executable(render-watchface
    render_watchface.c
    ../firmware/main/watch_face_layout.c
    ../firmware/main/watch_allowance_layout.c
    ../firmware/main/watch_rim_calibration.c
    ../firmware/main/fonts/jetbrains_mono_14_battery.c
    ../firmware/main/fonts/jetbrains_mono_22.c
    ../firmware/main/fonts/jetbrains_mono_26_connection.c
    ../firmware/main/fonts/jetbrains_mono_27.c
    ../firmware/main/fonts/jetbrains_mono_30_battery.c
    ../firmware/main/fonts/jetbrains_mono_32_agent.c
    ../firmware/main/fonts/jetbrains_mono_42.c
    ../firmware/main/fonts/jetbrains_mono_48_icons.c
    ../firmware/main/fonts/jetbrains_mono_114.c
)
target_include_directories(render-watchface PRIVATE
    ../firmware/main
    ../firmware/main/fonts
)
target_link_libraries(render-watchface PRIVATE lvgl m)

add_executable(test-profile test_profile.c)
target_include_directories(test-profile PRIVATE ../firmware/main)
# Assertions are the tests, including in the simulator's Release build.
target_compile_options(test-profile PRIVATE -UNDEBUG)

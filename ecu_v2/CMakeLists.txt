# Top-level CMake for the bike2 ECU v2 firmware.
#
# This is NOT a standalone CMake project. It is meant to be invoked
# via the MicroPython port build, which already wires the Pico SDK
# (PICO_SDK_PATH, pico_sdk_init, etc.). This file exists to allow
# unit-test builds of the C core in isolation later — for now its
# only job is to surface the source list as a static library against
# a host-side stub Pico SDK if you want to fuzz crank.c on the desktop.
#
# Real device builds use:
#
#   cd <micropython>/ports/rp2
#   make BOARD=PICO2 \
#        USER_C_MODULES=$BIKE2/ecu_v2/micropython/micropython.cmake
#
# (See micropython/micropython.cmake for the user-module wiring.)

cmake_minimum_required(VERSION 3.13)
project(bike2_ecu_v2 LANGUAGES C ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# When invoked standalone (no PICO_SDK_PATH), this is a no-op stub used
# by editor tooling / IDE indexing only.
if(NOT DEFINED PICO_SDK_PATH)
    message(STATUS "bike2_ecu_v2: PICO_SDK_PATH not set; skipping device target.")
    return()
endif()

include(${PICO_SDK_PATH}/external/pico_sdk_import.cmake)
pico_sdk_init()

add_library(ecu_core STATIC
    c_core/ipc.c
    c_core/crank.c
    c_core/scheduler.c
    c_core/ignition.c
    c_core/safety.c
    c_core/faults.c
    c_core/advance_map.c
    c_core/ecu_core.c
)

target_include_directories(ecu_core PUBLIC c_core)

pico_generate_pio_header(ecu_core
    ${CMAKE_CURRENT_LIST_DIR}/c_core/crank_capture.pio
)

target_link_libraries(ecu_core PUBLIC
    pico_stdlib
    pico_multicore
    hardware_pio
    hardware_irq
    hardware_timer
    hardware_gpio
)

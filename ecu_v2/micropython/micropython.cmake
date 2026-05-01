# micropython.cmake
# This file is consumed by MicroPython's USER_C_MODULES build path.
# Pass `-DUSER_C_MODULES=path/to/ecu_v2/micropython/micropython.cmake` to
# the MicroPython port build.

add_library(usermod_ecu INTERFACE)

target_sources(usermod_ecu INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/ecu_native.c

    # The C real-time core. We compile it INTO the MicroPython firmware
    # rather than as a separate library so the Pico SDK / MicroPython
    # heap configuration is a single image.
    ${CMAKE_CURRENT_LIST_DIR}/../c_core/ipc.c
    ${CMAKE_CURRENT_LIST_DIR}/../c_core/crank.c
    ${CMAKE_CURRENT_LIST_DIR}/../c_core/scheduler.c
    ${CMAKE_CURRENT_LIST_DIR}/../c_core/ignition.c
    ${CMAKE_CURRENT_LIST_DIR}/../c_core/safety.c
    ${CMAKE_CURRENT_LIST_DIR}/../c_core/faults.c
    ${CMAKE_CURRENT_LIST_DIR}/../c_core/advance_map.c
    ${CMAKE_CURRENT_LIST_DIR}/../c_core/ecu_core.c
)

target_include_directories(usermod_ecu INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
    ${CMAKE_CURRENT_LIST_DIR}/../c_core
)

# PIO assembly: generate crank_capture.pio.h next to the source and add
# the build directory to the include path.
pico_generate_pio_header(usermod_ecu
    ${CMAKE_CURRENT_LIST_DIR}/../c_core/crank_capture.pio
    OUTPUT_DIR ${CMAKE_CURRENT_BINARY_DIR}
)
target_include_directories(usermod_ecu INTERFACE
    ${CMAKE_CURRENT_BINARY_DIR}
)

# SDK libraries used by the C core. These are linked into the MicroPython
# port itself; we just declare the dependency here.
target_link_libraries(usermod_ecu INTERFACE
    pico_stdlib
    pico_multicore
    hardware_pio
    hardware_irq
    hardware_timer
    hardware_gpio
)

target_link_libraries(usermod INTERFACE usermod_ecu)

cmake_minimum_required(VERSION 3.13)

# Initialize the SDK
include(pico_sdk_import.cmake)

project(TimeshiftLooper_Project C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Initialize the Pico SDK
pico_sdk_init()

# Define the executable and its source files
# NOTE: If ComputerCard has a .cpp file, add it to this list!
add_executable(timeshift_looper 
    main.cpp
    usb_descriptors.c
)

# links tusb_config.h
target_include_directories(timeshift_looper PUBLIC ${CMAKE_CURRENT_LIST_DIR})

# --- MTMWS REQUIRED COMPILER FLAGS & DEFINES ---
# Catches accidental floats and provides memory usage stats
target_compile_options(timeshift_looper PRIVATE -Wdouble-promotion -Wfloat-conversion -Wall -Wextra)
target_link_options(timeshift_looper PRIVATE -Wl,--print-memory-usage)

# CRITICAL: Fixes the hardware crash-on-reset bug
target_compile_definitions(timeshift_looper PRIVATE PICO_XOSC_STARTUP_DELAY_MULTIPLIER=64)

# --- LINK LIBRARIES ---
# Combines your multicore/USB needs with the MTMWS standard hardware libraries
target_link_libraries(timeshift_looper 
    pico_stdlib 
    pico_multicore
    tinyusb_device
    tinyusb_board
    pico_unique_id 
    hardware_dma 
    hardware_i2c
    hardware_pwm 
    hardware_adc 
    hardware_spi
)

# --- MTMWS REQUIRED I/O SETTINGS ---
# OFF — stdio over USB interferes with the GPIO4 normalisation probe
pico_enable_stdio_usb(timeshift_looper 0)
pico_enable_stdio_uart(timeshift_looper 0)

# STRONGLY RECOMMENDED: Eliminates flash cache miss timing jitter.
# Your code is small enough to easily fit in the ~264KB RAM.
pico_set_binary_type(timeshift_looper copy_to_ram)

# Generate the .uf2 file!
pico_add_extra_outputs(timeshift_looper)
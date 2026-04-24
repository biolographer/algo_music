#ifndef _TUSB_CONFIG_H_
#define _TUSB_CONFIG_H_

#ifdef __cplusplus
 extern "C" {
#endif

// Mode 0 is Device mode for the RP2040
#define CFG_TUSB_RHPORT0_MODE     OPT_MODE_DEVICE


//#define CFG_TUSB_OS               OPT_OS_NONE
#ifndef CFG_TUSB_OS
  #define CFG_TUSB_OS OPT_OS_NONE
#endif

// Device stack configuration
#define CFG_TUD_ENDPOINT0_SIZE    64

// Enable MIDI and disable everything else to save RAM/CPU
#define CFG_TUD_CDC               0
#define CFG_TUD_MSC               0
#define CFG_TUD_HID               0
#define CFG_TUD_MIDI              1
#define CFG_TUD_VENDOR            0

// MIDI FIFO buffer sizes
#define CFG_TUD_MIDI_RX_BUFSIZE   64
#define CFG_TUD_MIDI_TX_BUFSIZE   64

#ifdef __cplusplus
 }
#endif

#endif
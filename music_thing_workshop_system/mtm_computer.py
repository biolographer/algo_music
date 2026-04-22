# SPDX-FileCopyrightText: Copyright (c) 2024 Tod Kurt
# SPDX-FileCopyrightText: Copyright (c) 2024 Tom Whitwell
#
# SPDX-License-Identifier: MIT
"""
`mtm_computer`
================================================================================

Library for Music Thing Modular Computer

* Author(s): Tod Kurt, based off Arduino code from Tom Whitwell

"""

import board
import digitalio
import analogio
import pwmio
import busio
import audiopwmio 
import audiomixer

# Rough calibrations from one device
#CVzeroPoint = 2085  # 0v
#CVlowPoint = 100;  # -6v 
#CVhighPoint = 4065  # +6v

CVzeroPoint = 2085 * 16  # 0v  (circuitpython duty-cycle is 16-bit always)
CVlowPoint = 100 * 16;  # -6v 
CVhighPoint = 4065 * 16  # +6v

# NB MCP4822 wrongly configured - -5 to +5v, was supposed to be +-6
DACzeroPoint = 1657  # 0v
DAClowPoint = 3031  # -5v 
DAChighPoint = 281  # +5v


# ADC input pins
AUDIO_L_IN_1 = board.GP26
AUDIO_R_IN_1 = board.GP27
MUX_IO_1 = board.A2
MUX_IO_2 = board.A3

# Mux pins
MUX_LOGIC_A = board.GP24
MUX_LOGIC_B = board.GP25

# Pulse pins
PULSE_1_INPUT = board.GP2
PULSE_2_INPUT = board.GP3

# Output pins
PULSE_1_RAW_OUT = board.GP8
PULSE_2_RAW_OUT = board.GP9
CV_1_PWM = board.GP23
CV_2_PWM = board.GP22

# DAC pins
DAC_CS = board.GP21
DAC_SDI = board.GP19
DAC_SCK = board.GP18

# DAC parameters
DAC_config_chan_A_gain = 0b0001000000000000
DAC_config_chan_B_gain = 0b1001000000000000

LED_PINS = (board.GP10, board.GP11, board.GP12, board.GP13, board.GP14, board.GP15)

CHANNEL_COUNT = 8  # three knobs, 1 switch, 2 CV  (= six? I guess two analog ins?)


def map_range(s, a1, a2, b1, b2):
    """Like Arduino ``map()``"""
    return  b1 + ((s - a1) * (b2 - b1) / (a2 - a1))

def gamma_correct(x):
    """simple and dumb LED brightness gamma-correction"""
    return min(max(int((x*x)/65535), 0), 65535)

class Computer:
    """
    Computer creates appropriate CircuitPython objects for all I/O devices.
    """
    def __init__(self):
        self.analog = [0] * CHANNEL_COUNT
        self.analog_mux1 = analogio.AnalogIn(MUX_IO_1)
        self.analog_mux2 = analogio.AnalogIn(MUX_IO_2)
        self.mux_count = 0
        self.analog_smooth_amount = 0.3

        self.leds = []
        for pin in LED_PINS:
            d = pwmio.PWMOut(pin, frequency=60_000, duty_cycle=0)
            self.leds.append(d)

        self.mux_A = digitalio.DigitalInOut(MUX_LOGIC_A)
        self.mux_B = digitalio.DigitalInOut(MUX_LOGIC_B)
        self.mux_A.switch_to_output()
        self.mux_B.switch_to_output()

        self.pulse_1_in = digitalio.DigitalInOut(PULSE_1_INPUT)
        self.pulse_2_in = digitalio.DigitalInOut(PULSE_2_INPUT)
        self.pulse_1_in.switch_to_input(pull=digitalio.Pull.UP)
        self.pulse_2_in.switch_to_input(pull=digitalio.Pull.UP)

        self.pulse_1_out = digitalio.DigitalInOut(PULSE_1_RAW_OUT)
        self.pulse_2_out = digitalio.DigitalInOut(PULSE_2_RAW_OUT)

        self.cv_1_pwm = pwmio.PWMOut(CV_1_PWM, frequency=60_000, duty_cycle=CVzeroPoint)
        self.cv_2_pwm = pwmio.PWMOut(CV_2_PWM, frequency=60_000, duty_cycle=CVzeroPoint)

        self.dac_spi = busio.SPI(clock=DAC_SCK, MOSI=DAC_SDI)
        if self.dac_spi.try_lock():
            self.dac_spi.configure(baudrate=20_000_000)
            self.dac_spi.unlock()
        else:
            print("could not configure DAC SPI")

        self.dac_cs = digitalio.DigitalInOut(DAC_CS)
        self.dac_cs.switch_to_output(value=True)

        for i in range(4):
            self.update()   # pre-read all the mux inputs

    def update(self):
        """Update the comptuer inputs. Should be called frequently"""
        self.mux_update(self.mux_count)
        self.mux_read(self.mux_count)
        self.mux_count = (self.mux_count + 1) % 4
        
    @property
    def knob_main(self):
        """Main knob position, raw 0-65535"""
        return self.analog[4]
    @property
    def knob_x(self):
        """X-knob position, raw 0-65535"""
        return self.analog[5]
    @property
    def knob_y(self):
        """Y-knob position, raw 0-65535"""
        return self.analog[6]
    @property
    def switch(self):
        """Switch position, raw 0-65535"""
        return self.analog[7]
    @property
    def cv_1_in(self):
        """Uninverted CV 1 input""" 
        return 65535 - self.analog[2]
    @property
    def cv_2_in(self):
        """Uninverted CV 1 input""" 
        return 65535 - self.analog[3]

    @property
    def cv_1_out(self):
        return self.cv_1_pwm.duty_cycle
    @cv_1_out.setter
    def cv_1_out(self,val):
        self.cv_1_pwm.duty_cycle = min(max(int(val), 0), 65535)

    @property
    def cv_2_out(self):
        return self.cv_2_pwm.duty_cycle
    @cv_2_out.setter
    def cv_2_out(self,val):
        self.cv_2_pwm.duty_cycle = min(max(int(val), 0), 65535)

    def mux_update(self, num):
        """Update the mux channel, used by ``update()``"""
        self.mux_A.value = (num >> 0) & 1
        self.mux_B.value = (num >> 1) & 1

    def mux_read(self, num):
        """Read into the ``analog`` list new values for
        the given mux channel, used by ``update()``"""
        s = self.analog_smooth_amount
        if num == 0:
            self.analog[4] = int(s*self.analog[4] + (1-s)*self.analog_mux1.value)  # main knob
            self.analog[2] = int(s*self.analog[2] + (1-s)*self.analog_mux2.value)  # CV 1 (inverted)
        elif num == 1:
            self.analog[5] = int(s*self.analog[5] + (1-s)*self.analog_mux1.value)  # X knob
            self.analog[3] = int(s*self.analog[3] + (1-s)*self.analog_mux2.value)  # CV 2 (inverted)
        elif num == 2:
            self.analog[6] = int(s*self.analog[6] + (1-s)*self.analog_mux1.value)  # Y knob
            self.analog[2] = int(s*self.analog[2] + (1-s)*self.analog_mux2.value)  # CV 1 (inverted)
        elif num == 3:
            self.analog[7] = int(s*self.analog[7] + (1-s)*self.analog_mux1.value)  # Switch
            self.analog[3] = int(s*self.analog[3] + (1-s)*self.analog_mux2.value)  # CV 2 (inverted)        

    def dac_write(self, channel, value):
        #dac_gain = DAC_config_chan_A_gain if channel == 0 else DAC_config_chan_B_gain 
        if channel == 0:
            DAC_data = DAC_config_chan_A_gain | (value & 0xFFF)
        else:
            DAC_data = DAC_config_chan_B_gain | (value & 0xFFF)

        self.dac_spi.write( bytes( (DAC_data >> 8, DAC_data & 0xFF) ) )


    def pulse_outs_to_audio(self, sample_rate=22050, voice_count=5, channel_count=2):
        """Convert the pulse outs to play PWM audio """
        if self.pulse_1_out:  # release in-use pins
            self.pulse_1_out.deinit()
            self.pulse_2_out.deinit()
        if hasattr(self, 'audio'):
            self.audio.deinit()
            
        self.audio = audiopwmio.PWMAudioOut(left_channel=PULSE_1_RAW_OUT,
                                            right_channel=PULSE_2_RAW_OUT)
        self.mixer = audiomixer.Mixer(voice_count=voice_count,
                                      sample_rate=sample_rate,
                                      channel_count=channel_count,
                                      bits_per_sample=16,
                                      samples_signed=True,
                                      buffer_size=2048
                                      )
        self.audio.play(self.mixer)  # attach mixer to audio playback


        
        
    

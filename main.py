import uasyncio as asyncio
from machine import Pin, I2C, SPI
import time
from ds3231 import DS3231

class NixieClock:
    def __init__(self):
        self.time_digits = [0, 0, 0, 0, 0, 0]  # [h1, h2, m1, m2, s1, s2]
        self.edit = {
            "active": False,       # flag to indicate if editing is active
            "digit_selected": -1,  # index of digit being edited
            "time_changed": False, # flag to indicate if any digit has changed
            "button_last_press": time.ticks_ms()
        }
        
        self.hv_power_enable = False
        self.hv_power_pin = Pin(26, Pin.OUT, value=0)

        # HV5222 pins
        self.oe_pin = Pin(6, Pin.OUT, value=0)
        self.clk_pin = Pin(2, Pin.OUT, value=0)
        self.data_pin = Pin(3, Pin.OUT, value=0)
        self.spi = SPI(0, baudrate=1000000,
                      polarity=0, 
                      phase=1,  # must be 1 for HV5222
                      bits=8, 
                      firstbit=SPI.MSB, 
                      sck=self.clk_pin, 
                      mosi=self.data_pin)

        # RTC DS3231 setup
        self.i2c = I2C(0, sda=Pin(4), scl=Pin(5))
        self.rtc = DS3231(self.i2c)

        # Buttons
        self.select_digit_button = Pin(10, Pin.IN, Pin.PULL_UP)
        self.increase_number_button = Pin(11, Pin.IN, Pin.PULL_UP)

    async def display_digits(self, digits, blink_index=None):
        value = 0
        for i, digit in enumerate(digits):
            if i == blink_index:
                continue  # Skip digit for blinking
            offset = i * 10
            bit = 0 if digit == 0 else digit
            pos = offset + bit
            value |= 1 << pos
        
        data = value.to_bytes(64, 'big')

        self.oe_pin.value(0)
        self.spi.write(data)
        self.oe_pin.value(1)

        if not self.hv_power_enable:
            self.hv_power_pin.value(1)
            self.hv_power_enable = True

    async def get_time_from_rtc(self):
        while True:
            if not self.edit["active"]:
                y, mo, d, wd, h, m, s, _ = self.rtc.datetime()
                self.time_digits[:] = [h // 10, h % 10, m // 10, m % 10, s // 10, s % 10]
            await asyncio.sleep(1)

    def save_time_to_rtc(self):
        y, mo, d, *_ = self.rtc.datetime() # Get year, month, day, weekday to later restore
        h = self.time_digits[0] * 10 + self.time_digits[1]
        m = self.time_digits[2] * 10 + self.time_digits[3]
        s = self.time_digits[4] * 10 + self.time_digits[5]
        self.rtc.datetime((y, mo, d, h, m, s, 0))

    async def display_digits_loop(self):
        blink = False
        while True:
            if self.edit["active"] and self.edit["digit_selected"] >= 0:
                await self.display_digits(self.time_digits, self.edit["digit_selected"] if blink else None)
                blink = not blink
            else:
                await self.display_digits(self.time_digits)
            await asyncio.sleep(0.5)

    async def cathode_poisoning_prevention(self):
        while True:
            await asyncio.sleep(60)
            if not self.edit["active"]:
                for i in range(10):
                    await self.display_digits([i, i, i, i, i, i])
                    await asyncio.sleep(0.05)

    async def button_handler(self):
        prev1 = self.select_digit_button.value()
        prev2 = self.increase_number_button.value()
        
        while True:
            curr1 = self.select_digit_button.value()
            curr2 = self.increase_number_button.value()
            now = time.ticks_ms()

            if prev1 and not curr1:
                self.edit["active"] = True
                self.edit["button_last_press"] = now
                self.edit["digit_selected"] = (self.edit["digit_selected"] + 1) % 6

            if prev2 and not curr2:
                if self.edit["active"] and self.edit["digit_selected"] >= 0:
                    self.edit["button_last_press"] = now
                    self.edit["time_changed"] = True
                    i = self.edit["digit_selected"]
                    if i == 0:
                        self.time_digits[i] = (self.time_digits[i] + 1) % 3
                    elif i == 1:
                        limit = 4 if self.time_digits[0] == 2 else 10
                        self.time_digits[i] = (self.time_digits[i] + 1) % limit
                    elif i == 2:
                        self.time_digits[i] = (self.time_digits[i] + 1) % 6
                    elif i == 3:
                        self.time_digits[i] = (self.time_digits[i] + 1) % 10
                    elif i == 4:
                        self.time_digits[i] = (self.time_digits[i] + 1) % 6
                    elif i == 5:
                        self.time_digits[i] = (self.time_digits[i] + 1) % 10

            prev1 = curr1
            prev2 = curr2

            if self.edit["active"] and time.ticks_diff(now, self.edit["button_last_press"]) > 3000:
                if self.edit["time_changed"]:
                    self.save_time_to_rtc()
                self.edit["active"] = False
                self.edit["digit_selected"] = -1
                self.edit["time_changed"] = False

            await asyncio.sleep_ms(50)

    async def main(self):
        await asyncio.gather(
            self.get_time_from_rtc(),
            self.display_digits_loop(),
            self.cathode_poisoning_prevention(),
            self.button_handler()
        )

NC = NixieClock()
asyncio.run(NC.main())

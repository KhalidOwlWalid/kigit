## 12th October 2026
- Worked on [[USB-UART]]
- Doing a bit of research on the kind of implementation of USB-UART that is available online
## Accelerometer
### LSM6DSM
![[Pasted image 20261014154300.png]]![[Pasted image 20261014154228.png]]
For the CS, what does it mean by 0,1? Is that basically saying that I need to have a pull up resistor on the CS pin to ensure that it is always logic high for the chip to be selected?

Actually, I understood ir wrongly, here is what I understand:
- 0: SPI mode selected, I2C disabled
- 1: SPI in idle, I2C enabled

I found a schematic from some research paper of the following schematic:
![[Pasted image 20261014155003.png|820]]
Source: https://aaltodoc.aalto.fi/server/api/core/bitstreams/0bbceb2b-3e8b-497c-96ac-d3c5c5635ea1/content

### 17th October
- Worked on implementing [[MicroSD card]]
- Found some reference online on how people do their schematics
## Power electronics
![[Pasted image 20261015111348.png]]
Right now, what I am doing is quite simple. I take the VBUS output from the USB device, which provides 5V then fed it into the ferrite bead to filter high frequency noise on the signal and then fed it into the the linear voltage dropout (LDO) regulator stepping the 5V down to 3.3V (actually in the schematic, I have chosen the wrong part it should be ..P332 (3.3V) instead of ..P302 (3.0V)).

That aside, my new goal is to be able to connect an external power supply or connect a 3.7V lipo battery which I am thinking of this one,
![[Pasted image 20261015111604.png]]
to power my circuit. The objective is simple:
- When USB is connected with no external power input, then USB is responsible for providing the power for the circuit
- When the external power input is plugged in (power supply or battery), the board then seamlessly swaps to the other power source. In this case, we are no longer limited to the current limitation of the USB power supply!

My idea in my head is to basically have a transistor that handles the switching. Upon receiving power from the power supply, this then drives the gate, and then switched it over to the battery/power supply. This is of course, easier said than done, cause I have jack shit knowledge of power electronics. I graduated from youtube academy. So this is gonna be fun figuring it out how it works by finding online reference schematic on how people have approached it!

![[Pasted image 20261015134140.png]]

Adafruit used an interesting method.

It has a schottky diode for the VBAT which I believe is the external power input, and the VBUS is from the USB. See the JSTPH pin there, which I believe where it provides the power from the battery.

I am not exactly sure how this works because I am assuming that here if it is using a JSTPH and taking a 2 pin battery, this would simply be a single cell lipo battery which means that the power being provided would be 4.2V or maybe 3.7V the same as what I am planning on considering to use. In this case, the VBUS is providing 5V would be higher than the VBAT, hence why it requires the schottky diode. It basically prevents the current from flowing in the opposite direction due to the higher potential difference from the VBUS.

This setup is not really one that I am looking for is that if an external battery is connected, the battery will be the main power supply.




Currently I am trying to figure out how my board will interface with a USB to UART interface.

I've done a bit of research which I managed to dumb it down to using either:
- CH340
- FTDI FT230XS

However, I am trying to select something that I can procure from Mouser, so CH340 is not in my list. JCLPCB does have that option, but I want to be able to buy all of the parts myself. So, in this case, I am going for the FTDI FT230XS.

I managed to find 
![[Pasted image 20261012213644.png]]
Source: https://ftdichip.com/wp-content/uploads/2025/06/DS_FT230X.pdf

![[Pasted image 20261012213724.png]]Source: https://www.mouser.com/datasheet/2/163/AN_216_Using_the_FT230X_to_design_a_GPS_Dongle-267962.pdf


My implementation of the USB-UART conversion is as below:
![[Pasted image 20261012213755.png]]

I then managed to find a reference online by from this guy: https://www.limpkin.fr/index.php?post/2014/11/27/A-Development-Board-for-the-ESP8266-03 which he showed his schematics on how he had implemented his USB->UART conversion.

![[Pasted image 20261013105958.png]]

Interestingly enough, as per the datasheet, he is routing his 3V3OUT to the CBUSx input to drive the LED. That's quite an interesting application, since I do want to be able to view if the USB chip is working or not! Another interesting thing to note is that he does not put any 10k ohm resistor to the USB Tx and Rx. The application note seems to be using that a lot and I am unsure how that works. One thing that should also not be forgotten is to invert Rx and Tx when it goes into the STM32 chip!

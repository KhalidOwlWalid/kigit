![[Pasted image 20261114144237.png]]

As per the review I had from u/Vaddieg, he recommended that a push button is better than the use of switch.
![[Pasted image 20261114181111.png]]

![[Pasted image 20261114181234.png]]

In this case, I need to ensure that the Boot0 pin is constantly pulled down to boot it from main flash memory. Unless, I want to go into its bootloader or its system memory, then the Boot0 pin needs to be high and the boot 0 pin pulled to ground (or low).

![[Pasted image 20261114181622.png]]

I have now put a SPST push button switch and the Boot0 pin is currently pulled down, while Boot1 (PB2) is also pulled down as well.

See:

[traces Update the traces for Boot0 pin with the new SPST push button](c3e4dd23.md)

# MicroSD card

I couldnt find any reference schematic on how to make your own micro sd card connection. However, I had managed to find the following blogpost and he also mentioned a mistake that he did which is very nice of him.

Quote from him:
> my next favourite mistake was the complete misunderstanding of the uSD populated switch. it really is just a switch with 2 pins. for some time saving reason I thought surely the switch pin just goes high when you insert a card. NO! the mechanical switch just bridges the 2 pins so you need to pull the line high with a resistor when connected or something similar. WRONG!!! this just does nothing :)

![[Pasted image 20261014181135.png]]
- Example source: [Hackaday post](https://hackaday.io/project/7041-multichannel-audio-dsp-field-mixer-recorder/log/158641-new-board-v12-with-tons-of-fixes-from-pcbway)

I am unsure why it is so difficult to find the mappings of SPI to the convention used for the sd card. I finally found a reference online here:
![[Pasted image 20261014201545.png]]
- [Life saver](https://www.google.com/url?sa=t&source=web&rct=j&url=https%3A%2F%2Fforum.armbian.com%2Ftopic%2F12736-orangepi-zero-external-sd-cad%2F&ved=0CBoQjhxqGAoTCNj-i8KaupcDFQAAAAAdAAAAABDcAg&opi=89978449)
My google search was: `micro sd card pinout spi -ai` and I basically went through google image to find the exact reference. Maybe I am just terrible at finding this information online.

MicroSD card implementation follows the following resources: 

![image.png](assets/f208705cde1cf202.png)

Source: [CM5 SODIMM Carrier board](https://github.com/KaiPereira/CM5-SODIMM-Carrier/blob/master/PCB/SCHEMATIC.pdf)

![image.png](assets/07df21af6267a0a9.png)

For the SPI card pinouts, I followed this reference. Taken from [here](https://forum.armbian.com/topic/12736-orangepi-zero-external-sd-cad/)


Reviews for the MicroSD card implementation can be found here:

[feat Integrate MicroSD Card into the board with SPI2](edab4545.md)

Here is my implementation on the schematic

![image.png](assets/16c1c0e0a8648a6e.png)

## Review from reddit
![image.png](assets/b60ccee4cda45053.png)

> DET_A is just a switch that closes to ground when the card seats - pull it up to 3.3V with 10k (or just the internal pull-up) and low means card present.

## PCB routing
I am now struggling for handling the placement of my sd card on the pcb editor. I want to make the board as clean as possible and right now here is what I have.
![[Pasted image 20261017075220.png]]

It is quite compact but I have not finished my routing yet. It feels quite shifted to one side due to the micro sd card. I am using this as a sort of first pass reference on how other people have done it.
![[Pasted image 20261017075326.png|657]]![[Pasted image 20261017075340.png]]
Source: https://risaksson.com/Designing-and-building-an-embedded-Linux-computer

His board looks clean with not empty spots! To be honest, my current limitation is the fact that I am planning on doing a 2 layer PCB which means that I would only have the GND plane as the 2nd layer, and for the 3.3V layer, I am simply going to find a way to route it on the board itself. Since this is a small board, I think it is generally doable and I believe this is also going to teach me some good practice on how to route my wires on the PCB.

<!-- kigit-pins [{"tab": "sch", "kind": "part", "name": "J6", "seen": {"old": "b7c058b662ed040525dea3a0c5c79d441f5f6c65", "new": "e19dcb8ad1024bece578b68fafed7612dda7abba", "side": "new"}}] -->

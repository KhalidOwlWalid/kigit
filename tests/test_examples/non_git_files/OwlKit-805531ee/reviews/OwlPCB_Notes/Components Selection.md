# Components Selection

## Voltage Regulator

[LDO Voltage Regulators Cap-Free 300mA LDO R eg A 595-TLV73333PD A 595-TLV73333PDBVR](https://www.mouser.co.uk/en/ProductDetail/Texas-Instruments/TLV73333PDBVT?qs=ifm8N2Kdrcam8xfmi4tOsQ%3D%3D)

![image.png](assets/cf1227995c90c380.png)

![image.png](assets/6bbed76f50517884.png)

The current LDO selection is limited to 300mA. I might not have enough power budget with this LDO. I am trying to spec for a higher current (>500mA), but the footprint is not the same, so I dont think it can be a direct replacement. 

I might be able to use [REG113NA-3.3/250G4](https://www.mouser.co.uk/en/ProductDetail/Texas-Instruments/REG113NA-3.3-250G4?qs=sSOk4GDDv7y9VuTqCEQ5Pg%3D%3D) as a replacement since it follows the same footprint: 

![image.png](assets/79b37401ff429fd2.png)

Both are packaged as SOT-23-5, here is the pinouts for the SOT-23-5 package

![image.png](assets/14cef63b8b2db8dd.png)

There is an NR pin which is noise reduction, this can be left unconnected.

So, I am considering to just order both.  That way, I can try and mess around with higher current margin if necessary. I still have not done my power budget calculation.


## JST-PH for VBAT

Datasheet: [JST-PH](https://www.mouser.co.uk/datasheet/3/1070/1/ePH.pdf)

![image.png](assets/706854e3b05e6e1d.png)

![image.png](assets/d942d87508f8af18.png)

### Summary
This code is the RFID part of the code for our [robot-game displayed at JavaZone 2023 in Oslo, Norway](https://github.com/jprofessionals/javazone-2023). When you have a PN532 attached to the I<sup>2</sup>C bus of a Bit:Bot XL and put it near a ISO14443-A RFID card, the card ID will be turned into colours and shown on the Bit:Bot XL neopixels.

# Hardware
PN532 is a NFC/RFID transceiver based on the 80C51 MCU. It supports SPI, I<sup>2</sup>C and HighSpeed UART.

We bought two different PN532 boards:  
![PN532 boards](doc/boards.jpg)  
It turns out the blue one is SPI only. The red one has switches to change between the 3 modes. As different pins are used for different modes, it comes with pins not soldered. For I<sup>2</sup>C, you need pins for GND, VCC, SDA, SCL, and optionally the IRQ pin. In the image you can see how we soldered them and the switch setting for selecting I<sup>2</sup>C.

We ended up mounting the board under the Bit:Bot XL using double sided foam tape and Dupont wires:  
![PN532 mounted under the robot](doc/pn532_mounted.jpg)

To connect the board to the Bit:Bot XL, we made a small PCB that fit in the robot front connector and soldered on a 5-pin Bornier connector. The front connector exposes the I<sup>2</sup>C bus and was an easy way of adding RFID-reading capability to the robot. The PCB was designed in KiCAD and was extremely simple:  
![PCB designed in KiCAD](doc/i2c_connector_kicad.png)  
Feel free to use our [Gerber file](PCB/i2c_connector.zip) if you want to order your own PCBs from [JLCPCB](https://jlcpcb.com/) or similiar companies. Make sure you order a 1.6mm thick board.

The final assembly looks like this:  
![Custom green PCB inserted into the Bit:Bot I2C connector](doc/i2c_pcb.jpg)  
(The resistor connected to +3.3V is a 2.2K pull-up resistor used for the front bumper collision detection switches. This has nothing to do with the RFID reader, except for that the front connector seems to be the only place on the robot that exposes +3.3V needed for the Micro:bit P1/P2 GPIOs)

# The PN532 protocol
The protocol is well documented in the [User Manual](https://www.nxp.com/docs/en/user-guide/141520.pdf). Main points:  
* PN532 is documented as using I<sup>2</sup>C with address 0x48 and frequency up to 400KHz. The red board we ended up with uses I<sup>2</sup>C address 0x24, so scan your I<sup>2</sup>C bus!
* Commands sent to and from the PN532 is wrapped in a thoroughly documented frame. TL;RD, frames sent _to_ PN532 looks like "0x00 0x00 0xFF <1-byte length of data bytes> <1-byte length checksum> 0xD4 <data (first byte is command code)> <1-byte data checksum> 0x00". Response from PN532 looks the same, but with 0xD5 instead of 0xD4 and the command code being the original command code plus one.
* When you send a command to PN532 (with valid checksums etc), PN532 will respond with a ACK frame. It is a minimal, no data frame "0x00 0x00 0xFF 0x00 0xFF 0x00".
* Sending a command to PN532 will cancel any pending commands. Thus, it is optional if you want to send an ACK to a response to complete it, or send the next command immediately (cancelling PN532 waiting for ACK).
* In I<sup>2</sup>C mode, whenever PN532 is busy a read will return a byte with the Least Significant Bit not set (typically 0x00). When PN532 is ready, it will return a byte with LSB set (typically 0x01) before the actual data. (There is also an IRQ pin on the PN532 and on the exposed I<sup>2</sup>C on the Bit:Bot XL, but we never got that working in microPython)

The main workflow becomes:
* Send Command#1
* Read and discard data until LSB of first byte is set
* Read and verify that received command is ACK
* Read and discard data until LSB of first byte is set
* Read response to Command#1
* Send Command#2
* ...

# Detecting a ISO14443-A card
PN532 supports detecting two cards at once, but if you ask it to detect two cards it does not return any information until both cards are found. For this reason we made the code detect one card only. Our reader was delivered with a stack of ISO14443-A cards, so that is what our code searches for. Changing this is very easy, but beware if you have other type of cards. All our cards return a 4-byte ID, but per documentation you should expect anything between 4 and 7 bytes.  

The workflow for detecting ISO14443-A cards, one at a time:
* Send command SAMConfiguration (0x14) with parameters "Normal Mode" (0x01), "No Timeout" (0x00) and "IRQ" enabled (0x01). (Our code does not use interrupt handlers, but enabling IRQ does no harm...)
* Send command RFConfiguration (0x32) with parameters "RF field" (0x01) set to 0x01 (bit1 "Auto RFCA" Off and bit0 "RF" On). This makes PN532 enable RF field immediately and without caring about other external fields.
* Send command InListPassiveTarget (0x4A) with parameters "Max Targets" set to 0x01 (only detect one card) and "BaudRate Type" set to 0x00 (detect ISO14443-A cards). In the response to this command, the first Data byte is number of targets found. If this is 0x01, a card is detected and we parse the ID out from the preceding TargetData

# Notes on implementation
Our code is based on quite a few existing PN532 libraries (sorry, I've lost track of the actual libraries), of which actually none of them worked. We removed code we didn't need, fixed their bugs, removed all the sleep()'s (so the code can co-exist with code driving the robot and code communicating wireless to a server) and actually made it work on a Bit:Bot XL.  
We used the common pattern of storing timestamps, and in the tight outer loop check current time and deltas to the stored timestamps. After sending a RFID command, the RFID code has this timeline:
* If called within 10 milliseconds, return immediately (to give PN532 some time to digest the command)
* If we're searching for a card and more than 100 ms has passed, assume there are no cards present right now.
* If we're waiting for an ACK and more than 1 second has passed, assume the command is lost. Restart the communication.
* If we're waiting for a card and more than 10 seconds has passed, resend the card search command. This will cause PN532 to drop its current command and restart searching, thus avoiding any unwanted timeouts.

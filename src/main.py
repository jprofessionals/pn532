import neopixel
from microbit import *


mostRecentTag = None
isOnTag = False

fireleds = neopixel.NeoPixel(pin13, 12)


class RFIDCom:
    READY = 1
    WAITING_FOR_ACK = 2
    WAITING_FOR_RESPONSE = 3


class BusyError(Exception):
    pass


class PN532:
    PN532_ADDRESS = 0x24

    PREAMBLE = 0x00
    STARTCODE1 = 0x00
    STARTCODE2 = 0xFF
    POSTAMBLE = 0x00

    HOSTTOPN532 = 0xD4
    PN532TOHOST = 0xD5

    COMMAND_SAMCONFIGURATION = 0x14
    COMMAND_RFCONFIGURATION = 0x32
    COMMAND_INLISTPASSIVETARGET = 0x4A

    ISO14443A = 0x00

    ACK = b"\x00\x00\xFF\x00\xFF\x00"
    FRAME_START = b"\x00\x00\xFF"

    # Give PN532 10ms to process command
    I2C_DELAY = 10

    # If there is no ACK within 1000ms, consider the command lost
    I2C_ACK_TIMEOUT = 1000

    # If no card is found within 100ms, there probably isn't one
    I2C_CARD_TAG_TIMEOUT = 100

    # To avoid timeouts/shutdowns, resend commands every 10000ms
    I2C_CARD_POLL_TIMEOUT = 10000

    def __init__(self, i2c):
        self._i2c = i2c
        self.state = RFIDCom.READY
        self.previousCommand = None
        self.previousCommandTime = 0

    def writeData(self, frame):
        print("write: ", [hex(i) for i in frame])
        self._i2c.write(self.PN532_ADDRESS, frame)

    def writeFrame(self, data):
        length = len(data)
        frame = bytearray(length + 7)
        frame[0] = self.PREAMBLE
        frame[1] = self.STARTCODE1
        frame[2] = self.STARTCODE2
        checksum = sum(frame[0:3])
        frame[3] = length & 0xFF
        frame[4] =
        for x in range(length):
            frame[5 + x] = data[x]
        checksum += sum(data)
        frame[-2] = ~checksum & 0xFF
        frame[-1] = self.POSTAMBLE
        self.writeData(bytes(frame))

    def writeCommand(self, command, params=[]):
        data = bytearray(2 + len(params))
        data[0] = self.HOSTTOPN532
        data[1] = command & 0xFF
        for i, val in enumerate(params):
            data[2 + i] = val
        self.writeFrame(data)
        return command

    def readData(self, count):
        frame = self._i2c.read(self.PN532_ADDRESS, count + 1)
        if frame[0] != 0x01:
            raise BusyError
        print("read: ", [hex(i) for i in frame])
        return frame[1:]

    def readFrame(self, length):
        response = self.readData(length + 8)
        if response[0:3] != self.FRAME_START:
            raise RuntimeError("Invalid response frame start")
        # Check length & length checksum match.
        frameLen = response[3]
        if (frameLen + response[4]) & 0xFF != 0:
            raise RuntimeError("Response length checksum mismatch")
        # Check frame checksum value matches bytes.
        checksum = sum(response[5: 5 + frameLen + 1]) & 0xFF
        if checksum != 0:
            raise RuntimeError("Response checksum mismatch:", checksum)
        # Return frame data.
        return response[5: 5 + frameLen]

    def isReady(self):
        return self._i2c.read(self.PN532_ADDRESS, 1) == b"\x01"

    def gotAck(self):
        return self.readData(len(self.ACK)) == self.ACK

    def getCardId(self, command, responseLen):
        response = self.readFrame(responseLen + 2)

        if not (response[0] == self.PN532TOHOST and response[1] == (command + 1)):
            raise RuntimeError("Invalid card response")

        cardCount = response[2]
        if cardCount != 1:
            raise RuntimeError("Unsupported card count response")

        carddataStart = 3
        carddataLength = response[carddataStart+4]
        if carddataLength > 7:
            raise RuntimeError("Unsupported card length")

        cardId = 0
        for i in range(carddataLength):
            cardId = cardId << 8 | response[carddataStart + 4 + 1 + i]

        return cardId

    def onDetectedNoCard(self):
        setLEDs(0)

    def onDetectedCard(self, cardId):
        if cardId is None:
            print('On card None')
        else:
            print('On card ', str(cardId))
            setLEDs(cardId)

    def handleRFID(self):
        try:
            currentRFIDTime = running_time()

            # Give PN532 some time to consume command
            if currentRFIDTime < (self.previousCommandTime + self.I2C_DELAY):
                return None

            if self.previousCommand == self.COMMAND_INLISTPASSIVETARGET:
                if (
                    currentRFIDTime >
                    (self.previousCommandTime + self.I2C_CARD_TAG_TIMEOUT)
                ):
                    global isOnTag
                    if isOnTag:
                        isOnTag = False
                        global mostRecentTag
                        mostRecentTag = None
                        self.onDetectedNoCard()

                if (
                    currentRFIDTime >
                    (self.previousCommandTime + self.I2C_CARD_POLL_TIMEOUT)
                ):
                    self.state = RFIDCom.READY

            if self.state != RFIDCom.READY and not self.isReady():
                if currentRFIDTime > (self.previousCommandTime + self.I2C_ACK_TIMEOUT):
                    self.state = RFIDCom.READY
                return None

            self.previousCommandTime = currentRFIDTime

            if self.state == RFIDCom.READY:
                if self.previousCommand is None:
                    self.previousCommand = self.writeCommand(
                        self.COMMAND_SAMCONFIGURATION, params=[0x01, 0x00, 0x01]
                    )
                elif self.previousCommand is self.COMMAND_SAMCONFIGURATION:
                    self.previousCommand = self.writeCommand(
                        self.COMMAND_RFCONFIGURATION, params=[0x01, 0x01]
                    )
                else:
                    self.previousCommand = self.writeCommand(
                        self.COMMAND_INLISTPASSIVETARGET, params=[0x01, self.ISO14443A]
                    )
                self.state = RFIDCom.WAITING_FOR_ACK
            elif self.state == RFIDCom.WAITING_FOR_ACK:
                if self.gotAck():
                    self.state = RFIDCom.WAITING_FOR_RESPONSE
            elif self.state == RFIDCom.WAITING_FOR_RESPONSE:
                if self.previousCommand is self.COMMAND_SAMCONFIGURATION:
                    self.readFrame(0)
                elif self.previousCommand is self.COMMAND_RFCONFIGURATION:
                    self.readFrame(0)
                elif self.previousCommand is self.COMMAND_INLISTPASSIVETARGET:
                    response = self.getCardId(
                        self.COMMAND_INLISTPASSIVETARGET, responseLen=19
                    )

                    if response is not None:
                        global isOnTag
                        isOnTag = True

                        global mostRecentTag
                        if response != mostRecentTag:
                            mostRecentTag = response
                            self.onDetectedCard(mostRecentTag)

                        self.state = RFIDCom.READY
                        return response
                self.state = RFIDCom.READY
        except (OSError, RuntimeError, BusyError):
            pass
        return None


def setLEDs(cardId):
    global fireleds

    # BitBot has 12 LEDs (6 on each side). CardId is 4 to 7 bytes.
    # For ease, consider it 9 bytes (72 bits), and let
    # each of the 12 LEDs be 6 bits (2 each for R, G and B)
    for pixelId in range(12):
        v = (cardId & (0x003F << (pixelId*6))) >> (pixelId*6)
        fireleds[pixelId] = ((v & 0x0030) << 2,
                             (v & 0x000C) << 4,
                             (v & 0x0003) << 6)
    fireleds.show()


pn532 = PN532(i2c)
while True:
    pn532.handleRFID()  # Non-blocking

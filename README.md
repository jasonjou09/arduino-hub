# arduino-hub
## Introduction
This is to maintain the code for a project of letting Arduino to act as a hub to receive MRI/Cyrix Ultrasound machine trigger-in/out functions. It can also log all the events passing Arduino. It consists of 2 parts. The first is the code that is used to be injected into Arduino; the second part is the Python scripts that creates an environment to communicate with Arduino in real-time.

## Part I : Arduino Scripts
**The light_log_v2.1.ino supports only trigger from MRI/Ultrasound. (PC is slave)**

**The omni.ino script supports bidirectional operation mode.**
  * When mode = 0, PC is master.
  * When mode = 1, PC is slave.

In the newest omni_v2.1.1 version, It'll ask you to provide the following info upon starting.
  * First, name the files that will be stored in the SD card, it'll follow the naming scheme of XXXXXX_0.txt, XXXXXX_1.txt...with the maximum length of 6 characters. When paired with Python script, the python script will automatically default the file name to MMDDHH.
  * Second, it'll ask you the mode. If it is not provided, it'll be defaulted to mode 1. When paired with Python script, It'll provide Arduino with the number given by the user (Please check Part.II for more info)

The scripts are written by FSM structure. With below states:
  * IDLE
  * REST0
  * REST
  * BLINK_ON
  * BLINK_OFF
  * FINISHED

With an if statement checking for COM input every loop.

During operation, in IDE/Python terminal:
  * `r` - halt all operations, return to initial IDLE state.
  * `s` - manual force trigger, only works when in IDLE state. This is useful for debugging and is used in Mode 0 (PC = Master) in omni.ino.

There are also several independent functions outside of loop() and setup(), namely:

  * `onFalling()` - Activates when external trigger is detected for the first time, this is to minimize response time.

  * `saveToFlashBuffer()` - Save buffer data inside Arduino SRAM into W25Q64 Flash Module. 256 Bytes at a time to fit one page of W25Q64. This operation is done once every 42 events recorded. The latency of this action is around 300~450 micro seconds.

  * `dumpFlashToSD()` - Save data to SD card, including all that in Flash modules and still in SRAM buffer. This operation is done only after one sequence is completed.

The data structure that is saved inside SRAM buffer and Flash module are like this:

```32 Bits unsigned long integer (milliseconds seconds time stamp data) | 8 Bits INT8 (Event Type) | 8 Bits INT8 (Event Duration or State)```

Event type: 0 is external trigger, 1 is LED output, 2 is electric stimulation.

### Hardware Components
* Main board: Arduino UNO 3
* The Flash module: W25Q64 8MiB Module
* [The SD card module](https://jin-hua.com.tw/page/product/show.aspx?num=13038&lang=TW)
* FR120N Separated MOSFET Switches
* A BNC Connector connecting to MRI/Cyrix


## Part II : Python Environment & Scripts
**arduino_logger.py**: It is the simplest version of environment that can communicate with Arduino, however it lacks any pylsl functionality so **it can't communicate with StEEG**. Also it does not have any automatic hand-shake protocol with Arduino. So everything is manual. But it is compatible with any Arduino scripts.

**arduino_logger_v2.1.1.py**: It has the protocols to hand-shake with omni_v2.1.1.ino and supports StEEG data synchronization. However the installation requires extra prerequisites. Before starting, it has a few following variable to look out for:
  * `COM_MODE` - It corresponds to the `mode` variable in Arduino, and it will be sent to Arduino upon initial handshake.
  * `ARDUINO_ONLY_MODE` - Let you skip the StEEG. This is used when you don't need Python to listen to StEEG signal. Note that in mode 1, when set this to `TRUE`, trigger will immediately be sent once Arduino finished initialization.

How to use them: Plug in the Arduino into PC, inject the Arduino with the desired script, then **Close the Arduino IDE** before starting the Python scripts.

### Installation
Your Python environment needs to have pyserial and pylsl installed.

`pip install pyserial`

`pip install pylsl`

After installation, inside the lib folder, there is a script called pylsl.py. Download and move the script into the `Lib\site-packages\pylsl\lib` folder. Done.

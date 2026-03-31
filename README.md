# arduino-hub
This is to maintain the code for a project of letting Arduino to act as a hub to receive MRI/Cyrix Ultrasound machine trigger-in/out functions. It can also log all the events bypassing Arduino.


**The light_log_v2.1.ino supports only trigger from MRI/Ultrasound. (PC is slave)**


**The omni.ino script supports bidirectional operation mode.**
  * When mode = 0, PC is master.
  * When mode = 1, PC is slave.

The scripts are written by FSM structure. With below states:
  * IDLE
  * REST0
  * REST
  * BLINK_ON
  * BLINK_OFF
  * FINISHED


With an if statement checking for COM input every loop.

During operation, in IDE terminal:
  * r - halt all operations, return to initial IDLE state.
  * s - manual force trigger, only works when in IDLE state. This is useful for debugging and is used in Mode 0 (PC = Master) in omni.ino.

There are also several independent functions outside of loop() and setup(), namely:

  * onFalling() - Activates when external trigger is detected for the first time, this is to minimize response time.

  * saveToFlashBuffer() - Save buffer data inside Arduino SRAM into W25Q64 Flash Module. 256 Bytes at a time to fit one page of W25Q64. This operation is done once every 42 events recorded. The latency of this action is around 300~450 micro seconds.

  * dumpFlashToSD() - Save data to SD card, including all that in Flash modules and still in SRAM buffer. This operation is done only after one sequence is completed.

The data structure that is saved inside SRAM buffer and Flash module are like this:

32 Bits unsigned long integer (milliseconds seconds time stamp data) | 8 Bits INT8 (Event Type) | 8 Bits INT8 (Event Duration or State)

Event type: 0 is external trigger, 1 is LED output.

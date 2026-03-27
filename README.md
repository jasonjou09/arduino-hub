# arduino-hub
This is to maintain the code for a project of letting Arduino to act as a hub to receive MRI/Cyrix Ultrasound machine trigger-in/out functions. It can also log all the events bypassing Arduino.

The light_

The omni.ino script supports bidirectional operation mode.
When mode = 0, PC is master.
When mode = 1, PC is slave.

The scripts are written by FSM structure. With below states:
IDLE
REST0
REST
BLINK_ON
BLINK_OFF
FINISHED

With an if statement checking for COM input every loop.
During operation, in IDE terminal:
r - halt all operations, return to initial IDLE state.
s - manual force trigger, only works when in IDLE state. This is useful for debugging and is used in Mode 0. (PC = Master)

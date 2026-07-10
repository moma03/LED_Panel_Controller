- [fixed] the LEDPanel PSU relay does not switch to off when the controller is stopped
  -> was actually the reverse: an active-low relay board energizes on GPIO init before any
     Power On command. Added relay.active_low config (led_controller/relay.py, config.py).
- [fixed] switch programs command does get stuck
  -> removed the SWITCH command/SWITCHING state entirely. Starting a program while one is
     already RUNNING now just stops the current one and starts the new one (same START
     command, same STARTING path). Also dropped the transition/switch animation.
- [ ] parameters are not passed to the program correctly / programs do not handel them correctly
- [fixed] idea: remove the swap command and just have that behaviour when starting a
  different program while one is running

- [fixed] misleadingly-named "retry" button relaunched the crashed program instead of
  settling into a stable idle state -> renamed to "reset" (display/control/reset,
  button.led_display_reset); it now force-quits the foreground, clears the error, and
  goes to IDLE instead of relaunching.
- [not reproduced] idle/shutdown font loading path -> traced through matrix_program.py's
  FONTS_DIR resolution and confirmed fonts load correctly regardless of invocation cwd;
  hardened it to use an absolute path anyway (was relative-but-consistent before).

- known pre-existing bug (unrelated, flagged separately): the Start button's MQTT
  command_template reads from select.led_display_controller_program/subprogram, but the
  actual configured entity_id is select.led_display_program/subprogram -- the button
  always sends null program/subprogram. See spawned task.

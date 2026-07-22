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
- [diagnosed, deployment not code] idle/shutdown font loading path -> code was actually
  fine (hardened it to use an absolute path anyway). Real cause on the Pi: running the
  controller from /root (mode 700) + rpi-rgb-led-matrix's default drop_privileges=true
  dropping root to the "daemon" user right after GPIO init, before font loading -- daemon
  can't traverse into /root at all. Fix: move the checkout out of /root, or set
  matrix.drop_privileges: false in config.yaml.
- [fixed] idle/shutdown screens didn't show at all when run as a systemd service ->
  program commands ("python3 programs/idle.py") are relative paths, resolved against
  whatever cwd the *controller process* happened to have -- fine in a manually-started
  shell from the repo root, silently broken under systemd unless WorkingDirectory
  exactly matched. ProcessManager.launch/run_to_completion now take an explicit `cwd`,
  and TransitionManager always passes a `_REPO_ROOT` anchored to
  led_controller/transition_manager.py's own location (two dirs up), independent of
  the controller's own cwd or config.yaml's location.

- known pre-existing bug (unrelated, flagged separately): the Start button's MQTT
  command_template reads from select.led_display_controller_program/subprogram, but the
  actual configured entity_id is select.led_display_program/subprogram -- the button
  always sends null program/subprogram. See spawned task.

- [fixed] shutdown routine freezes -> shutdown animation was launched via
  run_to_completion() BEFORE the current foreground (idle/active program) was stopped,
  so two processes fought over the matrix hardware and the animation hung forever.
  Reordered: stop foreground -> play animation -> relay off. Same bug class as the old
  switch animation hang.
- [fixed] want Ctrl+C / SIGTERM (daemon mode) to just stop the program + turn off the
  relay -> added TransitionManager.emergency_stop(), wired into
  DisplayController.run_forever()'s finally block. Skips the goodbye animation
  entirely (unlike the MQTT `shutdown` command) so the process exits promptly.
- [added] emergency restart from Home Assistant without SSH, + auto-start on boot ->
  deploy/led-panel-controller.service (systemd, auto-start + Restart=on-failure) and a
  separate deploy/led-panel-emergency-restart.service watchdog (independent process,
  no dependency on the controller's code/venv) that listens on MQTT
  (display/control/emergency_restart) and force-restarts the controller via
  `systemctl restart` -- this is what actually recovers a *hung* (not crashed)
  process, since Restart=on-failure only fires once a process has exited on its own.
  Publishes its own HA discovery button, button.led_display_emergency_restart. See
  deploy/README.md.
- [fixed] subprogram (and program) `name` had no effect on what Home Assistant showed
  -> the select entities' options were the raw config ids, not `name`. Now show `name`;
  Program.resolve_subprogram / AppConfig.resolve_program accept either the id or the
  name and always resolve to the same program/subprogram id for the actual
  {subprogram} substitution. Config load now rejects duplicate program/subprogram
  names since the dropdowns resolve by name.
- [fixed] idle.py still crashed under systemd even after rebuilding rgbmatrix in the
  venv (AttributeError: RGBMatrixOptions has no attribute 'rp1_pio') -> not a stale
  build after all; config.yaml's commands said bare "python3", which
  subprocess.Popen resolves via the *child* process's $PATH at launch time -- under
  systemd's minimal $PATH (no venv bin/ on it) that silently ran system Python and
  its separate, older rgbmatrix install in /usr/local/lib/.../dist-packages, not the
  freshly-built venv one. Added a {python} placeholder (AppConfig.render_command,
  led_controller/config.py) that expands to sys.executable -- the exact interpreter
  running the controller -- so config.yaml can say "{python} programs/idle.py ..."
  instead of a bare "python3" and always get the right venv regardless of $PATH.

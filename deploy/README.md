# Running as a daemon, with emergency restart

Two independent systemd services:

- **`led-panel-controller.service`** — the controller itself. Starts on boot,
  restarts on its own if it crashes (`Restart=on-failure`).
- **`led-panel-emergency-restart.service`** — a small standalone watchdog with no
  dependency on the controller's code or venv. It listens on MQTT and force-restarts
  `led-panel-controller.service` on demand via `systemctl restart`, which stops the
  service (SIGTERM, then SIGKILL if it doesn't exit) and starts it fresh -- this is
  what actually recovers a *hung* controller (still running, just stuck), which
  `Restart=on-failure` can't do since it only fires once a process has already exited.
  It's a separate process specifically so it keeps working even when the controller
  itself is completely unresponsive.

## Install

```
# Controller service (adjust the paths inside the unit file first if you didn't
# check out the repo to /opt/led-panel-controller)
sudo cp deploy/led-panel-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now led-panel-controller.service

# Emergency restart watchdog
sudo mkdir -p /opt/led-panel-controller/deploy
sudo cp deploy/emergency-restart-watchdog.sh deploy/restart-controller.sh /opt/led-panel-controller/deploy/
sudo chmod +x /opt/led-panel-controller/deploy/*.sh
sudo cp deploy/led-panel-emergency-restart.service /etc/systemd/system/
# Only if your broker needs credentials or isn't on localhost:1883:
sudo cp deploy/led-panel-emergency-restart.env.example /etc/led-panel-emergency-restart.env
sudo $EDITOR /etc/led-panel-emergency-restart.env
sudo systemctl daemon-reload
sudo systemctl enable --now led-panel-emergency-restart.service
```

Needs `mosquitto-clients` for `mosquitto_pub`/`mosquitto_sub`:
`sudo apt-get install mosquitto-clients`.

## Usage

- **From Home Assistant:** press the **Emergency Restart** button. It shows up
  automatically under the same **LED Display Controller** device as the rest of the
  entities (see [`../homeassistant/README.md`](../homeassistant/README.md)) — the
  watchdog publishes its own MQTT Discovery config on startup, same mechanism the
  controller itself uses.
- **From the Pi directly:** `sudo /opt/led-panel-controller/deploy/restart-controller.sh`,
  or just `sudo systemctl restart led-panel-controller.service`.
- **Checking it's alive:** `systemctl status led-panel-controller.service
  led-panel-emergency-restart.service`, or `journalctl -u led-panel-controller.service
  -f` for live logs.

## Why this doesn't go through the normal `shutdown`/`start` MQTT commands

The controller's own MQTT commands (`display/control/*`, handled by
`led_controller/mqtt_interface.py`) are processed by the controller's single
main loop. If that loop is what's hung, it can't act on any command sent to it,
emergency or not — the watchdog has to live outside the controller process
entirely, which is why it's a separate bash script and a separate service rather
than another `Command` in `led_controller/commands.py`.

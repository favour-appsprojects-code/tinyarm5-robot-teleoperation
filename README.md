# TinyARM-5 desktop teleoperation

Phase 1: Unity target → JSON/UDP → bounded position IK → MuJoCo actuators.
Original `tiny_arm_5/` files are unchanged. Physical transmission is locked.
There is now a separately gated binary sender for dry-run and loopback mock
testing; see [hardware integration](docs/hardware.md).

## Phase 1 status

Desktop Unity-to-MuJoCo motion has been manually verified: sideways, height,
depth, reset, unreachable-target rejection, and recovery. The demonstration
video has been recorded. Python's four automated test groups pass, including
reset recovery after reaching the workspace boundary and loopback UDP.

The robot mesh is displayed in MuJoCo; Unity displays the target, axes and an
amber joint-position goal preview. Quest deployment, simulated grasping and
physical execution remain unfinished.

## Final-project preparation

The desktop target now has an amber joint-position preview and explicit packet
preview/confirmation controls. **P** requests a frozen preview, **Enter** confirms
it within five seconds, **G** toggles logical gripper state, and **Escape** disables
output. Start with `--output-profile python/config/mock.json` for a no-transmission
dry run. Target movement alone never sends a robot command. All physical motor
calibration remains unknown; the example receiver IDs/angles are not assumed valid.

[Hardware mapping, commands and tests](docs/hardware.md) ·
[Quest status, prepared controller adapter and remaining setup](docs/quest3.md)

Moving to another computer? Follow [Quest-connected laptop setup](docs/laptop-setup.md).
The intended routing is Quest/Unity -> Python laptop **JSON UDP 5006** ->
physical receiver **192.168.1.244:5005 binary UDP**. Physical execution remains
locked until receiver mapping/calibration and explicit authorization are ready.

## Run the demonstration

Open PowerShell in this folder and start Python:

```powershell
.\.venv\Scripts\python.exe python/server.py
```

Expect `Ready UDP 127.0.0.1 5005` and a MuJoCo viewer. Leave it running.

Open the `unity` folder as a project in Unity Hub using **6000.4.8f1**.
Open `Assets/Scenes/DesktopDemo.unity`. If the scene is absent, select
**TinyARM → Create Desktop Demo**. Press Play and click the Game view.

- **W/S:** forward/back; **A/D:** left/right.
- **Q/E:** down/up; **R:** reset to the tested initial target.
- **I/K:** rotate about tool X (red); **J/L:** tool Y (green);
  **U/O:** tool Z (blue), at 35 degrees/s. **T:** toggle orientation tracking.
- **H:** move to a tested orientation-demo pose with more joint headroom,
  and align target orientation to the accepted tool pose. Wait for settling,
  then try I or U. **R** still returns to the original reset pose.
- Coloured axes appear on the sphere automatically in Play mode. Matching
  axes on the MuJoCo tip show its actual orientation. **R** resets both the
  target position and the initial reachable tool orientation.
- Position has priority. Orientation is best effort; the display reports
  `matched` (within 5 degrees) or `limited / best effort`. A green sphere
  means position is reachable, even if the requested rotation cannot match.
- Green sphere: position IK converged within 1.5 mm. Red: rejected target;
  last valid goal retained. Yellow: no recent Python feedback.
- The scene displays target coordinates and IK residual. That residual is a
  kinematic prediction; actuator tracking has its own small error.
- Stop Play to stop transmitting; Python freezes its command ramp after 0.5 s.
  Close the MuJoCo viewer or press Ctrl+C in Python to stop the server.

Move slowly around the initial target for the recording. Keep Unity Game view
and MuJoCo visible side by side. Show R/reset, small WASD/QE moves, green
feedback, and corresponding arm motion. Finally demonstrate a red rejected
target by moving well outside reach. Record only after confirming both windows
respond. Upload the resulting video as unlisted on YouTube by November 12,
11:59 PM; recording and upload are manual.

## Recreate Python environment

Python 3.13 was used. Only MuJoCo and NumPy are direct dependencies.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python/requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s python -p "test*.py" -v
```

Tests cover model loading, three IK targets, actuator tracking, unreachable
targets, malformed messages, actual loopback UDP feedback, and duplicates.
See [engineering notes](docs/phase1.md) for protocol, findings, and limitations.
See [orientation tracking](docs/orientation.md) for the pose protocol, test
results, and a step-by-step rotation check.

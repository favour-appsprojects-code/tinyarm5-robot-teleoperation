# TinyARM-5 desktop teleoperation

Phase 1: Unity target → JSON/UDP → bounded position IK → MuJoCo actuators.
Original `tiny_arm_5/` files are unchanged. No physical-robot output exists.

## Phase 1 status

Desktop Unity-to-MuJoCo motion has been manually verified: sideways, height,
depth, reset, unreachable-target rejection, and recovery. The demonstration
video has been recorded. Python's four automated test groups pass, including
reset recovery after reaching the workspace boundary and loopback UDP.

The robot model is displayed in MuJoCo; Unity displays the target and axes.
Quest support, Unity robot preview, simulated grasping, and hardware transport
are future phases.

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
.\.venv\Scripts\python.exe python/test_phase1.py
```

Tests cover model loading, three IK targets, actuator tracking, unreachable
targets, malformed messages, actual loopback UDP feedback, and duplicates.
See [engineering notes](docs/phase1.md) for protocol, findings, and limitations.

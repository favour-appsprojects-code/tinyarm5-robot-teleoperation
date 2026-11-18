# TinyARM-5 Mixed Reality Robot Teleoperation

Quest 3 hands -> Unity (passthrough MR) -> JSON/UDP 5006 -> Python IK -> MuJoCo,
with frozen previews, deliberate confirmation, permanent command recording, and
a gated binary sender for the TA receiver (192.168.1.244:5005, **locked** until
calibration is verified).

| Component | State (2026-11-18) |
|---|---|
| Desktop Unity -> Python -> MuJoCo (Phase 1) | Working, manually verified Nov 12 |
| Python IK, preview gate, recording, export, replay, receiver monitor | 34 automated tests pass |
| Simulated cube/cup/gripper and 20-s task timer (MuJoCo) | Implemented and tested |
| Quest hand tracking, HUD, passthrough, LAN discovery, build tooling | Code compiles against Unity 6.4 assemblies; **not yet run on the headset** |
| Physical robot output | Locked: no receiver calibration available |

Details: [integration test report](docs/integration-test-report.md) ·
[Quest build and use](docs/quest3.md) · [recording and replay](docs/recording.md) ·
[hardware and calibration](docs/hardware.md) · [new laptop](docs/laptop-setup.md) ·
[Phase 1 notes](docs/phase1.md) · [orientation](docs/orientation.md)

## Quick start: desktop (no headset)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python/requirements.txt
.\.venv\Scripts\python.exe python/server.py
```

Expect `Ready UDP 127.0.0.1 5006`, the session log path, and a MuJoCo viewer
with the arm, a red cube and a blue cup. Open `unity/` in Unity **6000.4.8f1**,
open `Assets/Scenes/DesktopDemo.unity`, press Play and click the Game view.

| Key | Action |
|---|---|
| W/S, A/D, Q/E | move target forward/back, left/right, down/up |
| I/K, J/L, U/O | rotate tool X/Y/Z; **T** toggles orientation tracking |
| R / H | reset pose / orientation demo pose |
| P / Enter / C | preview / confirm / cancel preview |
| G | toggle gripper open/closed (logical) |
| N | reset cube and task timer |
| Esc | disable output for the rest of the session |

Green target = IK converged, red = unreachable (last valid goal kept), yellow =
no Python feedback. Amber skeleton = IK goal / frozen preview.

## Quick start: Quest 3

```powershell
powershell -ExecutionPolicy Bypass -File scripts\quest_build.ps1        # builds unity\Builds\TinyARM5-Quest.apk
powershell -ExecutionPolicy Bypass -File scripts\start_python_lan.ps1 -AddFirewallRule   # once, as admin
powershell -ExecutionPolicy Bypass -File scripts\quest_deploy.ps1       # install + launch over USB
```

Pinch to move the target (relative clutch), pinch with the other hand for
precision, use the HUD buttons for gripper, preview and **hold-to-confirm**.
Full procedure and checklist: [docs/quest3.md](docs/quest3.md).

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s python -p "test*.py" -v
```

Unity batch checks (Unity closed):
`Unity.exe -batchmode -quit -projectPath unity -executeMethod VerifyQuestTeleop.Run -logFile verify.log`

## Safety summary

Target motion never sends a robot command. Execution requires a fresh,
unchanged, 5-second, single-use preview plus a held confirmation. Approvals are
written to disk before any transmission. Tracking loss, a changed target or a
0.5 s stream gap cancel previews; reconnecting never replays old commands.
Physical output cannot be enabled by any UI, network message or CLI flag in this
version; see [docs/hardware.md](docs/hardware.md) for the calibration sheet and
bring-up procedure.

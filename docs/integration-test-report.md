# Integration test report: 2026-11-18

Scope: takeover audit of commit `f834caf` (branch `main`, in sync with
`origin/main`; one pre-existing uncommitted Unity change to
`ProjectSettings.asset`), followed by this session's changes. Nothing has been
committed; all changes are in the working tree for review.

Legend: **VERIFIED** = executed and observed in this session. **COMPILED** =
compiled against the real Unity 6000.4.8f1 / package assemblies, not run in
Unity. **UNVERIFIED** = requires the headset, the Windows Unity install, or the
physical robot.

## Audit findings

| Finding | Action |
|---|---|
| Previous agent's 20 Python tests | VERIFIED: re-ran independently, 20/20 pass |
| `server.py` defaulted to UDP **5005** (docs said 5006; 5005 is the robot receiver's port) | Default now 5006; DesktopDemo scene updated to match |
| **Meta XR Core never compiled**: manifest lacked Animation/AssetBundle/Terrain modules (CS1069 in `Oculus.VR`, `Oculus.Interaction`, `Meta.XR.Audio`, `Meta.WitAi.TTS`) | Manifest fixed; all-in-one bundle replaced by `com.meta.xr.sdk.core` |
| No XR Plug-in Management configuration (no `Assets/XR`), no passthrough, no hand tracking, no headset HUD | Implemented (see below) |
| Preview/confirm only worked with an output profile; nothing was recorded | Simulation-mode gate + permanent recording |
| No receiver source/calibration anywhere in the repository | Hardware lock retained; calibration sheet added to hardware.md |

## Python (VERIFIED)

Environment used here: Linux, Python 3.10, MuJoCo 3.17, NumPy 2.2. The project
pins Python 3.13 / MuJoCo 4.0.1; **re-run on the Windows `.venv`** (one command in the README).

`python -m unittest discover -s python -p "test*.py"`: **34 tests, all pass**
(20 original + 14 new in `test_recording.py`).

| Area | Evidence |
|---|---|
| IK accuracy | targets [0,-0.12,0.15], [0.04,-0.16,0.16], [-0.04,-0.18,0.12]: IK residual 0.93 / 0.42 / 0.80 mm; simulated actuator tip 2.0 / 2.3 / 3.0 mm |
| Orientation (secondary) | feasible 17.2 deg request -> 0.007 deg at 0.31 mm; incompatible request keeps position (0.41 mm) with 126.6 deg residual, reported as best effort |
| IK speed | `solve_pose` average 0.6 ms (interactive rate is 20 Hz): no reason to replace the solver |
| Pick/place reachability | cube (0.08,-0.17,0.0125): 0.11 mm; 3 cm above: 0.18 mm; above cup (-0.09,-0.17,0.09): 0.79 mm |
| UDP packet format | 20/24 bytes, little-endian float32, ordering/sign/offset, NaN/inf/overflow rejection, loopback mock byte-exact (original tests) |
| Simulation fallback | server with no profile: preview -> confirm records `approved` with joints equal to the frozen preview, `transmission_attempted=false`, `not_attempted_simulation_only`, destination preserved |
| No silent loss | recording write failure is reported; an approval that cannot be recorded is never transmitted (socket not touched) |
| Receiver unavailable | server keeps running with an unreachable receiver (TEST-NET 192.0.2.1) |
| Attempted vs delivered | mock send logged `sent_to_loopback_mock_unacknowledged`, `delivery_confirmed=false` |
| No replay after reconnect | confirmed packet, 1 s stream gap (`stream_timeout` logged), stream resumes: no further packet at the mock, still exactly one `approved` |
| Receiver monitor | states never claim delivery; Windows router "unreachable" reply not counted; never creates a UDP socket |
| Discovery, cancel, unreachable flag | discovery reply, cancel invalidates preview, `IK Target Unreachable` flag |
| Grasp simulation | close far / sweep closed: no grasp; close near: grasp; carry; release above cup: lands in cup, timer stops |
| CLI end-to-end | real server session -> `export_commands.py` (1 approved row, exact radians) -> `replay_commands.py --headless` (joint error 0.009 rad, tip 3.0 mm) |

## Unity (COMPILED, not run)

`Assembly-CSharp` (10 scripts) and `Assembly-CSharp-Editor` (7 scripts) compiled
with zero errors using Mono `mcs` against Unity 6000.4.8f1 engine/editor modules
and this project's compiled XR Hands 1.7.3, OpenXR 1.19, XR Management 4.5.2 and
SpatialTracking assemblies. Meta XR Core had no compiled DLL (it never compiled),
so `OVRManager`, `OVRPassthroughLayer` and `OVRProjectConfig` were compiled
against stubs whose members were copied from the 209.0.0 package source. Unity's
own compiler, package resolution after the manifest change, and the scene/settings
editor scripts have **not** been executed.

One Euro filter (the hand smoothing), run under Mono with the compiled scripts:
±2 mm uniform per-axis noise at 72 Hz -> 0.87 mm peak; lag 9.6 mm at 0.3 m/s
(about 30 ms). `VerifyQuestTeleop.Run` encodes these limits as a batch check.

## UNVERIFIED (exact steps in quest3.md / hardware.md)

| Item | How to verify |
|---|---|
| Unity opens without compile errors after the manifest change | open project; Console clear; or `scripts\quest_build.ps1 -SetupOnly` |
| Desktop demo unchanged in Play mode | DesktopDemo, keys in README, Python on 5006 |
| APK build | `scripts\quest_build.ps1` |
| Standalone launch, passthrough, hand tracking, pinch/precision, HUD readability, tracking-loss behaviour, Wi-Fi discovery | quest3.md checklist rows 1-11 |
| Hand-to-target accuracy and latency on the headset | measure as described in quest3.md |
| Any physical robot behaviour (IDs, signs, offsets, gripper, motion, stop) | hardware.md calibration sheet and supervised procedure; transport still locked |
| Cube-to-cup in 20 s on the real robot | after the above |

No physical robot command was sent in this session. Nothing was sent to 192.168.1.244.

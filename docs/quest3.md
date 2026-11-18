# Meta Quest 3: standalone mixed-reality hand teleoperation

Status (2026-11-18): code and project configuration are complete and compile
against Unity 6000.4.8f1 reference assemblies. **The APK has not yet been built
or run on the headset**: the hardware steps below still need to be carried
out on the Windows laptop and headset. See
[integration-test-report.md](integration-test-report.md).

## Architecture

```text
Quest 3 (standalone Unity app, passthrough)          Windows laptop (Python)
  hands (XR Hands) -> pinch-clutched target   JSON/UDP 5006   python/server.py --lan
  HUD buttons: preview / hold-confirm / grip  ----------->   IK -> MuJoCo -> preview gate
  amber goal + cyan simulated arm, cube, cup  <-----------   state, status flags, scene
                                                              logs/robot_commands/*.jsonl
                                                              (robot receiver 192.168.1.244:5005
                                                               stays LOCKED; see hardware.md)
```

XR stack: Unity OpenXR 1.19 + Meta Quest feature, Meta XR Core 209
(passthrough only), XR Hands 1.7.3 (hand joints). No second XR rig/SDK is
used. Settings are Android-only; the desktop Editor demo stays non-XR.

### Project fix applied on 2026-11-18

`Packages/manifest.json` had removed Unity built-in modules that Meta XR Core
needs (Animation, AssetBundle, Terrain), so `Oculus.VR`, `Oculus.Interaction`,
`Meta.XR.Audio` and `Meta.WitAi.TTS` **failed to compile** (see
`Library/Bee/tundra.log.json`, CS1069). The manifest now lists those modules and
uses `com.meta.xr.sdk.core` instead of the all-in-one bundle (Voice, Interaction,
MRUK, Audio, Haptics and Platform SDKs are unused and were among the failing
assemblies). XR Hands and Legacy Input Helpers are listed explicitly because
the new scripts use them directly.

## One-time laptop prerequisites

1. Unity Hub -> Installs -> **6000.4.8f1** -> Add modules: **Android Build
   Support** with **Android SDK & NDK Tools** and **OpenJDK**.
2. Quest 3: enable Developer Mode (Meta Horizon phone app -> Devices ->
   Developer Mode). Connect USB-C, put the headset on and **Allow USB debugging**
   (tick "Always allow").
3. Python environment as in the README (`.venv`).

## Build (choose one)

**A. Batch script (no Unity window, Unity must be closed):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\quest_build.ps1
```

This runs `QuestMRSetup.BatchBuild`: configure project -> create
`Assets/Scenes/QuestMR.unity` -> build `unity/Builds/TinyARM5-Quest.apk`.
Output summary is printed; the full log is `quest-build.log`.

**B. In the Editor:** open the `unity` folder, wait for package import and make
sure the Console has no red errors, then run in order:

1. **TinyARM -> Quest MR -> 1. Configure Project For Quest 3**
2. **TinyARM -> Quest MR -> 2. Create Or Update QuestMR Scene**
3. Project Settings -> XR Plug-in Management -> **Project Validation** (Android
   tab): apply any remaining fixes it lists. Then
   **TinyARM -> Quest MR -> 3. Build Quest APK**.

What step 1 sets (Android only): IL2CPP, ARM64, min API 32, Vulkan, Linear,
INTERNET permission, package `edu.louisville.tinyarm5.teleop`; OpenXR loader;
OpenXR features Meta Quest Support, Meta XR, Hand Tracking Subsystem, Meta Hand
Tracking Aim, Oculus Touch + Touch Plus profiles; render mode Multi-pass (the
HUD uses legacy TextMesh, which is safe in every stereo mode this way);
`OVRProjectConfig` hand tracking = Controllers and Hands, passthrough = Required.
`QuestManifestCheck` verifies the hand-tracking and passthrough manifest entries
after Gradle generation.

What step 2 builds: a copy of DesktopDemo with an XR origin, a head camera driven
by `TrackedPoseDriver`, a virtual robot base at table height (the target is its
child), `HandTeleopController`, `QuestControllerTarget` (fallback),
`MixedRealitySetup`, the world-space `XrHud`, `SceneMirror`, and an `OVRManager`
+ `OVRPassthroughLayer` with a transparent camera background. `DesktopDemo.unity`
is not modified.

## Network and deploy

1. Laptop and Quest on the **same Wi-Fi**. Campus/guest Wi-Fi often blocks
   device-to-device traffic (client isolation); use a phone hotspot or a
   private router if discovery never succeeds.
2. On the laptop, once as Administrator, allow inbound UDP 5006 and start Python:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\start_python_lan.ps1 -AddFirewallRule
   ```

   (afterwards just `.\.venv\Scripts\python.exe python\server.py --lan`). It
   prints the laptop's LAN addresses and the session log path.
3. Install and launch:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\quest_deploy.ps1
   ```

   The app finds the server by UDP broadcast (`serverAddress: "auto"`) and
   remembers the last server. If broadcasts are blocked, pass the laptop IP:
   `scripts\quest_deploy.ps1 -ServerAddress 192.168.x.y`, which writes
   `/sdcard/Android/data/edu.louisville.tinyarm5.teleop/files/teleop_config.json`.
   All fields are in `config/teleop_config.example.json`; nothing is hard-coded
   in scripts and no rebuild is needed for a new network.
4. Unplug USB. The app runs standalone; Python and MuJoCo keep running on the laptop.

## Using it

On first launch the virtual robot base floats 0.45 m ahead at table height.

1. **Align the base.** Tap **PLACE BASE**, pinch and drag/rotate the white disc
   (green bar = robot reach direction, robot -Y) onto the real robot base, release,
   tap **PLACE BASE** again. The pose is saved on the headset. The target is fixed
   in the base frame, so moving your head or the base never changes robot coordinates.
2. **Move the target.** Pinch (thumb + index) with the dominant hand *anywhere*
   and move: the target follows relative to your hand (clutch), so there is no jump
   on grab. Release to leave it there (the last ~0.1 s before release is rewound to
   remove finger-opening jitter). Re-pinch to continue.
3. **Precision.** While moving, **pinch with the other hand** for x0.25 motion,
   or tap **FINE** to make it sticky.
4. **Orientation.** Off by default (position-priority 5-DOF arm). Tap **ROTATE**
   to let the palm rotation adjust the tool orientation; the HUD shows "matched" or
   "best effort" with the residual angle. Unreachable rotations keep position.
5. **Feedback.** Target colour: green = IK converged, red = unreachable (last valid
   goal kept), yellow = no Python feedback. Amber skeleton = IK goal / frozen preview;
   cyan = MuJoCo arm; red cube and blue cup = simulation props; tip dot = gripper.
6. **Gripper.** **GRIP OPEN** / **GRIP CLOSE** buttons (never a gesture, so moving
   the target cannot close the gripper). In MuJoCo, closing within 2.5 cm of the cube
   grasps it; opening above the cup drops it in and stops the task timer.
7. **Preview and execute.** **PREVIEW** freezes the joint solution (amber).
   **HOLD CONFIRM** for 0.6 s within 5 s approves it once; moving the target, changing
   the gripper, tracking loss or **CANCEL** invalidates it. Today confirmation
   records the approved command and remains simulation-only (physical output is locked).
8. **DISABLE OUTPUT** stops any further output until Python restarts.
   **HOME POSE** / **DEMO POSE** move the target to tested poses; **RESET CUBE**
   resets the props and timer.

Safety behaviour: buttons are inert while a pinch-grab is active; losing hand
tracking releases the target, cancels a pending preview and requires an open
hand before the next grab; if Python stops receiving for 0.5 s it freezes the
command and drops any preview; after reconnecting nothing is replayed.

Controllers (fallback, inactive while hands are tracked): right grip = clutch
move, A = preview, B = confirm, trigger = close/open gripper, left X/menu =
disable output.

## Headset verification checklist (not yet performed)

| # | Check | Pass criterion |
|---|-------|----------------|
| 1 | APK installs and launches from the Quest library without Link | App opens, no crash in `scripts\quest_deploy.ps1 -Logcat` |
| 2 | Passthrough | Real room visible behind HUD/robot |
| 3 | Hand tracking | HUD "Hand:" line changes from "Waiting" to "Pinch to grab" |
| 4 | Network | HUD shows `Python <ip>:5006: connected`, flags appear |
| 5 | Pinch move | Target follows without jump on grab or release |
| 6 | Precision | Other-hand pinch visibly slows motion; 1 cm moves are easy |
| 7 | Tracking loss | Hide hand mid-grab: target stops, preview cancelled |
| 8 | Robot response | MuJoCo window and cyan arm follow the target |
| 9 | Preview/confirm | Amber freezes; hold confirm -> `approved` line in the session log |
| 10 | Gripper and task | Grasp cube, drop in cup, HUD shows task time |
| 11 | Disconnect | Stop Python: HUD shows NO FEEDBACK, target turns yellow |

Measure and record: the IK residual (HUD) and the target-vs-cyan-tip offset at
a few points; MuJoCo actuator tracking adds about 2-3 mm (see test output).

## Troubleshooting

- **Console shows CS1069 errors in Oculus.VR**: the manifest fix above was
  reverted, or Unity has not re-resolved packages yet; reopen the project.
- **Black background instead of passthrough**: check `OVRProjectConfig`
  passthrough = Required, the *Meta XR* OpenXR feature is enabled for Android,
  and the scene camera background alpha is 0 (step 2 sets all three).
- **No hands**: Quest Settings -> Movement tracking -> Hand tracking on; confirm the
  Hand Tracking Subsystem feature is enabled (step 1).
- **"searching LAN"** forever: firewall rule missing, Wi-Fi set to Public, client
  isolation, or Python not started with `--lan`; use `-ServerAddress`.
- **App runs but nothing moves**: Python must show the session log path and no
  errors; check `adb logcat -s Unity` for `[TinyARM]` lines.

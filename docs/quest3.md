# Quest 3 status and shortest remaining path to November 19

## Audited status

The existing Unity 6000.4.8f1 project is preserved. Android Build Support,
SDK/NDK and OpenJDK were subsequently installed by the user on the original
computer; install them separately on any new laptop. The manifest now contains
OpenXR 1.19.0 and Meta XR All-in-One 209.0.0, and a Meta Quest build profile is
included under Assets/Settings/Build Profiles. Package installation does not
by itself prove the provider, controller profile or passthrough scene is enabled.
There is still **no tested headset build or verified passthrough configuration**.

Prepared and compiled code:

- `QuestControllerTarget`: right-controller grip-clutched relative target motion,
  rotation, tracking-loss handling and input edges using Unity's XR device API.
- Right A: request preview after releasing grip. Right B: confirm a fresh
  snapshot after releasing grip. Right trigger: logical closed/open (>0.7).
  Left X or exposed menu button: disable output. Physical output stays locked.
- Release/re-press grip after tracking loss; pose updates require a valid device
  and initialized target orientation. Head pose updates the rig camera.
- `RobotPreview`: amber FK goal skeleton already driven by Python feedback.
- `DesktopTarget.robotBase`: workspace frame for both target coordinates and
  preview. It is a placement interface, not a physically calibrated transform.
- Menu **TinyARM -> Prepare Controller Rig In Current Scene** adds a rig to the
  existing open scene. It does not install or configure an XR provider. Save a
  scene variant before invoking it if retaining the desktop camera layout matters.

These checks establish compilation only. Controller tracking, headset usability,
passthrough, Wi-Fi latency and standalone execution are not headset-tested.
The desktop OnGUI panel is not a headset world-space HUD; a readable XR status
panel and clear preview/confirmation cues are still needed before live use.
XR Interaction Toolkit is optional for this low-level device adapter, but can
be added later for polished XR UI; do not add hand tracking before controllers work.

## Priorities

1. **Install build prerequisites on the new laptop.** In Unity Hub -> Installs -> 6000.4.8f1 ->
   Add modules, install Android Build Support, Android SDK & NDK Tools and
   OpenJDK. This modifies the Unity installation outside the repository and
   requires a local installation step. Do not create another project.
2. **Enable standalone XR.** In this project create a Meta Quest/Android build
   profile, install the compatible OpenXR plug-in and XR Plug-in Management,
   enable the Android OpenXR provider and Meta Quest support, add the appropriate
   Touch controller interaction profile, and resolve project validation. Use
   ARM64/IL2CPP and the Android/API/graphics settings required by the selected
   supported package versions. Keep the desktop scene working.
3. **Scene and networking.** Use the controller-rig menu in a saved scene variant.
   Set Simulation UDP's serverAddress to the Python PC's LAN IP (not loopback).
   Start Python with `--bind <PC-LAN-IP>` and the mock profile in dry-run mode.
   Both devices need the same reachable LAN; Python feedback returns to the
   headset's originating socket. Grant only the required network access locally.
   Build/install on Quest in developer mode, then disconnect the USB cable and
   prove head/controller tracking and Wi-Fi simulation work untethered.
4. **Preview interaction.** Add world-space status and deliberate confirmation
   cues. Grip-clutch at half scale, release to hold a target, A preview, B confirm
   dry run. Check tracking loss, timeout, expiry, target changes and gripper
   changes cannot result in a stale confirmation. Confirm that the initial
   neutral gripper state is acceptable before physical mapping is enabled.
5. **Passthrough and registration.** Choose one supported integration (Unity Meta
   OpenXR with its AR Foundation scene setup, or Meta XR Core's documented
   passthrough workflow), configure it, and verify on Quest. The current built-in
   desktop renderer and camera background do not provide passthrough. Calibrate
   virtual robot base, axes, table scale and tool frame against the real robot.
   Do not apply both SDK camera rigs blindly to the same camera.
6. **Hardware review and supervised test.** Complete docs/hardware.md's mapping
   and receiver questions, establish safe startup and robot stop behavior, and
   obtain explicit user authorization before adding/enabling live transport.
7. **Pick-and-place rehearsal.** Model/validate gripper contact, cube/cup and table
   constraints; contact is currently disabled in MuJoCo. Add grasp/release cues,
   timer and repeatable start pose, then rehearse untethered operation and the
   20-second task. A skeleton preview alone does not validate collision safety.

Physical calibration collection and installing Android tooling can proceed
while the desktop mock path is tested. Neither should require replacing IK or
the existing Unity-to-Python protocol.

## Official setup references consulted

- Unity Meta Quest build profile and Android module requirements:
  https://docs.unity.com/en-us/engine/6000.3/manual/xr/configuring-project-for/meta-quest-develop/build-profile
- Meta OpenXR provider setup:
  https://developers.meta.com/vr/documentation/unity/unity-xr-plugin/
- Meta passthrough setup:
  https://developers.meta.com/vr/documentation/unity/unity-passthrough-tutorial/

Package versions and API/graphics requirements must be chosen from compatible
installed packages and project validation, rather than guessed from this plan.

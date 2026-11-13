# Physical interface audit and disabled integration

## What is verified

`send_joint_angles.py` supplied the packet format, not a hardware calibration.
The example's receiver is 192.168.1.244:5005. It packs five arm radians followed
optionally by one raw gripper encoder position as **little-endian float32**,
without a header, sequence, timestamp or acknowledgement: 20 or 24 bytes.
Its comments give an example `--ids 1 2 3 4 5 8`, open=3000, closed=2500.
These ID/range examples are not hardware-verified settings. The receiver source
is absent, so its actual clamping, interpolation, watchdog and motor ordering
cannot be independently verified.

The reference script previously transmitted immediately, even on import. Its
constants, packing and comments are retained, but it now has a main guard and
prints a dry-run packet only. It contains no socket or live transmission path.
Do not treat its sample pose as a safe physical starting pose.

The existing IK computes position-priority numerical solutions with optional
secondary orientation, joint clipping, warm starts and a neutral-seed fallback.
MuJoCo has nq=nv=nu=5. The server now asserts this exact joint ordering at startup:

| IK/qpos/actuator index | Model joint | Chain | Model limit radians | Physical ID/order/sign/offset/limit |
|---|---|---|---|---|
| 0 | j0 | base_link -> rotor_0 | [-pi/2,+pi/2] | Unknown |
| 1 | j1 | rotor_0 -> rotor_1 | [-pi/2,+pi/2] | Unknown |
| 2 | j2 | rotor_1 -> rotor_2 | [-pi/2,+pi/2] | Unknown |
| 3 | j3 | rotor_2 -> rotor_3 | [-pi/2,+pi/2] | Unknown |
| 4 | j4 | rotor_3 -> rotor_4 | [-pi/2,+pi/2] | Unknown |
| none | gripper | no moving finger joint in URDF | none | Example ID 8 only; unverified |

All model revolute axes are local Z with different joint origin transforms.
Actuators remain the supplied PD scheme: kp=20, kv=0.5, torque +/-0.52 Nm.
The model declares 11.73394 rad/s joint velocity; the application ramps its
simulated target at 0.8 rad/s. Neither is a verified physical speed setting.
Contact remains disabled. The approximate tip site is rotor_4+[0,-0.01,0.09].

## Modules and calibration

- `python/hardware.py`: codec, model-limit validation, calibrated mapping,
  explicitly disabled sender and one-use preview/confirmation gate.
- `python/config/hardware.unverified.json`: actual endpoint example with all
  unknown mapping fields left null. Preview preparation rejects this profile.
- `python/config/mock.json`: **synthetic test fixture only**. Its illustrative
  IDs, identity transforms, generous numeric limits and gripper presets do not
  establish any physical settings. Model input limits are still enforced.
- `python/mock_receiver.py`: numeric loopback only, non-5005 port.
- `python/hardware_demo.py`: IK-to-packet dry run, optional loopback send.

Each element in `arm` is one slot in receiver packet order. It names a model
joint, confirmed motor ID, sign (+1/-1), offset radians and limits in receiver
coordinates. Conversion is `q_receiver = sign*q_model + offset_rad`. Reordering
is explicit; the five joint names must each appear once. Units remain radians.
Both input model limits and transformed physical limits are checked, including
float32 round-trip limits. Invalid/NaN/infinite/bool/overflow values are rejected.
Optional gripper values may be logical open/closed or raw numeric values; both
require a separately verified gripper profile and limits.

`verified:true` plus a reference identifies a human-reviewed configuration; it
cannot infer real calibration. Even a fully populated physical profile cannot
enable transmission in this milestone: `set_enabled(True)` rejects physical
profiles. There is no Unity/network/CLI command that unlocks physical output.
A later, explicitly authorized change must add that transport after review.

## Existing pipeline integration

The existing Unity JSON target stream and MuJoCo control loop remain in place.
The output module reuses the already-computed `goal`; it does not solve IK a
second time. Normal target updates never invoke the sender. Optional target
fields are `action` (empty/preview/confirm/disable), `preview_id`, and logical
`gripper` (empty/open/closed). Raw motor gripper values stay out of Unity.

With an output profile selected, P requests a packet preview. The gate stores
the exact joint snapshot, packet, source endpoint, target signature, gripper,
random token and a five-second monotonic expiry. While pending, MuJoCo previews
that frozen configuration and Unity displays an amber FK skeleton of it.
Unity/PC feedback describes the intended destination, calibrated values, hex
packet and byte count. Enter confirms that exact snapshot once. A changed
target, orientation, gripper, source, unreachable request, five-second expiry,
0.5-second receive timeout, or disable command invalidates the pending preview.
Same-target heartbeat packets keep feedback alive but do not extend expiry.

Defaults are simulation-only. With a profile, confirmation is **dry run** and
does not send. Only the explicit `--mock-output` option enables socket output,
and it accepts numeric loopback profiles on a non-5005 port only. Physical output
is always reported false. Escape/Disable prevents future output and clears
pending confirmation; it is not a physical emergency stop. No re-enable button
exists; restart with an explicit mock flag for another mock-output session.

The amber Unity skeleton is an intended goal representation based on MuJoCo
link origins, not a mesh-accurate digital twin or measured physical robot state.
It updates when feedback arrives. In a headset it uses the calibrated virtual
robot-base transform. Hardware communication has no returned encoder telemetry.
This UDP interface has no authentication, acknowledgements or remote timestamps.
Those limitations and the instructor receiver's safety behavior must be reviewed
before live transport is implemented. A single distant endpoint command must
not bypass a confirmed receiver-side motion profile or jump limit.

## Safe commands

From the project root, packet preview only (no socket output):

```powershell
.\.venv\Scripts\python.exe python/hardware_demo.py --gripper open
```

Expect 24 bytes, ordered values, hex bytes, and `confirmed_dry_run_no_transmission`.
Without `--gripper`, expect 20 bytes.

Interactive Unity preview/confirmation with **no command transmission**:

```powershell
.\.venv\Scripts\python.exe python/server.py --output-profile python/config/mock.json
```

Move the target, press P, inspect the amber configuration, and press Enter within
five seconds. G changes the logical gripper state and invalidates an old preview.
The default `python/server.py` still works without any output profile.

To validate actual bytes at a local mock, open two terminals:

```powershell
# Terminal 1
.\.venv\Scripts\python.exe python/mock_receiver.py --port 15005 --count 1
# Terminal 2
.\.venv\Scripts\python.exe python/hardware_demo.py --gripper closed --mock-output
```

For Unity-confirmed loopback packets, replace hardware_demo with:

```powershell
.\.venv\Scripts\python.exe python/server.py --output-profile python/config/mock.json --mock-output
```

P does not send; Enter sends one packet to the mock. Starting the normal server
and mock on different ports prevents confusing Unity JSON with binary commands.
No command in this guide sends to 192.168.1.244.

## Verification and prerequisites before physical testing

Automated tests cover five/six-value packet size, exact endianness, finite values,
receiver reordering, signs/offsets, model and calibrated limits, gripper presets,
missing mappings, disabled/unconfirmed/unverified rejection, remote mock rejection,
single-use expiry/source/target binding, local send errors, and end-to-end
target -> IK -> frozen preview -> confirmation -> exact loopback binary packet.
Original position/orientation/actuator/reset/network regressions also pass.
Unity batch checks compile the controller adapter and verify JSON controls,
quaternion conversion and the six-link preview coordinate mapping.

Before requesting physical authorization, obtain:

1. Actual receiver source/version and its startup `--ids` order.
2. Per-motor model joint association, zero convention, sign, offset and safe
   receiver-coordinate range, verified against a known measured robot pose.
3. Gripper ID, open/closed values, raw safe range and whether 5-value packets
   are accepted when a sixth motor is configured.
4. Receiver startup/hold behavior, watchdog, interpolation, velocity/acceleration
   limits, stop procedure and whether repeated commands are required.
5. Physical tool-centre/base calibration, initial measured joint states and a
   supervised low-speed procedure for validating one joint at a time.

Do not substitute example IDs or simulation coordinates for those answers.

# Inspection and architecture

## Verified starter inventory

The complete supplied tree contains `bare_viewer.py`, `tiny_arm_5.urdf`, and
13 binary STL files in `meshes/`. No pub.py, sub.py, IK package, UDP code,
Unity project, requirements file, gripper control, or hardware protocol exists.
All 13 distinct mesh references resolve locally. Visual meshes use 0.001
scaling; joint transforms and runtime positions are metres.

The links are base_link and rotor_0 through rotor_4, followed by tool_frame.
Revolute joints j0 through j4 form that serial chain; each has limits
[-pi/2, pi/2] radians, effort 0.52 Nm, and declared velocity
11.733939817377575 rad/s. Each joint's axis is its local Z; joint origin
rotations mean their world axes differ. tool_fixed is a fixed rotation of
pi/2 about Z, at rotor_4's origin. There are no URDF transmissions or
actuators, and no articulated finger joints. Five serial arm joints must not
be treated as five positioning axes plus an extra gripper.

The starter viewer uses MjSpec, adds one PD position actuator per joint
(kp=20, kv=0.5, force +/-0.52), adds a `tip` site on rotor_4 at
[0,-0.01,0.09], and steps with implicitfast at 0.0005 s. It disables all
contact due to overlapping approximate collision boxes. The new loader
retains these choices. This is suitable for a motion demo, not grasping or
collision-safe execution. The site is a supplied approximation, not a
confirmed physical tool centre point. URDF tool_frame itself has no offset.

## Implementation

- `python/robot.py`: separate loader and position-only damped least-squares IK.
  Uses MuJoCo's site Jacobian, bounded joint steps, joint-limit clipping and
  backtracking, seeded from the previous accepted solution. No orientation
  constraint. A failed local solve means the target was not solved from this
  seed, not a proof that no configuration exists. If the continuity search
  fails, the solver retries from zero joints to recover from local minima.
  This fixes reset rejection after slowly raising the target to the workspace
  boundary; accepted goals still pass through the server's 0.8 rad/s ramp.
- `python/protocol.py`: finite-value/schema validation.
- `python/server.py`: nonblocking UDP, newest valid target per tick, feedback,
  stale sequence rejection, 0.8 rad/s command slew, and 0.5 s receive timeout.
- `unity/Assets/Scripts/DesktopTarget.cs`: keyboard sphere movement, 20 Hz
  sender, 0.5 s feedback timeout, green/red/yellow status.
- `unity/Assets/Editor/CreateDemo.cs`: reproducible scene generator with
  floor reference, colour axes, target, lighting, camera and build scene.

The floor is a scale reference, not a computed workspace boundary. The
default target is robot [0,-0.12,0.15] metres; zero-joint tip is approximately
[-0.00000125,-0.27943195,0.15568]. Keep steps small to retain branch continuity.

## Coordinates and UDP

Robot base is fixed to MuJoCo world, Z up. Unity uses Y up. Both use metres.
Unity position [x,y,z] maps to robot [x,-z,y]; inverse is [x,z,-y]. Thus
Unity +X is robot +X, Unity +Y is robot +Z, Unity +Z is robot -Y.
The target scene origin is the robot base world origin. This is an explicit
desktop mapping; a future headset needs a calibrated robot-base transform.

Python binds 127.0.0.1:5005 by default. Unity sends from an ephemeral UDP
port and receives replies on that same socket. UTF-8 JSON, one object per
datagram, at 20 Hz:

```json
{"v":1,"type":"target","seq":1,"position":[0,-0.12,0.15]}
```

Position is already in robot coordinates. Sequence is a nonnegative signed
32-bit integer. Coordinates must be three finite numbers within +/-1 m;
this validation bound is not the robot workspace. Messages over the read
buffer or malformed messages are discarded. Out-of-order/duplicate sequences
are discarded per source endpoint; after 2 s silence that endpoint can restart
its sequence. There is no synchronized wall clock dependency. UDP provides
no guarantee against a delayed first packet; this protocol is simulation-only.

```json
{"v":1,"type":"state","seq":1,"reachable":true,"ik_error_m":0.0009,"position":[0,-0.12,0.15],"joints":[0,0,0,0,0],"joint_targets":[0,0,0,0,0]}
```

The example is structural: actual joints are computed, in j0..j4 order,
radians. `position` is the current simulated tip; `joint_targets` is the last
accepted goal before ramping. Unreachable requests do not replace that goal.
After 0.5 s without valid packets the command freezes at the ramp position;
motors remain active, so this is not a physical emergency stop. No gripper
or execute fields are accepted. No hardware commands are transmitted.

## Validation and remaining milestones

Python 3.13 / MuJoCo 4.0.1 / NumPy 2.5.4 loaded the actual model with
nq=nv=nu=5. Three targets, tested sequentially:

| Target metres | IK error mm | Simulated settled error mm |
|---|---:|---:|
| [0,-0.12,0.15] | 0.925 | 2.001 |
| [0.04,-0.16,0.16] | 0.422 | 2.344 |
| [-0.04,-0.18,0.12] | 0.797 | 2.975 |

Actuator tracking errors include gravity and limited PD gains. Actual UDP
integration drove the simulated first target to 2.001 mm error. All three
Python test groups passed outside the restricted network sandbox. Invalid
targets held the previous goal; malformed and duplicate messages were rejected.

Next phases need controller/XR input, standalone Android configuration,
passthrough, robot mesh preview, confirmation controls, and cube/cup contact
simulation. None is required for the first desktop milestone. Hardware needs
instructor-confirmed protocol, joint order/sign/offset/unit calibration,
gripper interface, safety controls and physical tool calibration before any
physical command transport is added. No assumption is made about that protocol.

API reference consulted: https://mujoco.readthedocs.io/en/stable/APIreference/APIfunctions.html

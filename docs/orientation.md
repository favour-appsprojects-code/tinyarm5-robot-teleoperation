# Position-priority orientation tracking

## Run and test

1. Stop Unity Play mode and restart `python/server.py` in the project virtual
   environment. Reopen Unity if needed and wait for script compilation.
2. Open DesktopDemo, press Play, select Free Aspect, and click the Game view.
   No scene regeneration is required. Target axes are added at runtime.
3. Wait for green position feedback. The initial orientation is taken from
   the first accepted position IK goal, so it starts at a reachable pose.
4. Press H and wait for the arm to settle at robot [0,-0.22,0.16] metres.
   This pose has more joint headroom than the original reset, which puts a
   joint at +90 degrees. H aligns the target axes to the accepted tool
   orientation before resuming rotation tracking. R still restores the
   original reset pose. Tap/hold I or K to rotate about the red tool X axis. J/L rotate about
   green Y; U/O rotate about blue Z. Try one pair at a time, initially for
   0.5 seconds. Rotation speed is 35 degrees/s in the local tool frame.
5. Watch the sphere axes and MuJoCo tip axes. Position coordinates should
   remain unchanged during rotation-only input. Wait for motor settling.
6. Read the orientation status. `matched` means predicted goal error <=5
   degrees. `limited / best effort` means the arm cannot currently match the
   rotation while meeting its position tolerance. Green still means the
   requested position was solved. The displayed errors describe IK goals,
   not instantaneous physical/simulated tracking error.
7. Press R to restore the starting position and captured orientation. Press T
   to compare with position-only mode. WASD/QE translation controls still work.
8. Raise the sphere beyond reach and press R to check rejection and recovery.

Five joints cannot independently satisfy all six arbitrary pose coordinates.
All three rotation components are secondary soft objectives; some poses match,
others retain a residual. No orientation constraint can reject an otherwise
valid position. The tip is the same approximate rotor_4 site used previously,
not a calibrated physical gripper frame.

## Solver

`IK.solve_pose` first uses the existing bounded position solver and its neutral
seed fallback. If position fails, the server retains the last valid goal.
If an orientation is supplied, the secondary update uses the exact null-space
projector `N = I - pinv(J_position) J_position`, then a damped rotational
Jacobian solve in that space. Rotational errors are shortest world-frame
rotation vectors, consistent with MuJoCo's rotational site Jacobian.

Each candidate has bounded joint steps, respects +/-pi/2 joint limits, and is
corrected for nonlinear position drift. Joints at a bound that would move
outward are locked, and the null space is recomputed using the remaining
joints. Position correction uses 80% of the existing position tolerance,
rather than the previous fixed 0.5 mm correction threshold. It is accepted only if position error
is <=1.5 mm and orientation error decreases. Otherwise the last position-valid
solution is retained. There are at most 24 secondary iterations per solve;
later packets continue from the last accepted configuration. Goals still pass
through the existing 0.8 rad/s command ramp. Endpoint tolerance does not imply
a straight-line tip trajectory or collision avoidance during joint motion.

The MuJoCo loader adds massless, non-contact capsule visuals for positive tool
axes. Contact remains disabled as in the original desktop demonstration.
No physical robot transport was added.

## Pose protocol and basis conversion

Version 1 target messages accept these optional fields:

```json
{"v":1,"type":"target","seq":1,"position":[0,-0.12,0.15],"orientation_enabled":true,"orientation":[1,0,0,0]}
```

Quaternion order is **[w,x,y,z]**, in the robot world basis. Values must be
finite, four numeric components bounded by +/-2, and nonzero; the receiver
normalizes them. This example identity rotation is structural, not a promised
reachable rotation at that position. `orientation_enabled:false` ignores the
quaternion. A missing/null quaternion preserves legacy position-only behavior.
If the flag is omitted, a present quaternion enables orientation tracking.

The position basis matrix is `C(x,y,z) = (x,-z,y)`. Rotations use
`R_robot = C R_unity C^-1`; a Unity quaternion [x,y,z,w] therefore becomes
robot [w,x,-z,y]. The inverse is Unity [x,z,-y,w] from robot [w,x,y,z].
The Unity target triad draws robot local +X at Unity local +X (red), robot
local +Y at Unity local -Z (green), and robot local +Z at Unity local +Y
(blue). Thus its colours have the same meaning as the MuJoCo tip axes.

State feedback adds `orientation` (current simulated tip quaternion),
`goal_orientation` (accepted goal quaternion), `orientation_requested`,
`orientation_error_deg` (predicted residual; zero when disabled), and
`orientation_matched` (position accepted and rotation within 5 degrees).
Existing position, sequence, timeout and rejection behavior remains compatible.

## Verification

The ten Python tests cover the original position, actuator, reset and UDP
checks, plus world-frame rotational Jacobian finite differences, quaternion
sign equivalence, invalid inputs, legacy packets, pose UDP replies and holding
the accepted goal after an unreachable request.

For a known reachable pose generated from joints [0.2,0.4,-0.6,-0.4,0.3]
radians, predicted rotation error improved from 17.187 degrees to 0.007 degrees
while position error was 0.314 mm. An incompatible near-180-degree rotation
retained a 126.601-degree residual while keeping position error at 0.409 mm.
These are numerical endpoint checks, not manual visual confirmation.

The H pose starts with at least 0.8 radians of joint-limit margin when solved
from neutral. A +35-degree local X request achieved 0.401 degrees residual
and 0.721 mm position error. When reached from the original reset, the same
request achieved 0.004 degrees residual and 0.858 mm position error. At the
original reset, red/green rotations remain strongly constrained; blue-axis
rotation is more achievable. A better solver cannot create a missing degree
of freedom or remove the joint limits.

`VerifyOrientation.Run` compiles in Unity 6000.4.8f1 and checks rotation-basis
conversion against Unity's actual vector rotation, quaternion round trips,
message serialization and target-axis dimensions/idempotence.

MuJoCo API reference: https://mujoco.readthedocs.io/en/stable/APIreference/APIfunctions.html

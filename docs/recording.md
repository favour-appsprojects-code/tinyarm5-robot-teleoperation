# Command recording, simulation fallback, export and replay

Every Python session writes `logs/robot_commands/<session-id>.jsonl` (override with
`--log-dir` or `TINYARM_LOG_DIR`). Recording is always on, whether or not a
robot is reachable, so development at home produces the same records as a lab
session. The path is printed at startup and shown on the Quest HUD.

## What is recorded

One JSON object per line. Event types:

| event | when | durable (fsync) |
|---|---|---|
| `session_start` | server start: bind, profile, destination, physical_enabled | yes |
| `target_sample` | live stream, at most 5 Hz and only when target moved >= 2 mm, rotated >= 2 deg, or gripper/reachability changed | no (flushed) |
| `preview` | user requested a preview; frozen joints, packet (if a validated profile exists) | yes |
| `approved` | user confirmed; written **before** any transmission | yes |
| `execution_result` | outcome of that approval | yes |
| `rejected` | preview/confirm refused (reason) or send failure | yes |
| `preview_cancelled`, `output_disabled`, `scene_reset`, `stream_timeout`, `task_completed` | as named | yes |

Command fields: `timestamp` (UTC), `unix_time`, `session_id`, `sequence`,
`target_position_m` (robot base frame), `target_orientation_wxyz`, `joint_names`
(`j0..j4`), `joint_angles_rad` (unrounded, exact order), `gripper` (logical),
`gripper_raw` (only when a verified profile defines it), `ik_position_error_m`,
`ik_orientation_error_deg`, `validation`, `execution_status`
(`live_simulation_only` / `previewed_not_executed` / `approved_by_user`),
`preview_id`, `transmission_attempted`, `destination` (for example
`192.168.1.244:5005`), `transmission_outcome`, `delivery_confirmed`,
`receiver_values`, `packet_hex`.

`transmission_outcome` values: `not_attempted_simulation_only`,
`not_attempted_dry_run`, `not_attempted_preview_only`,
`sent_to_loopback_mock_unacknowledged`, `send_failed: ...`.
`delivery_confirmed` is always `false`: the TA receiver has no acknowledgement,
so a successful `sendto()` is never reported as delivery.

**No silent loss:** an approval is fsynced before anything is sent; if it cannot
be written, transmission is refused. Write failures are reported in the HUD
("RECORDING FAILED") and the server log.

## Simulation fallback and receiver status

With no output profile (the default) or the unverified hardware profile,
everything runs in **Simulation Mode**: IK, MuJoCo, preview, confirmation and
recording all work; nothing is transmitted. With
`--output-profile python/config/hardware.unverified.json` (or
`--receiver-host 192.168.1.244`) the server also monitors the receiver laptop:

| HUD flag | meaning |
|---|---|
| Physical Output Disabled | hardware lock active (always, currently) |
| Robot Connection Unverified | host answers ping/TCP; UDP delivery unknown |
| Robot Unavailable | host does not answer |
| Robot Connected | reserved for a receiver with an acknowledgement (none exists) |

The monitor **never sends UDP to port 5005**: any 20/24-byte datagram there is
a motion command. Windows "Destination host unreachable" replies from a router
are not counted as reachable. Reachability never enables output.

## Export approved commands to CSV

```powershell
.\.venv\Scripts\python.exe python\export_commands.py logs\robot_commands\<session>.jsonl
# all events:          ... --all
# previews + approved: ... --events preview approved
```

Writes `<session>.approved.csv` next to the log, with `j0_rad..j4_rad` at full precision.

## Replay in MuJoCo (simulation only)

```powershell
.\.venv\Scripts\python.exe python\replay_commands.py logs\robot_commands\<session>.jsonl
.\.venv\Scripts\python.exe python\replay_commands.py <log> --headless   # numbers only
```

Drives the simulated arm through each approved command at the live 0.8 rad/s
ramp and reports joint and tip error. The tool contains no network code and does
not import the hardware sender. **Old commands are never replayed to the
physical robot.** After a reconnect, the server needs a new preview and a new
confirmation.

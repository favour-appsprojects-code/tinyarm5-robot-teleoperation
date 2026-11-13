"""Unity -> UDP -> IK -> MuJoCo, with loopback binding by default."""
import argparse
from contextlib import nullcontext
import json
import logging
import socket
import time
import mujoco
import numpy as np
from robot import load_robot, IK
from protocol import decode_pose, decode_controls
from hardware import RobotSender, PreviewGate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=5005)
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('--output-profile', help='Optional dry-run calibration/mock JSON; never enables physical output')
    parser.add_argument('--mock-output', action='store_true', help='Permit confirmed packets to loopback MOCK ONLY')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    output = RobotSender.from_file(args.output_profile) if args.output_profile else None
    if args.mock_output:
        if output is None:
            parser.error('--mock-output requires a loopback mock profile')
        output.set_enabled(True)  # Physical profiles are rejected here, even if marked verified.
    gate = PreviewGate(output) if output else None
    output_status = 'mock_enabled_confirmation_required' if args.mock_output else 'dry_run_only' if output else 'output_disabled'
    model = load_robot()
    joint_order = tuple(mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(model.njnt))
    if joint_order != ('j0', 'j1', 'j2', 'j3', 'j4'):
        raise RuntimeError(f'Unexpected model/IK joint order: {joint_order}')
    preview_bodies = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n)
                      for n in ('base_link', 'rotor_0', 'rotor_1', 'rotor_2', 'rotor_3', 'rotor_4')]
    data = mujoco.MjData(model)
    ik = IK(model)
    command = data.qpos.copy()
    goal = command.copy()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind, args.port))
    sock.setblocking(False)
    print('Ready UDP', args.bind, args.port, 'initial tip metres', ik.position(command), flush=True)
    if not args.headless:
        from mujoco import viewer as mjviewer
        context = mjviewer.launch_passive(model, data)
    else:
        context = nullcontext(None)
    started = time.monotonic()
    last_receive = started
    sequences = {}
    try:
        with context as viewer:
            if viewer:
                viewer.opt.geomgroup[0] = 0
                viewer.cam.lookat[:] = [0, -0.12, 0.08]
                viewer.cam.distance = 0.6
                viewer.cam.elevation = -25
            while (not viewer or viewer.is_running()) and (not args.seconds or time.monotonic()-started < args.seconds):
                tick = time.monotonic()
                # Bounded drain: process only newest valid packet per frame.
                pending = None
                for _ in range(128):
                    try:
                        packet, address = sock.recvfrom(4096)
                    except BlockingIOError:
                        break
                    try:
                        seq, target, orientation = decode_pose(packet)
                        action, gripper, token = decode_controls(packet)
                        previous, received = sequences.get(address, (-1, 0))
                        if tick-received < 2 and seq <= previous:
                            continue
                        sequences[address] = (seq, tick)
                        pending = (seq, target, orientation, address, action, gripper, token)
                        # Process one-shot controls in order; leave later packets queued.
                        if action:
                            break
                    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
                        continue
                if pending:
                    seq, target, orientation, address, action, gripper, token = pending
                    solution, error, reachable, angle = ik.solve_pose(target, goal, orientation)
                    if reachable:
                        goal = solution
                    preview = {}
                    signature = json.dumps([target, orientation, gripper], separators=(',', ':'))
                    if gate:
                        gate.observe(signature, address, tick)
                        if gate.pending:
                            goal = np.array(gate.pending['model_joints'])
                        if not reachable:
                            gate.invalidate()
                        try:
                            if action == 'disable':
                                output.set_enabled(False)
                                gate.invalidate()
                                output_status = 'output_disabled'
                            elif action == 'preview':
                                if not reachable:
                                    raise ValueError('Cannot preview an unreachable target for execution')
                                preview = gate.preview(goal.tolist(), gripper, signature, address, tick)
                                output_status = 'preview_ready_mock' if output.enabled else 'preview_ready_dry_run'
                            elif action == 'confirm':
                                if not reachable:
                                    raise ValueError('Unreachable target invalidates confirmation')
                                preview = gate.confirm(token, signature, address, dry_run=not output.enabled, now=tick)
                                output_status = preview['status']
                        except (ValueError, PermissionError, KeyError, TypeError, OSError) as exc:
                            gate.invalidate()
                            output_status = f'rejected: {exc}'
                            logging.getLogger('tinyarm.hardware').warning('%s', output_status)
                    elif action:
                        output_status = 'output_disabled_no_profile'
                    last_receive = tick
                    feedback = dict(v=1, type='state', seq=seq, reachable=reachable,
                        ik_error_m=error, position=ik.position(data.qpos).tolist(),
                        joints=data.qpos.tolist(), joint_targets=goal.tolist(),
                        orientation=ik.orientation(data.qpos).tolist(),
                        goal_orientation=ik.orientation(goal).tolist(),
                        orientation_requested=orientation is not None,
                        orientation_error_deg=0.0 if angle is None else float(np.rad2deg(angle)),
                        orientation_matched=bool(angle is not None and reachable and angle <= np.deg2rad(5)))
                    feedback.update(physical_enabled=False, output_status=output_status, **preview)
                    tip = ik.position(goal)
                    feedback['preview_links'] = np.concatenate(
                        [ik.data.xpos[i].copy() for i in preview_bodies] + [tip]).tolist()
                    if gate and gate.pending:
                        feedback.update(preview_id=gate.pending['token'],
                            preview_ttl_s=max(0, gate.pending['expires']-tick),
                            preview_joints=list(gate.pending['model_joints']))
                    sock.sendto(json.dumps(feedback, allow_nan=False).encode(), address)
                if tick-last_receive > 0.5:
                    goal = command.copy()  # Freeze command ramp when sender disappears.
                    if gate:
                        gate.invalidate()
                # 0.8 rad/s target slew; motor dynamics remain active.
                command += np.clip(goal-command, -0.8*0.02, 0.8*0.02)
                data.ctrl[:] = command
                for _ in range(40):
                    mujoco.mj_step(model, data)
                if viewer:
                    viewer.sync()
                time.sleep(max(0, 0.02-(time.monotonic()-tick)))
    finally:
        sock.close()


if __name__ == '__main__':
    main()

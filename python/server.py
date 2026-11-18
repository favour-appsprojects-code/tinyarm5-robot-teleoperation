"""Quest/Unity -> JSON UDP -> IK -> MuJoCo, with preview, recording and gated output.

Default: simulation only, loopback bind, UDP 5006, every session recorded to
logs/robot_commands/<session>.jsonl. Physical transmission is locked in code
(RobotSender.set_enabled rejects physical profiles); see docs/hardware.md.
"""
import argparse
from contextlib import nullcontext
import json
import logging
import socket
import time
import mujoco
import numpy as np
from robot import load_robot, IK
from protocol import decode_pose, decode_controls, is_discovery
from hardware import RobotSender, PreviewGate
from command_log import CommandRecorder, command_fields
from receiver_status import ReceiverMonitor
from sim_scene import PickPlaceSim

DEFAULT_PORT = 5006
LINK_BODIES = ('base_link', 'rotor_0', 'rotor_1', 'rotor_2', 'rotor_3', 'rotor_4')
LOG = logging.getLogger('tinyarm.server')


def lan_addresses():
    """Best-effort local IPv4 addresses to show the operator (no packet is sent)."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('10.255.255.255', 1))  # UDP connect only selects a route.
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            if address not in found and not address.startswith('127.'):
                found.append(address)
    except OSError:
        pass
    return found


def rounded(values, digits=5):
    return [round(float(v), digits) for v in values]


def links(model_data, body_ids, tip):
    return rounded(np.concatenate([model_data.xpos[i].copy() for i in body_ids] + [tip]))


def status_flags(*, physical_enabled, mock_enabled, recorder, receiver, reachable, pending,
                 scene_state, connected_profile):
    flags = []
    flags.append('Physical Output Enabled' if physical_enabled else 'Simulation Mode')
    if not physical_enabled:
        flags.append('Physical Output Disabled')
    if mock_enabled:
        flags.append('Mock Output Enabled (loopback only)')
    if receiver:
        flags.append({'receiver_confirmed': 'Robot Connected',
                      'receiver_unavailable': 'Robot Unavailable',
                      'network_reachable_delivery_unverified': 'Robot Connection Unverified'}.get(
            receiver['receiver_state'],
            {'reachable': 'Robot Connection Unverified', 'unreachable': 'Robot Unavailable'}.get(
                receiver['receiver_network'], 'Robot Status Unknown')))
    elif not connected_profile:
        flags.append('No Robot Receiver Configured')
    flags.append('RECORDING FAILED' if recorder.error else 'Recording Commands')
    if not reachable:
        flags.append('IK Target Unreachable')
    if pending:
        flags.append('Movement Ready for Confirmation')
    if scene_state['cube_grasped']:
        flags.append('Cube Grasped')
    if scene_state['task_completed']:
        flags.append(f"Task Complete {scene_state['task_elapsed_s']:.1f} s")
    return flags


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--bind', default='127.0.0.1', help='Interface for Unity JSON targets')
    parser.add_argument('--lan', action='store_true', help='Bind 0.0.0.0 so a Quest on the LAN can connect/discover')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('--output-profile', help='Calibration/mock JSON; never enables physical output')
    parser.add_argument('--mock-output', action='store_true', help='Permit confirmed packets to loopback MOCK ONLY')
    parser.add_argument('--log-dir', help='Command log folder (default logs/robot_commands or $TINYARM_LOG_DIR)')
    parser.add_argument('--receiver-host', help='Robot receiver to monitor (default: physical profile host)')
    parser.add_argument('--receiver-port', type=int, default=5005)
    parser.add_argument('--receiver-tcp-port', type=int, action='append', default=[],
                        help='Optional TCP port on the receiver laptop used only as a reachability probe')
    parser.add_argument('--no-receiver-monitor', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    bind = '0.0.0.0' if args.lan else args.bind

    output = RobotSender.from_file(args.output_profile) if args.output_profile else None
    packet_sender, profile_note = None, 'no output profile: simulation only'
    if output:
        try:
            output.validate_profile()
            packet_sender, profile_note = output, f"{output.config['kind']} profile validated (dry run)"
        except (ValueError, KeyError, TypeError) as exc:
            profile_note = f'profile not usable for packets ({exc}); simulation only'
    if args.mock_output:
        if output is None:
            parser.error('--mock-output requires a loopback mock profile')
        output.set_enabled(True)  # Physical profiles are rejected here, even if marked verified.
        profile_note = 'mock loopback output enabled; confirmation required'
    gate = PreviewGate(packet_sender)
    output_status = ('mock_enabled_confirmation_required' if args.mock_output else
                     'dry_run_only' if packet_sender else 'simulation_only')
    physical_enabled = False  # Locked; no code path sets this True.

    destination = None
    if output is not None:
        try:
            destination = f"{output.config['host']}:{output.config['port']}"
        except KeyError:
            pass
    receiver_host = args.receiver_host or (output.config.get('host') if output is not None and
                                           output.config.get('kind') == 'physical' else None)
    receiver_port = args.receiver_port if args.receiver_host else (
        output.config.get('port', args.receiver_port) if receiver_host else args.receiver_port)
    if destination is None and receiver_host:
        destination = f'{receiver_host}:{receiver_port}'
    monitor = None
    if receiver_host and not args.no_receiver_monitor:
        monitor = ReceiverMonitor(receiver_host, receiver_port, physical_enabled=physical_enabled,
                                  tcp_ports=args.receiver_tcp_port).start()

    recorder = CommandRecorder(args.log_dir)
    gripper_presets = (output.config.get('gripper') or {}) if output is not None else {}

    model = load_robot(scene=True)
    joint_order = tuple(mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(model.njnt))
    if joint_order != ('j0', 'j1', 'j2', 'j3', 'j4'):
        raise RuntimeError(f'Unexpected model/IK joint order: {joint_order}')
    body_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n) for n in LINK_BODIES]
    tip_site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, 'tip')
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    ik = IK(model)
    scene = PickPlaceSim(model, data)
    command = data.qpos.copy()
    goal = command.copy()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind, args.port))
    sock.setblocking(False)
    recorder.record('session_start', bind=f'{bind}:{args.port}', profile=profile_note,
                    destination=destination, physical_enabled=physical_enabled,
                    mock_output=bool(args.mock_output), joint_names=list(joint_order))
    print('Ready UDP', bind, args.port, 'initial tip metres', ik.position(command), flush=True)
    print('Recording', recorder.path, flush=True)
    print('Output:', profile_note, '| physical output LOCKED', flush=True)
    if args.lan:
        print('Quest should use one of:', ', '.join(lan_addresses()) or 'unknown', f'port {args.port}', flush=True)

    def gripper_raw(gripper, values=None):
        if values and len(values) == 6:
            return values[5]
        return gripper_presets.get(f'{gripper}_raw') if gripper in ('open', 'closed') else None

    if not args.headless:
        from mujoco import viewer as mjviewer
        context = mjviewer.launch_passive(model, data)
    else:
        context = nullcontext(None)
    started = time.monotonic()
    last_receive = started
    stream_active = False
    sequences = {}
    gripper_state = None
    reset_target = None
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
                    except ConnectionResetError:  # Windows reports ICMP for earlier replies.
                        continue
                    if is_discovery(packet):
                        reply = dict(v=1, type='discover_reply', server='tinyarm5', port=args.port)
                        try:
                            sock.sendto(json.dumps(reply).encode(), address)
                        except OSError:
                            pass
                        continue
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
                    if gripper is not None:
                        gripper_state = gripper
                    if reset_target is None:
                        reset_target = np.array(target, dtype=float)
                    solution, error, reachable, angle = ik.solve_pose(target, goal, orientation)
                    angle_deg = None if angle is None else float(np.rad2deg(angle))
                    if reachable:
                        goal = solution
                    preview = {}
                    signature = json.dumps([target, orientation, gripper], separators=(',', ':'))
                    gate.observe(signature, address, tick)
                    if gate.pending:
                        goal = np.array(gate.pending['model_joints'])
                    if not reachable:
                        gate.invalidate()
                    if not stream_active:
                        stream_active = True
                    if recorder.should_sample(tick, target, orientation, gripper, reachable):
                        recorder.record('target_sample', **command_fields(
                            target, orientation, goal, gripper, error, angle_deg, reachable,
                            execution_status='live_simulation_only', transmission_attempted=False,
                            transmission_outcome='not_applicable_live_stream', destination=destination))
                    try:
                        if action == 'disable':
                            if output is not None:
                                output.set_enabled(False)
                            gate.invalidate()
                            output_status = 'output_disabled'
                            recorder.record('output_disabled')
                        elif action == 'cancel':
                            gate.invalidate()
                            output_status = 'preview_cancelled'
                            recorder.record('preview_cancelled')
                        elif action == 'reset_scene':
                            scene.reset()
                            reset_target = np.array(target, dtype=float)
                            recorder.record('scene_reset')
                        elif action == 'preview':
                            if not reachable:
                                raise ValueError('Cannot preview an unreachable target for execution')
                            preview = gate.preview(goal.tolist(), gripper, signature, address, tick)
                            output_status = ('preview_ready_mock' if output is not None and output.enabled else
                                             'preview_ready_dry_run' if packet_sender else 'preview_ready_simulation')
                            recorder.record('preview', **command_fields(
                                target, orientation, goal, gripper, error, angle_deg, reachable,
                                preview_id=preview['preview_id'], execution_status='previewed_not_executed',
                                gripper_raw=gripper_raw(gripper, preview['values']),
                                receiver_values=preview['values'], packet_hex=preview['packet_hex'],
                                transmission_attempted=False, transmission_outcome='not_attempted_preview_only',
                                destination=destination))
                        elif action == 'confirm':
                            if not reachable:
                                raise ValueError('Unreachable target invalidates confirmation')
                            dry_run = output is None or not output.enabled

                            def before_send(p, will_transmit):
                                details = PreviewGate.details(p['command'])
                                entry = recorder.record('approved', **command_fields(
                                    target, orientation, p['model_joints'], p['gripper'], error, angle_deg, reachable,
                                    preview_id=p['token'], execution_status='approved_by_user',
                                    gripper_raw=gripper_raw(p['gripper'], details['values']),
                                    receiver_values=details['values'], packet_hex=details['packet_hex'],
                                    transmission_attempted=will_transmit,
                                    transmission_outcome='pending' if will_transmit else
                                    ('not_attempted_dry_run' if p['command'] is not None else
                                     'not_attempted_simulation_only'),
                                    physical_enabled=physical_enabled, destination=destination))
                                # Never transmit an approval that is not durably recorded.
                                return entry is not None or not will_transmit

                            preview = gate.confirm(token, signature, address, dry_run=dry_run,
                                                   now=tick, before_send=before_send)
                            output_status = preview['status']
                            outcome = {'sent_to_loopback_mock': 'sent_to_loopback_mock_unacknowledged',
                                       'confirmed_dry_run_no_transmission': 'not_attempted_dry_run',
                                       'confirmed_simulation_only': 'not_attempted_simulation_only'}[preview['status']]
                            recorder.record('execution_result', preview_id=token, execution_status='confirmed',
                                            transmission_attempted=outcome.startswith('sent'),
                                            transmission_outcome=outcome, delivery_confirmed=False,
                                            destination=preview.get('destination') or destination,
                                            physical_enabled=physical_enabled)
                    except (ValueError, PermissionError, KeyError, TypeError, OSError) as exc:
                        gate.invalidate()
                        output_status = f'rejected: {exc}'
                        LOG.warning('%s', output_status)
                        recorder.record('rejected', action=action, reason=str(exc), preview_id=token or None,
                                        transmission_attempted=isinstance(exc, OSError),
                                        transmission_outcome=f'send_failed: {exc}' if isinstance(exc, OSError) else 'not_attempted',
                                        destination=destination)
                    last_receive = tick
                    tip = ik.position(goal)
                    goal_links = links(ik.data, body_ids, tip)
                    scene_state = scene.state()
                    receiver = monitor.snapshot() if monitor else None
                    feedback = dict(v=1, type='state', seq=seq, reachable=reachable,
                        ik_error_m=error, position=ik.position(data.qpos).tolist(),
                        joints=data.qpos.tolist(), joint_targets=goal.tolist(),
                        orientation=ik.orientation(data.qpos).tolist(),
                        goal_orientation=ik.orientation(goal).tolist(),
                        orientation_requested=orientation is not None,
                        orientation_error_deg=0.0 if angle is None else angle_deg,
                        orientation_matched=bool(angle is not None and reachable and angle <= np.deg2rad(5)))
                    feedback.update(physical_enabled=physical_enabled, output_status=output_status, **preview)
                    feedback['preview_links'] = goal_links
                    feedback['sim_links'] = links(data, body_ids, data.site_xpos[tip_site])
                    feedback.update(scene_state, gripper_state=gripper_state or '')
                    feedback.update(recording_session=recorder.session_id, recording_file=recorder.path.name,
                                    recorded_events=recorder.total, recording_error=recorder.error or '')
                    if receiver:
                        feedback.update(receiver)
                    feedback['status_flags'] = status_flags(
                        physical_enabled=physical_enabled, mock_enabled=bool(output is not None and output.enabled),
                        recorder=recorder, receiver=receiver, reachable=reachable,
                        pending=bool(gate.pending), scene_state=scene_state,
                        connected_profile=packet_sender is not None)
                    if gate.pending:
                        feedback.update(preview_id=gate.pending['token'],
                            preview_ttl_s=max(0, gate.pending['expires']-tick),
                            preview_joints=list(gate.pending['model_joints']))
                    for key in ('values',):
                        if feedback.get(key) is None:
                            feedback.pop(key, None)
                    try:
                        sock.sendto(json.dumps(feedback, allow_nan=False).encode(), address)
                    except OSError as exc:
                        LOG.warning('Feedback to %s failed: %s', address, exc)
                if tick-last_receive > 0.5:
                    goal = command.copy()  # Freeze command ramp when sender disappears.
                    gate.invalidate()
                    if stream_active:
                        stream_active = False
                        recorder.record('stream_timeout', note='no target for 0.5 s; command frozen, preview cleared')
                # 0.8 rad/s target slew; motor dynamics remain active.
                command += np.clip(goal-command, -0.8*0.02, 0.8*0.02)
                data.ctrl[:] = command
                for _ in range(40):
                    mujoco.mj_step(model, data)
                user_active = reset_target is not None and stream_active and \
                    np.linalg.norm(ik.position(goal) - reset_target) > 0.005
                scene.step(0.02, data.site_xpos[tip_site], gripper_state, user_active)
                if scene.just_completed:
                    recorder.record('task_completed', elapsed_s=round(scene.completed_time, 2))
                    print(f'TASK COMPLETE: cube in cup after {scene.completed_time:.2f} s', flush=True)
                if viewer:
                    viewer.sync()
                time.sleep(max(0, 0.02-(time.monotonic()-tick)))
    finally:
        sock.close()
        recorder.close()
        if monitor:
            monitor.stop()


if __name__ == '__main__':
    main()

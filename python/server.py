"""Unity -> UDP -> IK -> MuJoCo, with loopback binding by default."""
import argparse
from contextlib import nullcontext
import json
import socket
import time
import mujoco
import numpy as np
from robot import load_robot, IK
from protocol import decode_target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=5005)
    parser.add_argument('--seconds', type=float, default=0)
    args = parser.parse_args()
    model = load_robot()
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
                        seq, target = decode_target(packet)
                        previous, received = sequences.get(address, (-1, 0))
                        if tick-received < 2 and seq <= previous:
                            continue
                        sequences[address] = (seq, tick)
                        pending = (seq, target, address)
                    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
                        continue
                if pending:
                    seq, target, address = pending
                    solution, error, reachable = ik.solve(target, goal)
                    if reachable:
                        goal = solution
                    last_receive = tick
                    feedback = dict(v=1, type='state', seq=seq, reachable=reachable,
                        ik_error_m=error, position=ik.position(data.qpos).tolist(),
                        joints=data.qpos.tolist(), joint_targets=goal.tolist())
                    sock.sendto(json.dumps(feedback, allow_nan=False).encode(), address)
                if tick-last_receive > 0.5:
                    goal = command.copy()  # Freeze command ramp when sender disappears.
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

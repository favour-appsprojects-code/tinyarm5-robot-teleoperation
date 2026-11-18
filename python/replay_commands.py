"""Dry-run playback of recorded commands in MuJoCo. SIMULATION ONLY.

This tool has no network code and does not import the hardware sender: a
recorded command can never reach the physical robot through it. Physical
execution of an old command requires a fresh preview and a new confirmation
in a live session.

  python python/replay_commands.py logs/robot_commands/<session>.jsonl
  python python/replay_commands.py <log> --events preview approved --headless
"""
import argparse
import time
import mujoco
import numpy as np
from command_log import read_log
from robot import load_robot, IK
from sim_scene import PickPlaceSim

SLEW_RAD_S = 0.8   # Same target ramp as the live server.
DT = 0.02


def select(entries, events=('approved',)):
    return [e for e in entries if e.get('event') in events and e.get('joint_angles_rad')]


def replay(commands, model=None, data=None, viewer=None, dwell_s=0.6, realtime=False, max_move_s=8.0):
    """Drive the simulated arm through each command; return per-command results."""
    model = model or load_robot(scene=True)
    data = data if data is not None else mujoco.MjData(model)
    ik = IK(model)
    scene = PickPlaceSim(model, data)
    tip_site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, 'tip')
    command = data.qpos.copy()
    lower, upper = model.jnt_range.T
    results = []
    for entry in commands:
        goal = np.asarray(entry['joint_angles_rad'], dtype=float)
        if goal.shape != (5,) or not np.all(np.isfinite(goal)):
            results.append(dict(sequence=entry.get('sequence'), skipped='invalid joints'))
            continue
        if np.any(goal < lower) or np.any(goal > upper):
            results.append(dict(sequence=entry.get('sequence'), skipped='outside model limits'))
            continue
        settle = elapsed = 0.0
        while settle < dwell_s and elapsed < max_move_s:
            tick = time.monotonic()
            command += np.clip(goal - command, -SLEW_RAD_S*DT, SLEW_RAD_S*DT)
            data.ctrl[:] = command
            for _ in range(40):
                mujoco.mj_step(model, data)
            scene.step(DT, data.site_xpos[tip_site], entry.get('gripper'), True)
            elapsed += DT
            if np.allclose(command, goal):
                settle += DT
            if viewer is not None:
                if not viewer.is_running():
                    return results
                viewer.sync()
            if realtime:
                time.sleep(max(0, DT - (time.monotonic()-tick)))
        results.append(dict(sequence=entry.get('sequence'), event=entry.get('event'),
                            joint_error_rad=round(float(np.max(np.abs(data.qpos - goal))), 5),
                            tip_error_mm=round(float(np.linalg.norm(data.site_xpos[tip_site] - ik.position(goal))*1000), 3),
                            recorded_target=entry.get('target_position_m'),
                            cube_grasped=scene.grasped, cube_in_cup=scene.in_cup()))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('log')
    parser.add_argument('--events', nargs='+', default=['approved'])
    parser.add_argument('--headless', action='store_true')
    args = parser.parse_args()
    commands = select(read_log(args.log), tuple(args.events))
    print(f'SIMULATION-ONLY REPLAY of {len(commands)} command(s) from {args.log}; nothing is transmitted.')
    model = load_robot(scene=True)
    if args.headless:
        results = replay(commands, model)
    else:
        from mujoco import viewer as mjviewer
        data = mujoco.MjData(model)
        with mjviewer.launch_passive(model, data) as viewer:
            viewer.opt.geomgroup[0] = 0
            results = replay(commands, model, data, viewer, realtime=True)
    for r in results:
        print(r)


if __name__ == '__main__':
    main()

"""IK -> validated binary preview -> dry run (or explicit loopback mock)."""
import argparse
import json
from pathlib import Path
import numpy as np
from hardware import RobotSender, PreviewGate
from robot import IK, load_robot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', default=str(Path(__file__).with_name('config') / 'mock.json'))
    parser.add_argument('--target', type=float, nargs=3, default=[0,-0.22,0.16])
    parser.add_argument('--gripper', choices=['open', 'closed'])
    parser.add_argument('--mock-output', action='store_true', help='Actually send to configured LOOPBACK mock only')
    args = parser.parse_args()
    solver = IK(load_robot())
    joints, error, reachable = solver.solve(args.target, np.zeros(5))
    if not reachable:
        parser.error(f'Target unreachable, IK residual {error} m')
    sender = RobotSender.from_file(args.profile)
    gate = PreviewGate(sender)
    preview = gate.preview(joints.tolist(), args.gripper, 'demo', 'local_cli')
    print(json.dumps(dict(model_joints=joints.tolist(), ik_error_m=error, **preview), indent=2))
    if args.mock_output:
        sender.set_enabled(True)
    result = gate.confirm(preview['preview_id'], 'demo', 'local_cli', dry_run=not args.mock_output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

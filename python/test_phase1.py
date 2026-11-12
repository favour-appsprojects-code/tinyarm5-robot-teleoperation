"""Numerical, motor-dynamics, and real loopback UDP integration checks."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
import mujoco
import numpy as np
from robot import load_robot, IK
from protocol import decode_target


class Phase1(unittest.TestCase):
    def test_reset_after_workspace_boundary(self):
        solver = IK(load_robot())
        reset = [0, -0.12, 0.15]
        # Reproduce the old single-seed solver's small-step ascent, like E.
        seed, _, ok = solver._solve_local(reset, np.zeros(5))
        self.assertTrue(ok)
        rejections = 0
        for height in np.arange(0.15, 0.4, 0.001):
            candidate, _, ok = solver._solve_local([0, -0.12, height], seed)
            if ok:
                seed = candidate
            else:
                rejections += 1
        self.assertGreater(rejections, 0)
        self.assertFalse(solver._solve_local(reset, seed)[2])
        recovered, error, ok = solver.solve(reset, seed)
        self.assertTrue(ok)
        self.assertLessEqual(error, 0.0015)
        self.assertTrue(np.all(recovered >= solver.model.jnt_range[:, 0]))
        self.assertTrue(np.all(recovered <= solver.model.jnt_range[:, 1]))
        print(f'Reset recovered from boundary: {error*1000:.3f}mm')
        # Also exercise the corrected solver throughout ascent and recovery.
        seed, _, _ = solver.solve(reset, np.zeros(5))
        for height in np.arange(0.15, 0.4, 0.001):
            candidate, _, ok = solver.solve([0, -0.12, height], seed)
            if ok:
                seed = candidate
        self.assertTrue(solver.solve(reset, seed)[2])

    def test_ik_and_dynamics(self):
        model = load_robot()
        solver = IK(model)
        seed = np.zeros(5)
        targets = [[0,-0.12,0.15], [0.04,-0.16,0.16], [-0.04,-0.18,0.12]]
        for target in targets:
            goal, error, ok = solver.solve(target, seed)
            self.assertTrue(ok, (target, error))
            self.assertTrue(np.all(goal >= model.jnt_range[:,0]))
            self.assertTrue(np.all(goal <= model.jnt_range[:,1]))
            data = mujoco.MjData(model)
            data.qpos[:] = seed
            command = seed.copy()
            for _ in range(400):
                command += np.clip(goal-command, -0.016, 0.016)
                data.ctrl[:] = command
                for _ in range(40):
                    mujoco.mj_step(model, data)
            actual_error = np.linalg.norm(solver.position(data.qpos)-target)
            print(f'target={target} IK={error*1000:.3f}mm simulated={actual_error*1000:.3f}mm')
            self.assertLess(actual_error, 0.008)
            seed = goal
        self.assertFalse(solver.solve([0.9,0.9,0.9],seed)[2])

    def test_validation(self):
        for packet in [b'{}', b'no', b'{"v":1,"type":"target","seq":1,"position":[NaN,0,0]}',
                       b'{"v":1,"type":"target","seq":true,"position":[0,0,0]}']:
            with self.assertRaises((ValueError,KeyError)):
                decode_target(packet)

    def test_udp(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reservation:
            reservation.bind(('127.0.0.1',0))
            port = reservation.getsockname()[1]
        process = subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py')),
            '--headless','--port',str(port),'--seconds','15'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            self.assertIn('Ready UDP', process.stdout.readline())
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
                client.settimeout(2)
                def request(seq, target):
                    client.sendto(json.dumps(dict(v=1,type='target',seq=seq,position=target)).encode(),('127.0.0.1',port))
                    return json.loads(client.recv(4096))
                first = request(1,[0,-0.12,0.15])
                self.assertTrue(first['reachable'])
                rejected = request(2,[0.9,0.9,0.9])
                self.assertFalse(rejected['reachable'])
                self.assertEqual(first['joint_targets'],rejected['joint_targets'])
                for seq in range(3,123):
                    feedback = request(seq,[0,-0.12,0.15])
                    time.sleep(0.04)
                error = np.linalg.norm(np.array(feedback['position'])-[0,-0.12,0.15])
                print(f'UDP live simulated tip error: {error*1000:.3f}mm')
                self.assertLess(error,0.008)
                # Duplicate command receives no reply and cannot change the goal.
                client.sendto(json.dumps(dict(v=1,type='target',seq=122,position=[0,0,0])).encode(),('127.0.0.1',port))
                client.settimeout(0.2)
                with self.assertRaises(socket.timeout): client.recv(4096)
        finally:
            process.terminate()
            process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)

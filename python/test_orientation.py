"""Position-priority pose IK and optional-quaternion UDP regression tests."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
import mujoco
import numpy as np
from protocol import decode_pose
from robot import IK, load_robot


class Orientation(unittest.TestCase):
    def setUp(self):
        self.solver = IK(load_robot())

    def test_feasible_pose_improves_orientation(self):
        solver = self.solver
        reference = np.array([0.2, 0.4, -0.6, -0.4, 0.3])
        position = solver.position(reference)
        desired = solver.orientation(reference)
        seed, _, _ = solver.solve(position, np.zeros(5))
        before = np.linalg.norm(solver.rotation_error(desired, seed))
        goal, distance, ok, after = solver.solve_pose(position, seed, desired)
        self.assertTrue(ok)
        self.assertLessEqual(distance, 0.0015)
        self.assertLess(after, np.deg2rad(1))
        self.assertLess(after, before/10)
        np.testing.assert_array_less(goal, solver.model.jnt_range[:,1]+1e-10)
        np.testing.assert_array_less(solver.model.jnt_range[:,0]-1e-10, goal)
        print(f'Feasible orientation: {np.rad2deg(before):.3f} -> {np.rad2deg(after):.3f} degrees; position {distance*1000:.3f} mm')
        # Equivalent quaternion signs must yield identical physical solutions.
        antipodal = solver.solve_pose(position, seed, -desired)
        np.testing.assert_allclose(goal, antipodal[0], atol=1e-8)

    def test_incompatible_rotation_preserves_position(self):
        solver = self.solver
        target = [0, -0.12, 0.15]
        seed, _, _ = solver.solve(target, np.zeros(5))
        desired = np.array([1., 0, 0, 0])
        # This is nearly pi from the starting tool orientation.
        goal, distance, ok, angle = solver.solve_pose(target, seed, desired)
        self.assertTrue(ok)
        self.assertLessEqual(distance, 0.0015)
        self.assertGreater(angle, np.deg2rad(5))
        self.assertTrue(np.all(np.isfinite(goal)))
        self.assertFalse(solver.solve_pose([0.9, 0.9, 0.9], seed, desired)[2])
        print(f'Incompatible rotation: residual {np.rad2deg(angle):.3f} degrees; position {distance*1000:.3f} mm')

    def test_rotation_error_matches_world_jacobian(self):
        solver = self.solver
        q = np.array([0.2, 0.4, -0.6, -0.4, 0.3])
        solver.position(q)
        jac = np.empty((3, 5))
        mujoco.mj_jacSite(solver.model, solver.data, None, jac, solver.tip)
        for joint in range(5):
            offset = q.copy()
            offset[joint] += 1e-6
            desired = solver.orientation(offset)
            measured = solver.rotation_error(desired, q) / 1e-6
            np.testing.assert_allclose(measured, jac[:,joint], atol=1e-6)

    def test_orientation_demo_pose_has_rotation_headroom(self):
        solver = self.solver
        position = [0, -0.22, 0.16]
        seed, _, ok = solver.solve(position, np.zeros(5))
        self.assertTrue(ok)
        self.assertGreater(np.min(np.pi/2-np.abs(seed)), 0.5)
        start = solver.orientation(seed)
        delta = np.empty(4)
        mujoco.mju_axisAngle2Quat(delta, np.array([1., 0, 0]), np.deg2rad(35))
        desired = np.empty(4)
        mujoco.mju_mulQuat(desired, start, delta)
        goal, distance, ok, angle = solver.solve_pose(position, seed, desired)
        self.assertTrue(ok)
        self.assertLessEqual(distance, 0.0015)
        self.assertLess(angle, np.deg2rad(1))
        self.assertGreater(np.max(np.abs(goal-seed)), 0.1)
        print(f'Demo pose +35deg X: residual {np.rad2deg(angle):.3f} degrees; position {distance*1000:.3f} mm')

    def test_protocol_and_position_only_compatibility(self):
        base = dict(v=1, type='target', seq=1, position=[0,-0.12,0.15])
        self.assertIsNone(decode_pose(json.dumps(base))[2])
        self.assertIsNone(decode_pose(json.dumps(dict(base, orientation_enabled=False, orientation=[1,0,0,0])))[2])
        np.testing.assert_allclose(decode_pose(json.dumps(dict(base,orientation=[2,0,0,0])))[2], [1,0,0,0])
        for invalid in ([0,0,0,0], [1,0,0], [True,0,0,0], [float('nan'),0,0,0], [3,0,0,0]):
            with self.assertRaises(ValueError):
                decode_pose(json.dumps(dict(base, orientation=invalid)))
        seed = np.zeros(5)
        pose = self.solver.solve_pose(base['position'], seed)
        old = self.solver.solve(base['position'], seed)
        np.testing.assert_allclose(pose[0], old[0])
        self.assertIsNone(pose[3])

    def test_udp_pose_feedback_and_rejection(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('server.py')),
            '--headless', '--port', str(port), '--seconds', '10'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            self.assertIn('Ready UDP', process.stdout.readline())
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(3)
                def request(seq, position, orientation=None):
                    client.sendto(json.dumps(dict(v=1,type='target',seq=seq,
                        position=position,orientation=orientation)).encode(), ('127.0.0.1',port))
                    return json.loads(client.recv(4096))
                first = request(1, [0,-0.12,0.15])
                self.assertFalse(first['orientation_requested'])
                initial = first['goal_orientation']
                matched = request(2, [0,-0.12,0.15], initial)
                self.assertTrue(matched['orientation_matched'])
                self.assertEqual(len(matched['orientation']), 4)
                limited = request(3, [0,-0.12,0.15], [1,0,0,0])
                self.assertTrue(limited['reachable'])
                self.assertFalse(limited['orientation_matched'])
                self.assertLessEqual(limited['ik_error_m'], 0.0015)
                rejected = request(4, [0.9,0.9,0.9], initial)
                self.assertFalse(rejected['reachable'])
                self.assertEqual(rejected['joint_targets'], limited['joint_targets'])
                recovered = request(5, [0,-0.12,0.15], initial)
                self.assertTrue(recovered['reachable'])
                self.assertLessEqual(recovered['ik_error_m'], 0.0015)
        finally:
            process.terminate()
            process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)

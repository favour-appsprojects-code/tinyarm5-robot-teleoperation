"""Recording, fallback, export, replay, receiver status, discovery and scene tests."""
import copy
import csv
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import numpy as np
from command_log import CommandRecorder, command_fields, read_log
from export_commands import export
from hardware import PreviewGate, RobotSender
from receiver_status import ReceiverMonitor, ping_succeeded
from replay_commands import replay, select
from robot import IK, load_robot
from sim_scene import CUBE_START, CUP_CENTER, PickPlaceSim
import mujoco

MOCK = json.loads((Path(__file__).with_name('config') / 'mock.json').read_text())
JOINTS = [0.1, -0.2, 0.3, -0.05, 0.25]


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def test_entries_preserve_exact_joint_order_and_values(self):
        recorder = CommandRecorder(self.folder.name, session_id='s1')
        recorder.record('approved', **command_fields([0, -0.2, 0.15], [1, 0, 0, 0], JOINTS, 'closed',
                                                     0.0004, 1.5, True, transmission_attempted=False,
                                                     transmission_outcome='not_attempted_simulation_only',
                                                     destination='192.168.1.244:5005'))
        recorder.close()
        [entry] = read_log(Path(self.folder.name) / 's1.jsonl')
        self.assertEqual(entry['joint_names'], ['j0', 'j1', 'j2', 'j3', 'j4'])
        self.assertEqual(entry['joint_angles_rad'], JOINTS)
        self.assertEqual(entry['event'], 'approved')
        self.assertFalse(entry['transmission_attempted'])
        self.assertEqual(entry['destination'], '192.168.1.244:5005')
        for key in ('timestamp', 'sequence', 'session_id', 'target_position_m', 'target_orientation_wxyz',
                    'gripper', 'ik_position_error_m', 'ik_orientation_error_deg', 'validation',
                    'execution_status' if 'execution_status' in entry else 'event'):
            self.assertIn(key, entry)

    def test_rejects_non_finite_and_wrong_joint_count(self):
        with self.assertRaises(ValueError):
            command_fields([0, 0, 0], None, [0, 0, 0, 0], None, 0, None, True)
        recorder = CommandRecorder(self.folder.name)
        self.addCleanup(recorder.close)
        self.assertIsNone(recorder.record('approved', joint_angles_rad=[float('nan')]*5))
        self.assertIsNotNone(recorder.error)

    def test_sampling_is_rate_limited_and_change_based(self):
        recorder = CommandRecorder(self.folder.name)
        self.addCleanup(recorder.close)
        args = ([0, -0.2, 0.15], None, 'open', True)
        self.assertTrue(recorder.should_sample(0.0, *args))
        self.assertFalse(recorder.should_sample(0.1, *args))          # too soon
        self.assertFalse(recorder.should_sample(1.0, *args))          # unchanged
        self.assertTrue(recorder.should_sample(1.0, [0, -0.2, 0.153], None, 'open', True))
        self.assertTrue(recorder.should_sample(1.3, [0, -0.2, 0.153], None, 'closed', True))
        self.assertTrue(recorder.should_sample(1.6, [0, -0.2, 0.153], None, 'closed', False))

    def test_write_failure_is_reported_not_silent(self):
        recorder = CommandRecorder(self.folder.name)
        self.addCleanup(recorder.close)
        with mock.patch.object(recorder._file, 'write', side_effect=OSError('disk full')):
            self.assertIsNone(recorder.record('approved'))
        self.assertIn('disk full', recorder.error)

    def test_unrecorded_approval_never_transmits(self):
        sender = RobotSender(MOCK)
        sender.set_enabled(True)
        gate = PreviewGate(sender)
        preview = gate.preview(JOINTS, 'open', 'sig', 'me', now=0)
        with mock.patch('socket.socket') as sockets:
            with self.assertRaises(PermissionError):
                gate.confirm(preview['preview_id'], 'sig', 'me', dry_run=False, now=1,
                             before_send=lambda p, transmit: False)
            sockets.assert_not_called()

    def test_simulation_only_gate_previews_and_confirms_without_packet(self):
        gate = PreviewGate(None)
        preview = gate.preview(JOINTS, None, 'sig', 'me', now=0)
        self.assertEqual(preview['packet_bytes'], 0)
        seen = []
        result = gate.confirm(preview['preview_id'], 'sig', 'me', now=1,
                              before_send=lambda p, transmit: seen.append((p['model_joints'], transmit)))
        self.assertEqual(result['status'], 'confirmed_simulation_only')
        self.assertEqual(seen, [(tuple(JOINTS), False)])
        with self.assertRaises(PermissionError):
            gate.confirm(preview['preview_id'], 'sig', 'me', now=2)

    def test_export_csv_contains_only_approved_by_default(self):
        recorder = CommandRecorder(self.folder.name, session_id='s2')
        for event, joints in [('target_sample', [0]*5), ('preview', JOINTS), ('approved', JOINTS)]:
            recorder.record(event, **command_fields([0, -0.2, 0.15], None, joints, 'open', 0.001, None, True))
        recorder.close()
        out = Path(self.folder.name) / 'out.csv'
        self.assertEqual(export(recorder.path, out), 1)
        with out.open(newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]['event'], 'approved')
        self.assertEqual([float(rows[0][f'j{i}_rad']) for i in range(5)], JOINTS)
        self.assertEqual(export(recorder.path, out, include_all=True), 3)


class ReplayTests(unittest.TestCase):
    def test_replay_reaches_recorded_joints_without_network(self):
        model = load_robot(scene=True)
        ik = IK(model)
        q, _, ok = ik.solve([0.0, -0.2, 0.12], np.zeros(5))
        self.assertTrue(ok)
        entries = [dict(sequence=1, event='approved', joint_angles_rad=q.tolist(), gripper='open'),
                   dict(sequence=2, event='preview', joint_angles_rad=[0.0]*5),
                   dict(sequence=3, event='approved', joint_angles_rad=[9, 0, 0, 0, 0])]
        commands = select(entries)
        self.assertEqual([c['sequence'] for c in commands], [1, 3])
        with mock.patch('socket.socket', side_effect=AssertionError('replay must not use the network')):
            results = replay(commands, model)
        self.assertLess(results[0]['joint_error_rad'], 0.05)
        self.assertLess(results[0]['tip_error_mm'], 5)
        self.assertEqual(results[1]['skipped'], 'outside model limits')


class ReceiverStatusTests(unittest.TestCase):
    def test_states_never_claim_delivery_without_ack(self):
        disabled = ReceiverMonitor('192.168.1.244', 5005, probe=lambda h: True)
        self.assertEqual(disabled.poll_once()['receiver_state'], 'physical_disabled')
        self.assertEqual(disabled.snapshot()['receiver_network'], 'reachable')
        enabled = ReceiverMonitor('192.168.1.244', 5005, physical_enabled=True, probe=lambda h: True)
        state = enabled.poll_once()
        self.assertEqual(state['receiver_state'], 'network_reachable_delivery_unverified')
        self.assertEqual(state['receiver_delivery'], 'unverified')
        down = ReceiverMonitor('192.168.1.244', 5005, physical_enabled=True, probe=lambda h: False)
        self.assertEqual(down.poll_once()['receiver_state'], 'receiver_unavailable')
        broken = ReceiverMonitor('192.168.1.244', 5005, physical_enabled=True,
                                 probe=mock.Mock(side_effect=RuntimeError('x')))
        self.assertEqual(broken.poll_once()['receiver_state'], 'unknown')

    def test_windows_router_unreachable_reply_is_not_success(self):
        self.assertFalse(ping_succeeded(0, 'Reply from 192.168.1.1: Destination host unreachable.', True))
        self.assertTrue(ping_succeeded(0, 'Reply from 192.168.1.244: bytes=32 time=3ms TTL=128', True))
        self.assertFalse(ping_succeeded(1, '', False))

    def test_monitor_never_sends_udp_to_receiver(self):
        with mock.patch('receiver_status.icmp_ping', return_value=False), \
             mock.patch('socket.socket') as sockets:
            ReceiverMonitor('192.168.1.244', 5005, tcp_ports=()).poll_once()
            sockets.assert_not_called()


class SceneTests(unittest.TestCase):
    def test_grasp_carry_and_drop_in_cup_with_timer(self):
        model = load_robot(scene=True)
        data = mujoco.MjData(model)
        sim = PickPlaceSim(model, data)
        cube = np.array(CUBE_START)
        sim.step(0.02, cube + [0, 0, 0.1], 'closed', True)       # closing far away
        sim.step(0.02, cube, 'closed', True)                     # sweeping closed: no grasp
        self.assertFalse(sim.grasped)
        sim.step(0.02, cube, 'open', True)
        sim.step(0.02, cube + [0, 0, 0.005], 'closed', True)     # close near cube
        self.assertTrue(sim.grasped)
        above_cup = np.array([CUP_CENTER[0], CUP_CENTER[1], 0.1])
        sim.step(0.02, above_cup, 'closed', True)
        self.assertAlmostEqual(sim.cube[0], CUP_CENTER[0], delta=0.006)
        for _ in range(100):
            sim.step(0.02, above_cup, 'open', True)
        self.assertTrue(sim.in_cup())
        self.assertTrue(sim.completed)
        self.assertGreater(sim.completed_time, 0)


class ServerIntegrationTests(unittest.TestCase):
    def start(self, *extra):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
            reservation.bind(('127.0.0.1', 0))
            self.port = reservation.getsockname()[1]
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('server.py')),
                                         '--headless', '--seconds', '25', '--port', str(self.port),
                                         '--log-dir', self.folder.name, *extra],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (self.process.terminate(), self.process.communicate(timeout=5)))
        self.assertIn('Ready UDP', self.process.stdout.readline())
        self.client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client.settimeout(3)
        self.addCleanup(self.client.close)
        self.seq = 0

    def request(self, action='', token='', position=(0, -0.22, 0.16), gripper='open'):
        self.seq += 1
        self.client.sendto(json.dumps(dict(v=1, type='target', seq=self.seq, position=list(position),
                                           action=action, preview_id=token, gripper=gripper)).encode(),
                           ('127.0.0.1', self.port))
        return json.loads(self.client.recv(16384))

    def log(self):
        return read_log(next(Path(self.folder.name).glob('*.jsonl')))

    def test_simulation_fallback_records_preview_and_approval(self):
        self.start('--receiver-host', '192.0.2.1', '--receiver-port', '5005')  # TEST-NET: unreachable
        self.client.sendto(b'{"v":1,"type":"discover"}', ('127.0.0.1', self.port))
        self.assertEqual(json.loads(self.client.recv(4096))['type'], 'discover_reply')
        state = self.request()
        self.assertIn('Simulation Mode', state['status_flags'])
        self.assertIn('Physical Output Disabled', state['status_flags'])
        self.assertIn('Recording Commands', state['status_flags'])
        self.assertEqual(len(state['sim_links']), 21)
        self.assertEqual(state['receiver_state'], 'physical_disabled')
        preview = self.request('preview')
        self.assertIn('Movement Ready for Confirmation', preview['status_flags'])
        self.assertEqual(preview['packet_bytes'], 0)
        frozen = preview['preview_joints']
        result = self.request('confirm', preview['preview_id'])
        self.assertEqual(result['output_status'], 'confirmed_simulation_only')
        cancelled = self.request('preview')
        self.request('cancel')
        late = self.request('confirm', cancelled['preview_id'])
        self.assertTrue(late['output_status'].startswith('rejected:'))
        unreachable = self.request(position=(0, 0, 0))
        self.assertIn('IK Target Unreachable', unreachable['status_flags'])
        events = self.log()
        approved = [e for e in events if e['event'] == 'approved']
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]['joint_angles_rad'], frozen)
        self.assertFalse(approved[0]['transmission_attempted'])
        self.assertEqual(approved[0]['transmission_outcome'], 'not_attempted_simulation_only')
        self.assertEqual(approved[0]['destination'], '192.0.2.1:5005')
        results = [e for e in events if e['event'] == 'execution_result']
        self.assertEqual(results[0]['delivery_confirmed'], False)
        self.assertTrue(any(e['event'] == 'preview' and e['execution_status'] == 'previewed_not_executed'
                            for e in events))
        self.assertTrue(any(e['event'] == 'rejected' for e in events))

    def test_reconnect_never_replays_old_commands(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(('127.0.0.1', 0))
            receiver.settimeout(0.3)
            profile = copy.deepcopy(MOCK)
            profile['port'] = receiver.getsockname()[1]
            path = Path(tempfile.mkdtemp()) / 'mock.json'
            path.write_text(json.dumps(profile))
            self.start('--output-profile', str(path), '--mock-output')
            preview = self.request('preview')
            self.request('confirm', preview['preview_id'])
            packet, _ = receiver.recvfrom(4096)
            self.assertEqual(packet.hex(), preview['packet_hex'])
            time.sleep(1.0)                                   # stream drops out
            for _ in range(5):
                state = self.request()                        # stream resumes
            with self.assertRaises(socket.timeout):
                receiver.recvfrom(4096)
            self.assertNotIn('Movement Ready for Confirmation', state['status_flags'])
            events = self.log()
            self.assertEqual(sum(e['event'] == 'approved' for e in events), 1)
            self.assertTrue(any(e['event'] == 'stream_timeout' for e in events))
            sent = [e for e in events if e['event'] == 'execution_result']
            self.assertEqual(sent[0]['transmission_outcome'], 'sent_to_loopback_mock_unacknowledged')


if __name__ == '__main__':
    unittest.main(verbosity=2)

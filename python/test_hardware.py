import copy
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from hardware import RobotSender, PreviewGate, PreparedCommand, pack_packet, unpack_packet

CONFIG = Path(__file__).with_name('config')


class Hardware(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((CONFIG/'mock.json').read_text())
        self.sender = RobotSender(self.profile)
        self.joints = [0, 0.2, -0.1, 0, 0.3]

    def test_wire_five_and_six_values_little_endian(self):
        for gripper, size in [(None,20), (3000,24), (2500,24)]:
            packet = pack_packet(self.joints, gripper)
            values = self.joints + ([] if gripper is None else [gripper])
            self.assertEqual(len(packet), size)
            self.assertEqual(packet, b''.join(struct.pack('<f',v) for v in values))
            self.assertEqual(unpack_packet(packet), struct.unpack(f'<{len(values)}f',packet))
        self.assertEqual(pack_packet([1,0,0,0,0])[:4], b'\x00\x00\x80\x3f')

    def test_bad_numbers_counts_and_gripper(self):
        for invalid in (float('nan'),float('inf'),-float('inf'),True,1e100):
            with self.assertRaises(ValueError): pack_packet([invalid,0,0,0,0])
        for joints in ([], [0]*4, [0]*6):
            with self.assertRaises(ValueError): pack_packet(joints)
        for value in (-1, 3001, float('nan'), 'unknown'):
            with self.assertRaises(ValueError): self.sender.prepare(self.joints,value)
        self.assertEqual(self.sender.prepare(self.joints,'open').values[-1],3000)
        self.assertEqual(self.sender.prepare(self.joints,'closed').values[-1],2500)
        self.profile['gripper'] = None
        with self.assertRaises(ValueError): RobotSender(self.profile).prepare(self.joints,'open')
        for packet in (b'',b'\0'*21,struct.pack('<5f',float('inf'),0,0,0,0)):
            with self.assertRaises(ValueError): unpack_packet(packet)

    def test_reorder_sign_and_offset(self):
        self.profile['arm'].reverse()
        self.profile['arm'][0]['sign'] = -1
        self.profile['arm'][0]['offset_rad'] = 0.1
        command = RobotSender(self.profile).prepare(self.joints)
        self.assertAlmostEqual(command.values[0],-0.2)
        self.assertEqual(command.values[1:],(0,-0.1,0.2,0))
        self.profile['arm'][0]['limits_rad'] = [-0.1,0.1]
        with self.assertRaises(ValueError): RobotSender(self.profile).prepare(self.joints)
        with self.assertRaises(ValueError): self.sender.prepare([2,0,0,0,0])

    def test_no_socket_when_disabled_unconfirmed_or_unverified(self):
        command = self.sender.prepare(self.joints)
        with patch('hardware.socket.socket') as network:
            with self.assertRaises(PermissionError): self.sender.send(command,confirmed=True)
            self.sender.set_enabled(True)
            with self.assertRaises(PermissionError): self.sender.send(command)
            physical = RobotSender.from_file(CONFIG/'hardware.unverified.json')
            with self.assertRaises(ValueError): physical.prepare(self.joints)
            with self.assertRaises(ValueError): physical.set_enabled(True)
            verified = copy.deepcopy(self.profile)
            verified.update(kind='physical',host='192.168.1.244',port=5005)
            with self.assertRaises(PermissionError): RobotSender(verified).set_enabled(True)
            network.assert_not_called()

    def test_mock_cannot_target_remote_or_use_simulation_port(self):
        for host,port in [('192.168.1.244',15005),('127.0.0.1',5005),('localhost',15005)]:
            self.profile.update(host=host,port=port)
            with self.assertRaises(ValueError): RobotSender(self.profile).set_enabled(True)

    def test_mapping_rejects_duplicates_and_missing_calibration(self):
        for field,value in [('sign',None),('offset_rad',None),('motor_id',None),('limits_rad',[1,0])]:
            c = copy.deepcopy(self.profile)
            c['arm'][0][field] = value
            with self.assertRaises((ValueError,TypeError)): RobotSender(c).prepare(self.joints)
        self.profile['arm'][0]['joint'] = 'j1'
        with self.assertRaises(ValueError): RobotSender(self.profile).prepare(self.joints)

    def test_frozen_one_use_confirmation_and_invalidation(self):
        gate = PreviewGate(self.sender, ttl=5)
        with patch('hardware.socket.socket') as network:
            preview = gate.preview(self.joints,None,'target','client',now=10)
            self.joints[0] = 0.5
            result = gate.confirm(preview['preview_id'],'target','client',now=11)
            self.assertEqual(result['values'][0],0)
            self.assertEqual(result['status'],'confirmed_dry_run_no_transmission')
            with self.assertRaises(PermissionError): gate.confirm(preview['preview_id'],'target','client',now=12)
            for signature,owner,now in [('changed','client',11),('target','other',11),('target','client',16)]:
                preview = gate.preview(self.joints,None,'target','client',now=10)
                with self.assertRaises(PermissionError): gate.confirm(preview['preview_id'],signature,owner,now=now)
            network.assert_not_called()

    def test_float32_boundary_and_forged_command_are_rejected(self):
        self.profile['arm'][4]['limits_rad'] = [-0.3,0.3]
        with self.assertRaises(ValueError): RobotSender(self.profile).prepare(self.joints)
        sender = self.sender
        sender.set_enabled(True)
        values = (9.,0.,0.,0.,0.)
        forged = PreparedCommand(('127.0.0.1',15005),values,pack_packet(values),'mock')
        with patch('hardware.socket.socket') as network:
            with self.assertRaises(ValueError): sender.send(forged,confirmed=True)
            network.assert_not_called()

    def test_real_loopback_binary_and_local_error(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as receiver:
            receiver.bind(('127.0.0.1',0)); receiver.settimeout(1)
            self.profile['port'] = receiver.getsockname()[1]
            sender = RobotSender(self.profile); sender.set_enabled(True)
            command = sender.prepare(self.joints,'closed')
            self.assertEqual(sender.send(command,confirmed=True),24)
            packet,_ = receiver.recvfrom(4096)
            self.assertEqual(packet,command.packet)
            self.assertEqual(unpack_packet(packet)[-1],2500)
        with patch('hardware.socket.socket',side_effect=OSError('local failure')):
            with self.assertRaises(OSError): sender.send(command,confirmed=True)
        self.assertFalse(sender.enabled)

    def test_existing_server_preview_confirmation_to_mock(self):
        # Exercise Unity JSON -> existing IK -> preview -> exact binary packet.
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as receiver:
            receiver.bind(('127.0.0.1',0)); receiver.settimeout(0.2)
            profile = copy.deepcopy(self.profile); profile['port'] = receiver.getsockname()[1]
            import tempfile
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'mock.json'; path.write_text(json.dumps(profile))
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reservation:
                    reservation.bind(('127.0.0.1',0)); port = reservation.getsockname()[1]
                process = subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py')),
                    '--headless','--seconds','15','--port',str(port),
                    '--output-profile',str(path),'--mock-output'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    self.assertIn('Ready UDP',process.stdout.readline())
                    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
                        client.settimeout(3)
                        def request(seq,action='',token='',position=None):
                            client.sendto(json.dumps(dict(v=1,type='target',seq=seq,
                                position=position or [0,-0.22,0.16],action=action,preview_id=token,gripper='closed')).encode(),('127.0.0.1',port))
                            return json.loads(client.recv(8192))
                        state = request(1)
                        self.assertFalse(state['physical_enabled'])
                        self.assertEqual(len(state['preview_links']),21)
                        with self.assertRaises(socket.timeout): receiver.recvfrom(4096)
                        preview = request(2,'preview')
                        self.assertEqual(preview['packet_bytes'],24)
                        with self.assertRaises(socket.timeout): receiver.recvfrom(4096)
                        result = request(3,'confirm',preview['preview_id'])
                        self.assertEqual(result['output_status'],'sent_to_loopback_mock')
                        packet,_ = receiver.recvfrom(4096)
                        self.assertEqual(packet.hex(),preview['packet_hex'])
                        replay = request(4,'confirm',preview['preview_id'])
                        self.assertTrue(replay['output_status'].startswith('rejected:'))
                        newer = request(5,'preview')
                        changed = request(6,'confirm',newer['preview_id'],[0.04,-0.2,0.16])
                        self.assertTrue(changed['output_status'].startswith('rejected:'))
                        with self.assertRaises(socket.timeout): receiver.recvfrom(4096)
                finally:
                    process.terminate(); process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""Binary receiver protocol, calibration validation, and explicit output gates.

No physical transport can be enabled by the current application. Mock transport
is restricted to numeric loopback addresses, with a port distinct from 5005.
"""
from dataclasses import dataclass
import ipaddress
import json
import logging
import math
from pathlib import Path
import secrets
import socket
import struct
import time
import xml.etree.ElementTree as ET

LOG = logging.getLogger('tinyarm.hardware')
JOINTS = tuple(f'j{i}' for i in range(5))
URDF = Path(__file__).resolve().parents[1] / 'tiny_arm_5/tiny_arm_5.urdf'
MODEL_LIMITS = {j.attrib['name']: (float(j.find('limit').attrib['lower']),
                float(j.find('limit').attrib['upper']))
                for j in ET.parse(URDF).getroot().findall('joint') if j.attrib['type'] == 'revolute'}


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected a finite numeric value')
    return float(value)


def pack_packet(joints, gripper=None):
    """Wire format only; caller must separately verify calibration and limits."""
    if len(joints) != 5:
        raise ValueError('Exactly five arm angles required')
    values = [finite(v) for v in joints]
    if gripper is not None:
        values.append(finite(gripper))
    try:
        packet = struct.pack(f'<{len(values)}f', *values)
    except (OverflowError, struct.error) as exc:
        raise ValueError('Value cannot be represented as float32') from exc
    if not all(math.isfinite(v) for v in struct.unpack(f'<{len(values)}f', packet)):
        raise ValueError('Nonfinite float32 value')
    return packet


def unpack_packet(packet):
    if len(packet) not in (20, 24):
        raise ValueError('Expected exactly 20 or 24 bytes, without a header')
    values = struct.unpack(f'<{len(packet)//4}f', packet)
    for value in values:
        finite(value)
    return values


@dataclass(frozen=True)
class PreparedCommand:
    destination: tuple
    values: tuple
    packet: bytes
    profile: str

    def describe(self):
        return dict(destination=f'{self.destination[0]}:{self.destination[1]}',
                    values=list(self.values), packet_bytes=len(self.packet),
                    packet_hex=self.packet.hex(), profile=self.profile)


class RobotSender:
    def __init__(self, config):
        # Isolate a caller's mutable dictionary from an already-reviewed profile.
        self.config = json.loads(json.dumps(config, allow_nan=False))
        self.enabled = False
        self.last_values = None

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    def validate_profile(self):
        c = self.config
        if c.get('kind') not in ('mock', 'physical'):
            raise ValueError('Profile kind must be mock or physical')
        address = ipaddress.ip_address(c['host'])
        port = c['port']
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid UDP port')
        if c['kind'] == 'mock' and (not address.is_loopback or port == 5005):
            raise ValueError('Mock output must use loopback and a non-5005 port')
        if c.get('verified') is not True or not c.get('verification_reference'):
            raise ValueError('Calibration/receiver profile is unverified')
        mapping = c['arm']
        if len(mapping) != 5 or {m['joint'] for m in mapping} != set(JOINTS):
            raise ValueError('Receiver order must contain each of j0..j4 exactly once')
        ids = []
        for m in mapping:
            motor = m['motor_id']
            if type(motor) is not int or motor < 0:
                raise ValueError('Motor ID is not confirmed')
            ids.append(motor)
            if finite(m['sign']) not in (-1, 1):
                raise ValueError('Joint sign must be confirmed as +1 or -1')
            finite(m['offset_rad'])
            lower, upper = map(finite, m['limits_rad'])
            if lower >= upper:
                raise ValueError('Physical coordinate limits must be increasing')
        if len(set(ids)) != 5:
            raise ValueError('Duplicate arm motor ID')
        g = c.get('gripper')
        if g is not None:
            if g.get('verified') is not True or type(g.get('motor_id')) is not int or g['motor_id'] < 0 or g['motor_id'] in ids:
                raise ValueError('Gripper mapping is unverified or conflicts with arm IDs')
            lower, upper = map(finite, g['limits_raw'])
            if lower >= upper:
                raise ValueError('Invalid gripper limits')
            for key in ('open_raw', 'closed_raw'):
                if not lower <= finite(g[key]) <= upper:
                    raise ValueError('Gripper preset outside confirmed limits')
        return c

    def prepare(self, joints, gripper=None):
        LOG.info('PREPARE ATTEMPT profile=%s gripper=%s', self.config.get('kind'), gripper)
        c = self.validate_profile()
        if len(joints) != 5:
            raise ValueError('Expected j0..j4')
        source = dict(zip(JOINTS, map(finite, joints)))
        for name, value in source.items():
            if not MODEL_LIMITS[name][0] <= value <= MODEL_LIMITS[name][1]:
                raise ValueError(f'{name} outside URDF limits')
        values = []
        limits = []
        for m in c['arm']:
            value = m['sign'] * source[m['joint']] + m['offset_rad']
            lower, upper = m['limits_rad']
            if not lower <= value <= upper:
                raise ValueError(f'{m["joint"]} outside calibrated receiver limits')
            values.append(value)
            limits.append((lower, upper))
        if gripper is not None:
            g = c.get('gripper')
            if g is None:
                raise ValueError('Gripper is not configured')
            if isinstance(gripper, str):
                if gripper not in ('open', 'closed'):
                    raise ValueError('Gripper state must be open or closed')
                gripper = g[f'{gripper}_raw']
            value = finite(gripper)
            if not g['limits_raw'][0] <= value <= g['limits_raw'][1]:
                raise ValueError('Gripper outside verified raw limits')
            values.append(value)
            limits.append(g['limits_raw'])
        packet = pack_packet(values[:5], values[5] if len(values) == 6 else None)
        # Quantization must not turn an accepted boundary into an out-of-range command.
        for value, (lower, upper) in zip(unpack_packet(packet), limits):
            if not lower <= value <= upper:
                raise ValueError('Float32 quantization crosses a calibrated limit')
        command = PreparedCommand((c['host'], c['port']), tuple(values), packet, c['kind'])
        LOG.info('PREPARED %s', command.describe())
        return command

    def set_enabled(self, enabled):
        if not enabled:
            self.enabled = False
            return
        try:
            c = self.validate_profile()
            if c['kind'] != 'mock':
                raise PermissionError('Physical transmission is locked in this milestone')
            self.enabled = True
        except Exception:
            self.enabled = False
            LOG.warning('ENABLE REJECTED', exc_info=True)
            raise

    def send(self, command, *, confirmed=False):
        LOG.info('SEND ATTEMPT enabled=%s confirmed=%s', self.enabled, confirmed)
        if not self.enabled or not confirmed:
            raise PermissionError('Output disabled or command not explicitly confirmed')
        c = self.validate_profile()
        if c['kind'] != 'mock' or command.profile != 'mock' or command.destination != (c['host'], c['port']):
            raise PermissionError('Only this profile\'s loopback mock transport is supported')
        if len(command.values) not in (5, 6):
            raise ValueError('Prepared command must contain five or six values')
        if pack_packet(command.values[:5], command.values[5] if len(command.values) == 6 else None) != command.packet:
            raise ValueError('Prepared packet changed')
        # A caller cannot bypass range checks by constructing PreparedCommand directly.
        source = {}
        for mapping, value in zip(c['arm'], command.values[:5]):
            source[mapping['joint']] = (value-mapping['offset_rad'])/mapping['sign']
        rebuilt = self.prepare([source[name] for name in JOINTS],
                               command.values[5] if len(command.values) == 6 else None)
        if rebuilt.packet != command.packet:
            raise ValueError('Prepared command does not match validated calibration')
        try:
            family = socket.AF_INET6 if ipaddress.ip_address(command.destination[0]).version == 6 else socket.AF_INET
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                count = sock.sendto(command.packet, command.destination)
            if count != len(command.packet):
                raise OSError('Incomplete local UDP send')
            LOG.info('SENT TO MOCK ONLY bytes=%s', count)
        except OSError:
            self.enabled = False
            LOG.exception('Local UDP transmission failed; mock output disabled')
            raise
        return count


class PreviewGate:
    """One-use frozen preview bound to target, source endpoint and local time."""
    def __init__(self, sender, ttl=5.0):
        self.sender, self.ttl = sender, ttl
        self.pending = None

    def invalidate(self):
        self.pending = None

    def observe(self, signature, owner, now):
        if self.pending and (self.pending['signature'] != signature or self.pending['owner'] != owner or now >= self.pending['expires']):
            self.invalidate()

    def preview(self, joints, gripper, signature, owner, now=None):
        self.invalidate()
        now = time.monotonic() if now is None else now
        command = self.sender.prepare(joints, gripper)
        token = secrets.token_hex(16)
        self.pending = dict(token=token, command=command, signature=signature,
                            owner=owner, expires=now+self.ttl, model_joints=tuple(joints))
        return dict(preview_id=token, preview_ttl_s=self.ttl, **command.describe())

    def confirm(self, token, signature, owner, *, dry_run=True, now=None):
        now = time.monotonic() if now is None else now
        self.observe(signature, owner, now)
        p = self.pending
        # Consume even a failed confirmation so it cannot be retried/replayed.
        self.invalidate()
        if not p or not secrets.compare_digest(str(token), p['token']):
            raise PermissionError('Missing, expired, changed or already-used preview')
        if dry_run:
            LOG.info('CONFIRMED DRY RUN %s', p['command'].describe())
            return dict(status='confirmed_dry_run_no_transmission', **p['command'].describe())
        self.sender.send(p['command'], confirmed=True)
        return dict(status='sent_to_loopback_mock', **p['command'].describe())

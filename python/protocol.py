"""Versioned local simulation protocol. No physical command transport."""
import json
import math


def decode_target(packet):
    seq, position, _ = decode_pose(packet)
    return seq, position


def decode_pose(packet):
    obj = json.loads(packet)
    if obj.get('v') != 1 or obj.get('type') != 'target':
        raise ValueError('Unsupported message')
    seq = obj['seq']
    if type(seq) is not int or seq < 0 or seq > 2147483647:
        raise ValueError('Invalid sequence')
    p = obj['position']
    if not isinstance(p, list) or len(p) != 3:
        raise ValueError('Invalid position')
    if any(type(x) not in (float, int) or not math.isfinite(x) or abs(x) > 1 for x in p):
        raise ValueError('Invalid coordinates')
    enabled = obj.get('orientation_enabled', True)
    if type(enabled) is not bool:
        raise ValueError('Invalid orientation enable flag')
    orientation = obj.get('orientation') if enabled else None
    if orientation is not None:
        if not isinstance(orientation, list) or len(orientation) != 4:
            raise ValueError('Invalid orientation')
        if any(type(x) not in (float, int) or not math.isfinite(x) or abs(x) > 2 for x in orientation):
            raise ValueError('Invalid quaternion values')
        norm = math.sqrt(sum(x*x for x in orientation))
        if norm < 1e-8:
            raise ValueError('Zero quaternion')
        orientation = [x/norm for x in orientation]
    return seq, p, orientation


def decode_controls(packet):
    """Optional dry-run actions; this protocol has no physical-enable action."""
    obj = json.loads(packet)
    action = obj.get('action', '')
    if action not in ('', 'preview', 'confirm', 'disable'):
        raise ValueError('Unsupported output action')
    gripper = obj.get('gripper') or None
    if gripper not in (None, 'open', 'closed'):
        raise ValueError('Invalid logical gripper state')
    token = obj.get('preview_id', '')
    if not isinstance(token, str) or len(token) > 64:
        raise ValueError('Invalid preview ID')
    return action, gripper, token

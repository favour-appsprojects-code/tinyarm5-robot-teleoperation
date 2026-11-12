"""Versioned local simulation protocol. No physical command transport."""
import json
import math


def decode_target(packet):
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
    return seq, p

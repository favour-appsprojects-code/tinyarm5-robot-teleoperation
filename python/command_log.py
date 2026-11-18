"""Persistent, event-based robot command recording (JSON Lines).

This module never opens a network socket. Every line is a self-contained JSON
object so a crash can lose at most the line being written. Events that matter
for safety review (previews, approvals, execution results, rejections) are
flushed *and* fsynced before the caller continues; the continuous target
stream is sampled so a long session does not produce an unmanageable file.
"""
import datetime
import json
import logging
import math
import os
from pathlib import Path
import time
import uuid

LOG = logging.getLogger('tinyarm.recording')
SCHEMA = 1
JOINT_NAMES = ('j0', 'j1', 'j2', 'j3', 'j4')
DEFAULT_DIR = Path(__file__).resolve().parents[1] / 'logs' / 'robot_commands'

# Events written with fsync. A user approval is never acknowledged in the UI
# before its line is durable on disk.
DURABLE_EVENTS = frozenset({'session_start', 'preview', 'approved', 'execution_result',
                            'rejected', 'preview_cancelled', 'output_disabled',
                            'scene_reset', 'task_completed', 'stream_timeout'})


def new_session_id():
    return datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]


def _floats(values, digits=None):
    if values is None:
        return None
    out = [float(v) for v in values]
    if not all(math.isfinite(v) for v in out):
        raise ValueError('Non-finite value in log entry')
    return [round(v, digits) for v in out] if digits is not None else out


def command_fields(target, orientation, joints, gripper, ik_error_m, orientation_error_deg,
                   reachable, **extra):
    """Common fields for a command-like entry. Joint values are NOT rounded."""
    fields = dict(
        target_position_m=_floats(target, 6),
        target_orientation_wxyz=_floats(orientation, 6),
        joint_names=list(JOINT_NAMES),
        joint_angles_rad=_floats(joints),
        gripper=gripper,
        ik_position_error_m=float(ik_error_m),
        ik_orientation_error_deg=None if orientation_error_deg is None else float(orientation_error_deg),
        validation='reachable_within_model_limits' if reachable else 'unreachable_rejected',
    )
    if fields['joint_angles_rad'] is not None and len(fields['joint_angles_rad']) != 5:
        raise ValueError('Expected exactly five joint angles in j0..j4 order')
    fields.update(extra)
    return fields


class CommandRecorder:
    def __init__(self, directory=None, session_id=None, sample_period_s=0.2,
                 min_move_m=0.002, min_turn_deg=2.0, wall_clock=time.time):
        directory = Path(directory or os.environ.get('TINYARM_LOG_DIR') or DEFAULT_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or new_session_id()
        self.path = directory / f'{self.session_id}.jsonl'
        self.sample_period_s = sample_period_s
        self.min_move_m = min_move_m
        self.min_turn_deg = min_turn_deg
        self.wall_clock = wall_clock
        self.sequence = 0
        self.counts = {}
        self.error = None
        self._last_sample = None
        self._file = open(self.path, 'a', encoding='utf-8', newline='\n')

    def record(self, event, durable=None, **fields):
        """Append one entry. Returns the entry, or None if it could not be stored."""
        durable = event in DURABLE_EVENTS if durable is None else durable
        self.sequence += 1
        now = self.wall_clock()
        entry = dict(schema=SCHEMA,
                     timestamp=datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat(timespec='milliseconds'),
                     unix_time=round(now, 4), session_id=self.session_id,
                     sequence=self.sequence, event=event, **fields)
        try:
            line = json.dumps(entry, allow_nan=False, separators=(',', ':'))
            self._file.write(line + '\n')
            self._file.flush()
            if durable:
                os.fsync(self._file.fileno())
        except (OSError, ValueError, TypeError) as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            LOG.error('RECORDING FAILED for %s #%s: %s', event, self.sequence, self.error)
            return None
        self.counts[event] = self.counts.get(event, 0) + 1
        return entry

    def should_sample(self, now, target, orientation, gripper, reachable):
        """Rate-limited, change-based sampling of the live target stream."""
        state = (now, tuple(float(v) for v in target),
                 None if orientation is None else tuple(float(v) for v in orientation),
                 gripper, bool(reachable))
        last = self._last_sample
        if last is not None:
            if now - last[0] < self.sample_period_s:
                return False
            moved = math.dist(state[1], last[1]) >= self.min_move_m
            turned = False
            if (state[2] is None) != (last[2] is None):
                turned = True
            elif state[2] is not None:
                dot = min(1.0, abs(sum(a*b for a, b in zip(state[2], last[2]))))
                turned = math.degrees(2*math.acos(dot)) >= self.min_turn_deg
            if not (moved or turned or state[3] != last[3] or state[4] != last[4]):
                return False
        self._last_sample = state
        return True

    @property
    def total(self):
        return sum(self.counts.values())

    def close(self):
        try:
            self._file.flush()
            os.fsync(self._file.fileno())
        except (OSError, ValueError):
            pass
        self._file.close()


def read_log(path):
    """Read a JSONL log, skipping (and reporting) a truncated trailing line."""
    entries, bad = [], 0
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    if bad:
        LOG.warning('%s: skipped %d unreadable line(s)', path, bad)
    return entries

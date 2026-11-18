"""Export recorded commands (JSONL) to CSV for analysis. Never transmits.

Default: only user-approved commands. --events preview approved ... to choose,
or --all for every event. Joint angles are written unrounded, in j0..j4 order.
"""
import argparse
import csv
from pathlib import Path
import sys
from command_log import read_log

COLUMNS = ['timestamp', 'session_id', 'sequence', 'event', 'preview_id',
           'target_x_m', 'target_y_m', 'target_z_m',
           'target_qw', 'target_qx', 'target_qy', 'target_qz',
           'j0_rad', 'j1_rad', 'j2_rad', 'j3_rad', 'j4_rad',
           'gripper', 'gripper_raw', 'ik_position_error_mm', 'ik_orientation_error_deg',
           'validation', 'execution_status', 'transmission_attempted', 'destination',
           'transmission_outcome', 'delivery_confirmed', 'packet_hex']


def row(entry):
    out = {k: entry.get(k) for k in COLUMNS if k in entry}
    for axis, value in zip('xyz', entry.get('target_position_m') or []):
        out[f'target_{axis}_m'] = value
    for axis, value in zip('wxyz', entry.get('target_orientation_wxyz') or []):
        out[f'target_q{axis}'] = value
    for i, value in enumerate(entry.get('joint_angles_rad') or []):
        out[f'j{i}_rad'] = repr(float(value))
    if entry.get('ik_position_error_m') is not None:
        out['ik_position_error_mm'] = round(entry['ik_position_error_m']*1000, 4)
    return out


def export(source, destination, events=('approved',), include_all=False):
    entries = read_log(source)
    selected = [e for e in entries if include_all or e.get('event') in events]
    with open(destination, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for entry in selected:
            writer.writerow(row(entry))
    return len(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', help='logs/robot_commands/<session>.jsonl')
    parser.add_argument('-o', '--output', help='CSV path (default: next to the log)')
    parser.add_argument('--events', nargs='+', default=['approved'])
    parser.add_argument('--all', action='store_true')
    args = parser.parse_args()
    source = Path(args.log)
    suffix = 'all' if args.all else '-'.join(args.events)
    destination = Path(args.output) if args.output else source.with_name(f'{source.stem}.{suffix}.csv')
    count = export(source, destination, tuple(args.events), args.all)
    print(f'Wrote {count} row(s) to {destination}')
    return 0 if count else 1


if __name__ == '__main__':
    sys.exit(main())

"""Robot receiver availability, without ever sending a packet to the receiver.

The TA receiver protocol (header-free float32 joints on UDP 5005) has no
status or acknowledgement message. Any 20/24-byte datagram is a motion command
and a malformed one may crash the receiver, so this module NEVER probes UDP
5005. It reports host-level reachability (ICMP and, optionally, TCP ports the
receiver laptop is known to expose) and keeps delivery explicitly unverified.

States:
  physical_disabled                     physical output locked (network info still shown)
  receiver_unavailable                  host did not answer
  network_reachable_delivery_unverified host answers; UDP delivery/execution unknown
  receiver_confirmed                    reserved for a receiver that implements an ack
  unknown                               no probe result yet / probe unavailable
"""
import logging
import platform
import socket
import subprocess
import threading
import time

LOG = logging.getLogger('tinyarm.receiver')


def icmp_ping(host, timeout_s=0.8):
    """True/False when ping ran, None when ping is unavailable here."""
    windows = platform.system().lower().startswith('win')
    command = (['ping', '-n', '1', '-w', str(int(timeout_s*1000)), host] if windows
               else ['ping', '-c', '1', '-W', str(max(1, round(timeout_s))), host])
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout_s + 2, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return ping_succeeded(result.returncode, result.stdout, windows)


def ping_succeeded(returncode, stdout, windows):
    # Windows ping exits 0 for "Destination host unreachable" sent by a router;
    # only a TTL-bearing reply proves the host itself answered.
    if returncode != 0:
        return False
    return 'ttl=' in stdout.lower() if windows else True


def tcp_probe(host, ports, timeout_s=0.5):
    """A completed or *refused* TCP connection both prove the host is up."""
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                return True
        except ConnectionRefusedError:
            return True
        except OSError:
            continue
    return False if ports else None


class ReceiverMonitor:
    def __init__(self, host, port, physical_enabled=False, probe=None, interval_s=2.0,
                 tcp_ports=(), ack_supported=False, clock=time.monotonic):
        self.host, self.port = host, port
        self.physical_enabled = physical_enabled
        self.ack_supported = ack_supported
        self.interval_s = interval_s
        self.clock = clock
        self._probe = probe or (lambda h: self._default_probe(h, tuple(tcp_ports)))
        self._lock = threading.Lock()
        self._network = 'unknown'
        self._checked = None
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _default_probe(host, tcp_ports):
        result = icmp_ping(host)
        if result:
            return True
        tcp = tcp_probe(host, tcp_ports)
        if tcp:
            return True
        return False if (result is False or tcp is False) else None

    def poll_once(self):
        try:
            result = self._probe(self.host)
        except Exception:  # A broken probe must never stop teleoperation.
            LOG.exception('Receiver probe failed')
            result = None
        with self._lock:
            previous = self._network
            self._network = 'unknown' if result is None else 'reachable' if result else 'unreachable'
            self._checked = self.clock()
        if previous != self._network:
            LOG.info('Receiver %s:%s network %s -> %s (UDP delivery remains unverified)',
                     self.host, self.port, previous, self._network)
        return self.snapshot()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='receiver-monitor', daemon=True)
            self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.interval_s)

    def stop(self):
        self._stop.set()

    def snapshot(self):
        with self._lock:
            network, checked = self._network, self._checked
        if not self.physical_enabled:
            state = 'physical_disabled'
        elif network == 'unreachable':
            state = 'receiver_unavailable'
        elif network == 'reachable':
            state = 'receiver_confirmed' if self.ack_supported else 'network_reachable_delivery_unverified'
        else:
            state = 'unknown'
        delivery = 'acknowledged' if state == 'receiver_confirmed' else 'unverified'
        network_text = {'reachable': 'receiver host reachable, UDP delivery unverified',
                        'unreachable': 'receiver host unavailable',
                        'unknown': 'receiver reachability unknown'}[network]
        prefix = 'Physical output disabled; ' if not self.physical_enabled else ''
        return dict(receiver=f'{self.host}:{self.port}', receiver_state=state,
                    receiver_network=network, receiver_delivery=delivery,
                    receiver_summary=prefix + network_text,
                    receiver_checked_age_s=None if checked is None else round(self.clock()-checked, 1))

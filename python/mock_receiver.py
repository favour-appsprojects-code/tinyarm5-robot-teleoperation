"""Local binary protocol diagnostic; never connects to hardware."""
import argparse
import ipaddress
import json
import socket
from hardware import unpack_packet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=15005)
    parser.add_argument('--count', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=15)
    args = parser.parse_args()
    if not ipaddress.ip_address(args.host).is_loopback or args.port == 5005:
        parser.error('Mock receiver requires loopback and a port other than 5005')
    family = socket.AF_INET6 if ipaddress.ip_address(args.host).version == 6 else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.bind((args.host, args.port))
        sock.settimeout(args.timeout)
        print(f'MOCK ONLY listening {args.host}:{args.port}', flush=True)
        for _ in range(args.count):
            packet, source = sock.recvfrom(4096)
            try:
                values = unpack_packet(packet)
                print(json.dumps(dict(source=source, bytes=len(packet), values=values,
                                      packet_hex=packet.hex())), flush=True)
            except ValueError as exc:
                print(f'REJECTED: {exc}', flush=True)


if __name__ == '__main__':
    main()

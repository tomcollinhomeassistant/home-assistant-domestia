"""UDP Domestia: commandes + lecture d'état (push + poll) avec auto-découverte et sockets fiables."""

from __future__ import annotations

import errno
import logging
import socket
import threading
import time
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Commande 9C (156) : Lit l'état des Relais + Dimmers + Volets
READ_CMD = bytes([0xFF, 0x00, 0x00, 0x01, 0x9C, 0x9C])
ATRRELAIS_HEADER_PREFIX = (0xFF, 0x00)
ATRRELAIS_VALUES_OFFSET = 3
MAX_OUTPUTS = 192


def _checksum(payload_list: list[int]) -> int:
    return sum(payload_list[4:]) & 0xFF


def build_relay_payload(output_id: int, on: bool) -> bytes:
    header = [0xFF, 0x00, 0x00, 0x02]
    cmd = 0x0E if on else 0x0F
    payload = header + [cmd, int(output_id)]
    payload.append(_checksum(payload))
    return bytes(payload)


def build_dimmer_payload(output_id: int, level_0_64: int) -> bytes:
    header = [0xFF, 0x00, 0x00, 0x03]
    level = max(0, min(64, int(level_0_64)))
    payload = header + [0x10, int(output_id), level]
    payload.append(_checksum(payload))
    return bytes(payload)


def _is_state_frame(data: bytes) -> bool:
    if not data:
        return False
    if len(data) < (ATRRELAIS_VALUES_OFFSET + 60):
        return False
    if (data[0], data[1]) != ATRRELAIS_HEADER_PREFIX:
        return False
    return True


class DomestiaUDPClient:
    def __init__(self, host: str, port: int, timeout: float = 2.5) -> None:
        self._host = str(host)
        self._port = int(port)
        self._timeout = float(timeout)
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Port éphémère (0) pour éviter les collisions
        self._sock.bind(("0.0.0.0", 0))
        self._sock.settimeout(self._timeout)

        self._last_state: Optional[bytes] = None
        self._last_state_ts: float = 0.0

    def close(self) -> None:
        with self._lock:
            try:
                self._sock.close()
            except OSError:
                pass

    def send_only(self, payload: bytes) -> None:
        with self._lock:
            try:
                self._sock.sendto(payload, (self._host, self._port))
            except OSError as e:
                _LOGGER.error("Erreur envoi UDP: %s", e)

    def _recv_one(self, timeout: float) -> Optional[bytes]:
        old_timeout = self._sock.gettimeout()
        try:
            self._sock.settimeout(timeout)
            data, addr = self._sock.recvfrom(4096)

            # Filtre simple: on n'accepte que les paquets venant du contrôleur attendu
            if addr and addr[0] != self._host:
                return None

            return data
        except (socket.timeout, BlockingIOError):
            return None
        except OSError as e:
            err_code = getattr(e, "errno", None)
            if err_code in (errno.EAGAIN, errno.EWOULDBLOCK, 11):
                return None
            return None
        finally:
            try:
                self._sock.settimeout(old_timeout)
            except OSError:
                pass

    def _drain_push_frames(self, max_packets: int = 10) -> None:
        for _ in range(max_packets):
            data = self._recv_one(timeout=0.01)
            if not data:
                return
            if _is_state_frame(data):
                self._last_state = data
                self._last_state_ts = time.time()

    def read_states(self) -> Optional[bytes]:
        with self._lock:
            self._drain_push_frames()

            if self._last_state and (time.time() - self._last_state_ts) < 2.0:
                return self._last_state

            try:
                self._sock.sendto(READ_CMD, (self._host, self._port))
            except OSError:
                return self._last_state

            data = self._recv_one(timeout=self._timeout)

            if data and _is_state_frame(data):
                self._last_state = data
                self._last_state_ts = time.time()
                return data

            self._drain_push_frames()
            return self._last_state


_CLIENTS: dict[tuple[str, int], DomestiaUDPClient] = {}
_CLIENTS_LOCK = threading.Lock()


def _get_client(host: str, port: int, timeout: float = 2.5) -> DomestiaUDPClient:
    key = (str(host), int(port))
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = DomestiaUDPClient(host=host, port=port, timeout=timeout)
            _CLIENTS[key] = client
        return client


def send_udp_command(host: str, port: int, payload: bytes, timeout: float = 2.5) -> None:
    client = _get_client(host, port, timeout)
    client.send_only(payload)


def get_output_value(frame: bytes, output_id: int) -> int:
    if not frame:
        return 0
    oid = int(output_id)
    if oid < 1 or oid > MAX_OUTPUTS:
        return 0
    idx = ATRRELAIS_VALUES_OFFSET + (oid - 1)
    if idx >= len(frame):
        return 0
    return int(frame[idx])


# ==========================================
# PARTIE AUTO-DÉCOUVERTE
# ==========================================

def _get_hardware_types(host: str, port: int) -> list[int] | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(2.0)
    try:
        payload = [0xFF, 0x00, 0x00, 0x01, 0x42]
        payload.append(_checksum(payload))
        sock.sendto(bytes(payload), (host, port))
        data, _ = sock.recvfrom(1024)
        if data and len(data) >= 196 and data[0] == 0xFF and data[3] == 0xC0:
            return list(data[4:4 + 192])
    except Exception:
        pass
    finally:
        sock.close()
    return None


def _get_output_name(sock: socket.socket, host: str, port: int, output_id: int) -> str:
    payload = [0xFF, 0x00, 0x00, 0x02, 0x3E, output_id]
    payload.append(_checksum(payload))
    try:
        sock.sendto(bytes(payload), (host, port))
        data, _ = sock.recvfrom(1024)
        if data and len(data) >= 5 and data[0] == 0xFF:
            length = data[3]
            if length > 0 and len(data) >= 4 + length:
                return (
                    data[4:4 + length]
                    .replace(b"\x00", b"")
                    .decode("latin-1")
                    .strip()
                )
    except Exception:
        pass
    return f"Sortie {output_id}"


def discover_domestia_devices(host: str, port: int) -> dict[int, dict]:
    types = _get_hardware_types(host, port)
    if not types:
        _LOGGER.error("Impossible de récupérer les types de modules Domestia.")
        return {}

    discovered: dict[int, dict] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(0.3)

    try:
        for output_id in range(1, MAX_OUTPUTS + 1):
            hw_type = types[output_id - 1]

            # TYPES : 0=Relais, 6=Dimmer, 1 et 2 = Volets (supposé)
            if hw_type in (0, 6, 1, 2):
                name = _get_output_name(sock, host, port, output_id)
                if name:
                    if name.lower() == "vide":
                        name = f"Réserve {output_id}"
                    discovered[output_id] = {"type": hw_type, "name": name}
    finally:
        sock.close()

    return discovered
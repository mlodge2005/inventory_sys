"""Local address discovery for LAN and Tailscale URLs.

The default route is intentionally ignored. A reachable inventory URL is chosen
from interface addresses, an operator override, or an explicit flag.
"""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from dataclasses import dataclass

from app.core.errors import InventoryError


@dataclass(frozen=True)
class HostAddress:
    interface: str
    ip: str
    kind: str  # ethernet, wifi, hotspot, tailscale, other

    def url(self, port: int) -> str:
        return f"http://{self.ip}:{port}"


_IFACE_RE = re.compile(r"^\d+:\s+([^:]+):")
_INET_RE = re.compile(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/")


def classify_interface(name: str, ip: str) -> str | None:
    """Return an address kind, or None when the address should not be advertised."""

    iface = name.lower().split("@", 1)[0]
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if parsed.version != 4 or parsed.is_loopback or parsed.is_multicast or parsed.is_unspecified:
        return None
    if iface == "lo" or iface.startswith(
        ("docker", "br-", "veth", "virbr", "vnet", "kube", "cni", "flannel", "podman", "zt")
    ):
        return None
    if iface.startswith("tailscale"):
        return "tailscale"
    if iface.startswith(("tun", "tap", "wg", "ppp", "ipsec", "vpn")):
        return None
    if ip in {"10.42.0.1", "192.168.4.1"} or iface in {"ap0", "wlan_ap"}:
        return "hotspot"
    if iface.startswith(("eth", "en", "usb")):
        return "ethernet"
    if iface.startswith(("wlan", "wl", "wifi")):
        return "wifi"
    if parsed.is_link_local:
        return None
    return "other"


def parse_ip_addr_json(payload: list) -> list[HostAddress]:
    found: list[HostAddress] = []
    for iface in payload:
        name = str(iface.get("ifname") or "")
        for addr in iface.get("addr_info") or []:
            if addr.get("family") != "inet":
                continue
            ip = addr.get("local")
            if not ip:
                continue
            kind = classify_interface(name, ip)
            if kind:
                found.append(HostAddress(name, ip, kind))
    return _dedupe(found)


def parse_ip_addr_text(text: str) -> list[HostAddress]:
    found: list[HostAddress] = []
    current = ""
    for line in text.splitlines():
        match = _IFACE_RE.match(line)
        if match:
            current = match.group(1)
            continue
        inet = _INET_RE.search(line)
        if inet and current:
            kind = classify_interface(current, inet.group(1))
            if kind:
                found.append(HostAddress(current, inet.group(1), kind))
    return _dedupe(found)


def detect_addresses() -> list[HostAddress]:
    try:
        completed = subprocess.run(
            ["ip", "-4", "-j", "addr", "show"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        payload = json.loads(completed.stdout or "[]")
        if isinstance(payload, list):
            return parse_ip_addr_json(payload)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass
    try:
        completed = subprocess.run(
            ["ip", "-4", "addr", "show"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return parse_ip_addr_text(completed.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return []


def exposure_warnings(bind_host: str, addresses: list[HostAddress]) -> list[str]:
    warnings: list[str] = []
    if bind_host in {"0.0.0.0", "::", "::0"}:
        warnings.append(
            "The server listens on all interfaces. Do not forward this port from your router "
            "and do not enable Tailscale Funnel."
        )
        public = []
        for address in addresses:
            if address.kind == "tailscale":
                continue
            ip = ipaddress.ip_address(address.ip)
            if ip.is_global:
                public.append(f"{address.interface} {address.ip}")
        if public:
            warnings.append(
                "A public address is configured on this host, so 0.0.0.0 may expose the app "
                "beyond a trusted LAN: " + ", ".join(public)
            )
    return warnings


def select_public_url(
    *,
    port: int,
    addresses: list[HostAddress],
    explicit: str | None = None,
    env_url: str | None = None,
    settings_url: str | None = None,
    index: int | None = None,
    interactive: bool = False,
    input_fn=None,
) -> tuple[str, list[str]]:
    """Pick one URL and return it with every candidate.

    Priority is an explicit flag, then the environment override, then the saved
    setting, then a numbered choice, then a single detected address, then an
    interactive prompt, then the first LAN address.
    """

    candidates = [address.url(port) for address in addresses]
    for raw in (explicit, env_url, settings_url):
        if raw and raw.strip():
            return _validate_url(raw.strip()), candidates
    if index is not None:
        if index < 1 or index > len(candidates):
            raise InventoryError(
                "validation_error",
                f"Address index must be between 1 and {len(candidates) or 0}.",
                422,
            )
        return candidates[index - 1], candidates
    if len(candidates) == 1:
        return candidates[0], candidates
    if len(candidates) == 0:
        raise InventoryError(
            "not_found",
            "No LAN or Tailscale address was detected. Set INVENTORY_PUBLIC_URL.",
            404,
        )
    if interactive and input_fn is not None:
        choice = input_fn(_prompt(addresses, port))
        text = (choice or "").strip()
        if text == "":
            return _preferred_candidate(addresses, port), candidates
        if text.isdigit() and 1 <= int(text) <= len(candidates):
            return candidates[int(text) - 1], candidates
        raise InventoryError("validation_error", "Choose one of the listed addresses.", 422)
    return _preferred_candidate(addresses, port), candidates


def _preferred_candidate(addresses: list[HostAddress], port: int) -> str:
    for kind in ("ethernet", "wifi", "hotspot", "tailscale", "other"):
        for address in addresses:
            if address.kind == kind:
                return address.url(port)
    return addresses[0].url(port)


def _prompt(addresses: list[HostAddress], port: int) -> str:
    lines = ["Multiple addresses detected:"]
    for number, address in enumerate(addresses, start=1):
        lines.append(f"  {number}. {address.kind} {address.interface} {address.url(port)}")
    lines.append("Select a number (press Enter for the first LAN address):")
    return "\n".join(lines)


def _validate_url(value: str) -> str:
    if not (value.startswith("http://") or value.startswith("https://")) or any(ch.isspace() for ch in value):
        raise InventoryError("validation_error", "Public URL must be an http or https URL.", 422)
    return value


def _dedupe(addresses: list[HostAddress]) -> list[HostAddress]:
    seen: set[tuple[str, str]] = set()
    unique: list[HostAddress] = []
    for address in addresses:
        key = (address.interface, address.ip)
        if key in seen:
            continue
        seen.add(key)
        unique.append(address)
    return unique

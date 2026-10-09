"""
ONVIF Core Communication Engine
- Multi-NIC WS-Discovery (RFC/OASIS standard over UDP Multicast 239.255.255.250:3702)
- SOAP 1.2 Request / Response handling
- Clock synchronization with GetSystemDateAndTime
- Device information, Capabilities, Profiles (S/G/T), Stream & Snapshot URI resolution
"""

import asyncio
import logging
import socket
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import httpx

from .onvif_auth import generate_ws_security_header

logger = logging.getLogger("aegis.onvif")

def _strip_ns(tag: str) -> str:
    """Helper to remove namespace prefix from XML tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def get_active_ipv4_interfaces() -> List[Dict[str, str]]:
    """
    Enumerates all active, non-loopback network interfaces with their IPv4 addresses.
    Uses socket probing and /proc/net/dev or system tools.
    """
    interfaces = []
    try:
        import ifaddr
        adapters = ifaddr.get_adapters()
        for adapter in adapters:
            for ip in adapter.ips:
                if isinstance(ip.ip, str) and not ip.ip.startswith("127.") and ":" not in ip.ip:
                    interfaces.append({
                        "name": adapter.name,
                        "ip": ip.ip,
                        "nice_name": adapter.nice_name or adapter.name
                    })
    except Exception:
        # Fallback using socket hostname
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            if local_ip and not local_ip.startswith("127."):
                interfaces.append({"name": "default", "ip": local_ip, "nice_name": "Default Interface"})
        except Exception:
            pass

    return interfaces


def build_soap_envelope(body_content: str, header_content: str = "") -> str:
    """Builds a standard SOAP 1.2 Envelope."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
               xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
               xmlns:tt="http://www.onvif.org/ver10/schema"
               xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Header>
    {header_content}
  </soap:Header>
  <soap:Body>
    {body_content}
  </soap:Body>
</soap:Envelope>""".strip()


class ONVIFClient:
    """
    Robust ONVIF Client for real IP cameras.
    Handles device date/time sync, WS-Security digest auth,
    capabilities, profiles (S/G/T), stream and snapshot URIs.
    """

    def __init__(self, xaddr: str, username: str = "", password: str = "", timeout: float = 6.0):
        self.device_xaddr = xaddr.strip()
        self.username = username.strip()
        self.password = password.strip()
        self.timeout = timeout
        self.time_offset_seconds: float = 0.0
        self.media_xaddr: Optional[str] = None
        self.device_info: Dict[str, str] = {}
        self.profiles: List[Dict[str, Any]] = []

    async def _send_soap_request(self, service_url: str, action: str, body_xml: str, authenticated: bool = True) -> ET.Element:
        """Sends a SOAP request over HTTP POST and returns root ElementTree."""
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8; action=\"\""
        }

        header_xml = ""
        if authenticated and self.username:
            wsse_header, _, _ = generate_ws_security_header(
                self.username, self.password, self.time_offset_seconds
            )
            header_xml = wsse_header

        envelope_xml = build_soap_envelope(body_xml, header_xml)

        async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
            resp = await client.post(service_url, content=envelope_xml.encode("utf-8"), headers=headers)
            if resp.status_code not in (200, 400, 500):
                resp.raise_for_status()
            
            # Parse XML response
            try:
                root = ET.fromstring(resp.text)
                return root
            except ET.ParseError as e:
                raise ValueError(f"Failed to parse SOAP XML response: {e}")

    async def sync_time(self) -> float:
        """
        Calls GetSystemDateAndTime without authentication.
        Calculates time offset between camera clock and client clock:
        Δt = t_camera - t_client
        """
        body = "<tds:GetSystemDateAndTime/>"
        try:
            root = await self._send_soap_request(self.device_xaddr, "GetSystemDateAndTime", body, authenticated=False)
            
            # Search for UTCDateTime or LocalDateTime
            year, month, day, hour, minute, second = None, None, None, None, None, None
            for elem in root.iter():
                tag = _strip_ns(elem.tag)
                if tag == "Year":
                    year = int(elem.text.strip())
                elif tag == "Month":
                    month = int(elem.text.strip())
                elif tag == "Day":
                    day = int(elem.text.strip())
                elif tag == "Hour":
                    hour = int(elem.text.strip())
                elif tag == "Minute":
                    minute = int(elem.text.strip())
                elif tag == "Second":
                    second = int(elem.text.strip())

            if all(v is not None for v in [year, month, day, hour, minute, second]):
                camera_dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
                client_dt = datetime.now(timezone.utc)
                self.time_offset_seconds = (camera_dt - client_dt).total_seconds()
                return self.time_offset_seconds
        except Exception as e:
            # Fallback to zero offset if camera does not return clock
            self.time_offset_seconds = 0.0
            
        return self.time_offset_seconds

    async def get_device_information(self) -> Dict[str, str]:
        """Fetches Manufacturer, Model, FirmwareVersion, SerialNumber, HardwareId."""
        body = "<tds:GetDeviceInformation/>"
        root = await self._send_soap_request(self.device_xaddr, "GetDeviceInformation", body, authenticated=True)

        info = {
            "manufacturer": "Generic ONVIF",
            "model": "IP Camera",
            "firmware_version": "Unknown",
            "serial_number": "Unknown",
            "hardware_id": "Unknown"
        }

        for elem in root.iter():
            tag = _strip_ns(elem.tag)
            text = (elem.text or "").strip()
            if tag == "Manufacturer" and text:
                info["manufacturer"] = text
            elif tag == "Model" and text:
                info["model"] = text
            elif tag == "FirmwareVersion" and text:
                info["firmware_version"] = text
            elif tag == "SerialNumber" and text:
                info["serial_number"] = text
            elif tag == "HardwareId" and text:
                info["hardware_id"] = text

        self.device_info = info
        return info

    async def get_capabilities(self) -> Dict[str, str]:
        """Discovers MediaService, PTZ, Events, Analytics URLs."""
        body = "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>"
        root = await self._send_soap_request(self.device_xaddr, "GetCapabilities", body, authenticated=True)

        caps = {}
        for elem in root.iter():
            tag = _strip_ns(elem.tag)
            if tag == "Media":
                for child in elem.iter():
                    if _strip_ns(child.tag) == "XAddr" and child.text:
                        caps["media"] = child.text.strip()
            elif tag == "PTZ":
                for child in elem.iter():
                    if _strip_ns(child.tag) == "XAddr" and child.text:
                        caps["ptz"] = child.text.strip()
            elif tag == "Events":
                for child in elem.iter():
                    if _strip_ns(child.tag) == "XAddr" and child.text:
                        caps["events"] = child.text.strip()

        # If Media XAddr was found, cache it. Otherwise fallback to device_xaddr
        self.media_xaddr = caps.get("media", self.device_xaddr)
        return caps

    async def get_profiles(self) -> List[Dict[str, Any]]:
        """
        Discovers media profiles, video encoder configurations,
        Profile S, Profile T, Profile G tags, resolution, and fps.
        """
        media_url = self.media_xaddr or self.device_xaddr
        body = "<trt:GetProfiles/>"
        root = await self._send_soap_request(media_url, "GetProfiles", body, authenticated=True)

        profiles = []
        for elem in root.iter():
            if _strip_ns(elem.tag) == "Profiles":
                token = elem.attrib.get("token", "")
                name = ""
                width = 1920
                height = 1080
                framerate = 25
                encoding = "H264"

                for child in elem.iter():
                    ctag = _strip_ns(child.tag)
                    if ctag == "Name" and not name:
                        name = (child.text or "").strip()
                    elif ctag == "Encoding":
                        encoding = (child.text or "").strip().upper()
                    elif ctag == "Width":
                        try:
                            width = int(child.text.strip())
                        except Exception:
                            pass
                    elif ctag == "Height":
                        try:
                            height = int(child.text.strip())
                        except Exception:
                            pass
                    elif ctag == "FrameRateLimit":
                        try:
                            framerate = int(float(child.text.strip()))
                        except Exception:
                            pass

                if token:
                    profiles.append({
                        "token": token,
                        "name": name or f"Profile_{token}",
                        "encoding": encoding,
                        "width": width,
                        "height": height,
                        "framerate": framerate
                    })

        self.profiles = profiles
        return profiles

    async def get_stream_uri(self, profile_token: str) -> Optional[str]:
        """Fetches RTSP live stream URI for the given profile token."""
        media_url = self.media_xaddr or self.device_xaddr
        body = f"""
        <trt:GetStreamUri>
          <trt:StreamSetup>
            <tt:Stream>RTP-Unicast</tt:Stream>
            <tt:Transport>
              <tt:Protocol>RTSP</tt:Protocol>
            </tt:Transport>
          </trt:StreamSetup>
          <trt:ProfileToken>{profile_token}</trt:ProfileToken>
        </trt:GetStreamUri>"""
        
        try:
            root = await self._send_soap_request(media_url, "GetStreamUri", body, authenticated=True)
            for elem in root.iter():
                if _strip_ns(elem.tag) == "Uri" and elem.text:
                    uri = elem.text.strip()
                    # Inject credentials into RTSP URI if present and not already embedded
                    if self.username and self.password and "@" not in uri and uri.startswith("rtsp://"):
                        safe_user = urllib.parse.quote(self.username)
                        safe_pass = urllib.parse.quote(self.password)
                        uri = f"rtsp://{safe_user}:{safe_pass}@{uri[7:]}"
                    return uri
        except Exception as e:
            logger.warning(f"Failed GetStreamUri: {e}")
        return None

    async def get_snapshot_uri(self, profile_token: str) -> Optional[str]:
        """Fetches HTTP snapshot URI for the given profile token."""
        media_url = self.media_xaddr or self.device_xaddr
        body = f"""
        <trt:GetSnapshotUri>
          <trt:ProfileToken>{profile_token}</trt:ProfileToken>
        </trt:GetSnapshotUri>"""

        try:
            root = await self._send_soap_request(media_url, "GetSnapshotUri", body, authenticated=True)
            for elem in root.iter():
                if _strip_ns(elem.tag) == "Uri" and elem.text:
                    return elem.text.strip()
        except Exception as e:
            # Not all cameras support HTTP snapshot endpoint (some are RTSP-only)
            pass
        return None


def parse_scopes(scopes_str: str) -> Dict[str, Any]:
    """Parses ONVIF Scopes string into structured metadata."""
    metadata = {
        "name": "",
        "hardware": "",
        "location": "",
        "profiles": []
    }
    
    parts = scopes_str.split()
    for part in parts:
        part = urllib.parse.unquote(part)
        lower = part.lower()
        if "/name/" in lower:
            metadata["name"] = part.split("/name/", 1)[1]
        elif "/hardware/" in lower:
            metadata["hardware"] = part.split("/hardware/", 1)[1]
        elif "/location/" in lower:
            metadata["location"] = part.split("/location/", 1)[1]
        elif "profile/streaming" in lower or "profile/s" in lower:
            if "Profile S" not in metadata["profiles"]:
                metadata["profiles"].append("Profile S")
        elif "profile/g" in lower:
            if "Profile G" not in metadata["profiles"]:
                metadata["profiles"].append("Profile G")
        elif "profile/t" in lower:
            if "Profile T" not in metadata["profiles"]:
                metadata["profiles"].append("Profile T")

    return metadata


def parse_probe_matches_xml(xml_content: str) -> List[Dict[str, Any]]:
    """Parses a WS-Discovery ProbeMatches SOAP XML string."""
    devices = []
    try:
        root = ET.fromstring(xml_content)
    except Exception:
        return devices

    for pm in root.iter():
        if _strip_ns(pm.tag) == "ProbeMatch":
            dev = {
                "uuid": "",
                "xaddrs": [],
                "scopes": "",
                "types": "",
                "name": "",
                "hardware": "",
                "location": "",
                "profiles": ["Profile S"] # Default assumption for video devices
            }
            for child in pm.iter():
                ctag = _strip_ns(child.tag)
                text = (child.text or "").strip()
                if ctag == "Address" and text.startswith("urn:uuid:"):
                    dev["uuid"] = text
                elif ctag == "XAddrs" and text:
                    dev["xaddrs"] = text.split()
                elif ctag == "Types" and text:
                    dev["types"] = text
                elif ctag == "Scopes" and text:
                    dev["scopes"] = text
                    parsed_sc = parse_scopes(text)
                    if parsed_sc["name"]:
                        dev["name"] = parsed_sc["name"]
                    if parsed_sc["hardware"]:
                        dev["hardware"] = parsed_sc["hardware"]
                    if parsed_sc["location"]:
                        dev["location"] = parsed_sc["location"]
                    if parsed_sc["profiles"]:
                        dev["profiles"] = list(set(dev["profiles"] + parsed_sc["profiles"]))

            if dev["xaddrs"]:
                devices.append(dev)

    return devices


async def run_multi_nic_ws_discovery(timeout: float = 3.0) -> List[Dict[str, Any]]:
    """
    Executes standard WS-Discovery UDP multicast scan across all active physical network interfaces.
    Sends standard probe packets to 239.255.255.250:3702 and captures all ProbeMatch responses.
    """
    interfaces = get_active_ipv4_interfaces()
    if not interfaces:
        interfaces = [{"name": "default", "ip": "0.0.0.0", "nice_name": "Default"}]

    discovered_devices: Dict[str, Dict[str, Any]] = {}
    loop = asyncio.get_running_loop()

    # SOAP WS-Discovery Probe Templates
    message_uuid = str(uuid.uuid4())
    probe_xml_network = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
               xmlns:tns="http://schemas.xmlsoap.org/ws/2005/04/discovery"
               xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <soap:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
    <wsa:MessageID>urn:uuid:{message_uuid}</wsa:MessageID>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
  </soap:Header>
  <soap:Body>
    <tns:Probe>
      <tns:Types>dn:NetworkVideoTransmitter</tns:Types>
    </tns:Probe>
  </soap:Body>
</soap:Envelope>""".encode("utf-8")

    probe_xml_device = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
               xmlns:tns="http://schemas.xmlsoap.org/ws/2005/04/discovery"
               xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  <soap:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
    <wsa:MessageID>urn:uuid:{uuid.uuid4()}</wsa:MessageID>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
  </soap:Header>
  <soap:Body>
    <tns:Probe>
      <tns:Types>tds:Device</tns:Types>
    </tns:Probe>
  </soap:Body>
</soap:Envelope>""".encode("utf-8")

    multicast_group = ("239.255.255.250", 3702)

    def _sync_scan():
        sockets = []
        for iface in interfaces:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.bind(("0.0.0.0", 0))
                s.settimeout(0.3)
                
                # Bind socket to interface if specific IP is available
                if iface["ip"] != "0.0.0.0":
                    try:
                        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface["ip"]))
                    except Exception:
                        pass

                sockets.append((s, iface))
            except Exception as e:
                logger.warning(f"Socket error on {iface}: {e}")

        # Send probes out of every interface (multicast, local loopback, and broadcast)
        targets = [
            ("239.255.255.250", 3702),
            ("127.0.0.1", 3702),
            ("255.255.255.255", 3702)
        ]
        for s, iface in sockets:
            for target in targets:
                try:
                    s.sendto(probe_xml_network, target)
                    s.sendto(probe_xml_device, target)
                except Exception:
                    pass

        # Listen for replies until timeout
        end_time = datetime.now().timestamp() + timeout
        while datetime.now().timestamp() < end_time:
            for s, iface in sockets:
                try:
                    data, addr = s.recvfrom(65535)
                    xml_str = data.decode("utf-8", errors="ignore")
                    matches = parse_probe_matches_xml(xml_str)
                    for match in matches:
                        # Extract primary IP and port
                        for xaddr in match["xaddrs"]:
                            parsed_url = urllib.parse.urlparse(xaddr)
                            host = parsed_url.hostname
                            port = parsed_url.port or 80
                            key = f"{host}:{port}"
                            if key not in discovered_devices:
                                discovered_devices[key] = {
                                    "id": key.replace(".", "_").replace(":", "_"),
                                    "ip": host,
                                    "port": port,
                                    "xaddr": xaddr,
                                    "uuid": match.get("uuid", ""),
                                    "name": match.get("name") or f"ONVIF Camera ({host})",
                                    "hardware": match.get("hardware") or "IP Camera",
                                    "profiles": match.get("profiles", ["Profile S"]),
                                    "discovered_via": iface["name"],
                                    "discovered_at": datetime.now(timezone.utc).isoformat()
                                }
                except socket.timeout:
                    continue
                except Exception as e:
                    pass

        for s, _ in sockets:
            s.close()

    await loop.run_in_executor(None, _sync_scan)
    return list(discovered_devices.values())

"""
ONVIF WS-Security Authentication Module
Adheres to OASIS WS-Security UsernameToken Profile 1.0 specifications.
Computes PasswordDigest = Base64(SHA1(raw_nonce + created_iso + password))
and handles camera clock-skew compensation.
"""

import base64
import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import Tuple


def generate_ws_security_header(username: str, password: str, time_offset_seconds: float = 0.0) -> Tuple[str, str, str]:
    """
    Generates WS-Security UsernameToken PasswordDigest XML and raw components.
    
    Formula:
        PasswordDigest = Base64(SHA-1( Nonce_bytes + Created_string + Password_string ))
        
    Args:
        username: Camera username (e.g. 'admin')
        password: Plaintext password
        time_offset_seconds: Delta seconds between camera clock and client clock (t_camera - t_client).
        
    Returns:
        Tuple of (soap_header_xml, created_iso_timestamp, nonce_b64)
    """
    if not username:
        return "", "", ""

    # 1. Generate 16 bytes of cryptographically secure random nonce
    raw_nonce = os.urandom(16)
    nonce_b64 = base64.b64encode(raw_nonce).decode("ascii")

    # 2. Compute UTC timestamp adjusted for camera clock skew
    adjusted_now = datetime.now(timezone.utc) + timedelta(seconds=time_offset_seconds)
    created_iso = adjusted_now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # 3. Concatenate: raw_nonce bytes + created_iso ASCII bytes + password UTF-8 bytes
    combined = raw_nonce + created_iso.encode("ascii") + password.encode("utf-8")

    # 4. SHA-1 hash and Base64 encode
    digest_hash = hashlib.sha1(combined).digest()
    digest_b64 = base64.b64encode(digest_hash).decode("ascii")

    # 5. Build OASIS standard WS-Security Header XML
    header_xml = f"""
    <wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
                   xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
      <wsse:UsernameToken>
        <wsse:Username>{username}</wsse:Username>
        <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest_b64}</wsse:Password>
        <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_b64}</wsse:Nonce>
        <wsu:Created>{created_iso}</wsu:Created>
      </wsse:UsernameToken>
    </wsse:Security>"""

    return header_xml.strip(), created_iso, nonce_b64

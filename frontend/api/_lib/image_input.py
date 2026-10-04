"""Bounded inline image input; never fetch client-supplied URLs."""
import base64
import binascii
import re

MAX_IMAGE_BYTES = 2_000_000
MAX_REQUEST_BYTES = 2_800_000


def validate_image(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_REQUEST_BYTES:
        raise ValueError('Choose one PNG, JPEG or WebP image under 2 MB.')
    match = re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)', value)
    if not match:
        raise ValueError('Only inline PNG, JPEG and WebP images are supported.')
    try:
        raw = base64.b64decode(match[2], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('Invalid image encoding.') from None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('Image exceeds the 2 MB limit.')
    valid = (match[1] == 'png' and raw.startswith(b'\x89PNG\r\n\x1a\n')
             or match[1] == 'jpeg' and raw.startswith(b'\xff\xd8\xff')
             or match[1] == 'webp' and raw.startswith(b'RIFF') and raw[8:12] == b'WEBP')
    if not valid:
        raise ValueError('Image content does not match its file type.')
    return value

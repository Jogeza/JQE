"""Hosted media validation stays offline and never fetches image URLs."""
import base64
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('hosted_image_input', Path(__file__).parents[1] / 'frontend/api/_lib/image_input.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def inline(mime, raw):
    return f'data:image/{mime};base64,' + base64.b64encode(raw).decode()


@pytest.mark.parametrize('mime,raw', [('png', b'\x89PNG\r\n\x1a\n123'), ('jpeg', b'\xff\xd8\xff123'), ('webp', b'RIFF1234WEBP123')])
def test_supported_inline_formats(mime, raw):
    value = inline(mime, raw)
    assert module.validate_image(value) == value


@pytest.mark.parametrize('value', ['https://127.0.0.1/private', 'file:///credentials', inline('svg+xml', b'<svg/>'), inline('jpeg', b'not a jpeg'), 'data:image/png;base64,!!!', {}, 123])
def test_reject_external_urls_and_mismatched_content(value):
    with pytest.raises(ValueError):
        module.validate_image(value)


def test_reject_large_body_before_decoding():
    with pytest.raises(ValueError):
        module.validate_image('a' * (module.MAX_REQUEST_BYTES + 1))
    assert module.validate_image(None) is None

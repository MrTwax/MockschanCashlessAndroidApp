from base64 import b64encode
from io import BytesIO
import json

import qrcode
from qrcode.image.svg import SvgPathFillImage


def device_qr_data_uri(origin, device_key):
    payload = json.dumps(
        {"type": "odentaler-device", "version": 1, "url": origin, "device_key": device_key},
        separators=(",", ":"),
    )
    qr = qrcode.make(payload, image_factory=SvgPathFillImage)
    with BytesIO() as output:
        qr.save(output)
        return "data:image/svg+xml;base64," + b64encode(output.getvalue()).decode("ascii")

import base64
from io import BytesIO
from typing import Optional

import qrcode
from qrcode.image.pil import PilImage


class QRService:
    """Service for generating QR codes for payment URIs"""

    @staticmethod
    def generate_qr_code(payment_uri: str, size: int = 256) -> str:
        """Generate QR code as base64 PNG for payment URI"""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(payment_uri)
        qr.make(fit=True)

        # Create PIL image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Resize if needed
        if size != 256:
            img = img.resize((size, size))

        # Convert to base64
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        b64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return f"data:image/png;base64,{b64_data}"

    @staticmethod
    def create_payment_response(
        intent_id: str,
        address: str, 
        payment_uri: str,
        qr_size: int = 256
    ) -> dict:
        """Create complete payment response with QR code"""
        qr_data = QRService.generate_qr_code(payment_uri, qr_size)
        
        return {
            "intent_id": intent_id,
            "address": address,
            "payment_uri": payment_uri,
            "qr_code": qr_data,
            "qr_size": qr_size
        }
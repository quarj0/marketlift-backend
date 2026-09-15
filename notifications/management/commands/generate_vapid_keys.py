import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class Command(BaseCommand):
    help = "Generate a P-256 VAPID key pair for Marketlift Web Push."

    def handle(self, *args, **options):
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_value = private_key.private_numbers().private_value.to_bytes(32, "big")
        public_value = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )

        self.stdout.write("Add these values to the backend environment:")
        self.stdout.write(f"MARKETLIFT_VAPID_PRIVATE_KEY={_b64url(private_value)}")
        self.stdout.write("MARKETLIFT_VAPID_SUBJECT=mailto:support@marketlift.com.br")
        self.stdout.write("")
        self.stdout.write(
            "Derived public key (informational; Marketlift serves this from the API):"
        )
        self.stdout.write(_b64url(public_value))
        self.stdout.write(
            self.style.WARNING(
                "Keep MARKETLIFT_VAPID_PRIVATE_KEY secret. Never put it in a frontend or NEXT_PUBLIC_* variable."
            )
        )

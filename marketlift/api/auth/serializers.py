from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    emailOrPhone = serializers.CharField(required=False)
    password = serializers.CharField(trim_whitespace=False, write_only=True)

    def validate(self, data):
        if not data.get("email") and not data.get("emailOrPhone"):
            raise serializers.ValidationError(
                {"emailOrPhone": "Email or phone is required."}
            )
        return data


class RegisterSerializer(serializers.Serializer):
    fullName = serializers.CharField(max_length=160)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=32)
    password = serializers.CharField(write_only=True, min_length=8)
    terms = serializers.BooleanField()

    def validate_fullName(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter your full name.")
        return value

    def validate_phone(self, value):
        value = value.strip()
        if len(value) < 7:
            raise serializers.ValidationError("Enter a valid phone number.")
        return value

    def validate_terms(self, value):
        if not value:
            raise serializers.ValidationError(
                "You must accept the terms and privacy policy."
            )
        return value


class VerifySerializer(serializers.Serializer):
    userId = serializers.UUIDField()
    code = serializers.CharField(min_length=6, max_length=6)


class PasswordResetRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)


class PasswordResetSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=8)


def serialize_session_user(user):
    seller = getattr(user, "seller_profile", None)
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
        "phone": user.phone,
        "isStaff": user.is_staff,
        "isSuperuser": user.is_superuser,
        "emailVerified": bool(user.email_verified_at),
        "sellerProfile": (
            {
                "sellerId": str(seller.id),
                "activatedAt": seller.activated_at.isoformat(),
                "verified": seller.verified,
                "suspended": seller.is_suspended,
            }
            if seller
            else None
        ),
    }

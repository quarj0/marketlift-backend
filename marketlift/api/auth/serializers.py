from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, write_only=True)


def serialize_session_user(user):
    seller = getattr(user, "seller_profile", None)
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
        "phone": user.phone,
        "isStaff": user.is_staff,
        "isSuperuser": user.is_superuser,
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

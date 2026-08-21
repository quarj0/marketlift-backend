from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, HttpResponseRedirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from uploads.models import UploadAsset
from uploads.services import (
    can_access_upload,
    complete_upload,
    delete_unattached_upload,
    prepare_upload,
    store_proxy_upload,
)
from uploads.storage import get_storage_backend


def _error(exc):
    if isinstance(exc, ValidationError):
        if hasattr(exc, "message_dict"):
            return exc.message_dict
        return {"detail": exc.messages[0] if exc.messages else str(exc)}
    return {"detail": str(exc)}


def _asset(asset_id):
    try:
        return UploadAsset.objects.select_related("owner").get(pk=asset_id)
    except UploadAsset.DoesNotExist:
        return None


def _redirect_to_storage(url: str, *, public: bool):
    response = HttpResponseRedirect(url)
    if public:
        response["Cache-Control"] = "public, max-age=240"
    else:
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
    return response


class PrepareUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        try:
            asset, target = prepare_upload(
                user=request.user,
                purpose=data.get("purpose", ""),
                original_name=data.get("name", ""),
                mime_type=data.get("mimeType", ""),
                size=data.get("size", 0),
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            return Response(_error(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "upload": {
                    "id": str(asset.id),
                    "purpose": asset.purpose,
                    "status": asset.status,
                    "name": asset.original_name,
                    "mimeType": asset.mime_type,
                    "size": asset.expected_size,
                    "expiresAt": asset.expires_at,
                },
                "target": {
                    "method": target.method,
                    "url": target.url,
                    "headers": target.headers,
                    "fields": target.fields,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class UploadContentView(APIView):
    permission_classes = [AllowAny]

    def put(self, request, asset_id):
        # Session-authenticated local development upload. Remote storage
        # backends can instead return their own signed target from /prepare/.
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        asset = _asset(asset_id)
        if asset is None:
            return Response(
                {"detail": "Upload not found."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            store_proxy_upload(
                asset=asset,
                user=request.user,
                stream=request.stream,
                content_type=request.content_type or "",
                content_length=request.META.get("CONTENT_LENGTH"),
            )
        except PermissionDenied as exc:
            return Response(_error(exc), status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response(_error(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get(self, request, asset_id):
        asset = _asset(asset_id)
        if asset is None or asset.status not in {
            UploadAsset.Status.READY,
            UploadAsset.Status.ATTACHED,
        }:
            return Response(
                {"detail": "Upload not found."}, status=status.HTTP_404_NOT_FOUND
            )
        if not can_access_upload(asset=asset, user=getattr(request, "user", None)):
            return Response(
                {"detail": "You do not have access to this upload."},
                status=status.HTTP_403_FORBIDDEN,
            )
        backend = get_storage_backend(asset.storage_alias)
        redirect_url = backend.access_url(asset, request=request)
        if redirect_url:
            return _redirect_to_storage(
                redirect_url,
                public=asset.visibility == UploadAsset.Visibility.PUBLIC,
            )
        try:
            stream = backend.open(asset)
        except FileNotFoundError:
            return Response(
                {"detail": "Stored object not found."}, status=status.HTTP_404_NOT_FOUND
            )
        response = FileResponse(stream, content_type=asset.mime_type)
        response["Content-Disposition"] = (
            f'inline; filename="{asset.original_name.replace(chr(34), "")}"'
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response


class CompleteUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, asset_id):
        asset = _asset(asset_id)
        if asset is None:
            return Response(
                {"detail": "Upload not found."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            complete_upload(asset=asset, user=request.user)
        except PermissionDenied as exc:
            return Response(_error(exc), status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response(_error(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "id": str(asset.id),
                "status": asset.status,
                "contentUrl": asset.content_url,
            }
        )


class UploadDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, asset_id):
        asset = _asset(asset_id)
        if asset is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            delete_unattached_upload(asset=asset, user=request.user)
        except PermissionDenied as exc:
            return Response(_error(exc), status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response(_error(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UploadVariantView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, asset_id, kind):
        from uploads.models import UploadVariant

        asset = _asset(asset_id)
        if (
            asset is None
            or asset.status
            not in {UploadAsset.Status.READY, UploadAsset.Status.ATTACHED}
            or not can_access_upload(asset=asset, user=getattr(request, "user", None))
        ):
            return Response(
                {"detail": "Upload not found."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            variant = UploadVariant.objects.get(asset=asset, kind=kind)
        except UploadVariant.DoesNotExist:
            return Response(
                {"detail": "Variant not found."}, status=status.HTTP_404_NOT_FOUND
            )
        backend = get_storage_backend(variant.storage_alias)
        redirect_url = backend.access_url(variant, request=request)
        if redirect_url:
            return _redirect_to_storage(
                redirect_url,
                public=asset.visibility == UploadAsset.Visibility.PUBLIC,
            )
        try:
            stream = backend.open(variant)
        except FileNotFoundError:
            return Response(
                {"detail": "Stored object not found."}, status=status.HTTP_404_NOT_FOUND
            )
        response = FileResponse(stream, content_type=variant.mime_type)
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = (
            "public, max-age=86400"
            if asset.visibility == UploadAsset.Visibility.PUBLIC
            else "private, no-store"
        )
        return response

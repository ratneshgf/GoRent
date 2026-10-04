import logging

import cloudinary.uploader
from django.conf import settings
from rest_framework.exceptions import APIException

log = logging.getLogger(__name__)


class ImageUploadUnavailable(APIException):
    status_code = 503
    default_detail = "Car image upload is unavailable. Please try again later."
    default_code = "image_upload_unavailable"


def upload_vehicle_image(image):
    if not settings.CLOUDINARY_URL:
        raise ImageUploadUnavailable("Cloudinary is not configured. Ask the site administrator to set CLOUDINARY_URL.")
    image.seek(0)
    try:
        result = cloudinary.uploader.upload(image, folder="gorent/vehicles", resource_type="image")
        return result["public_id"], result["secure_url"]
    except Exception:
        log.exception("Cloudinary car image upload failed")
        raise ImageUploadUnavailable() from None


def delete_vehicle_image(public_id):
    if not public_id:
        return
    try:
        cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
    except Exception:
        log.exception("Could not remove replaced Cloudinary image %s", public_id)

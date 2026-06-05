from typing import Optional

MIME_BY_EXTENSION = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

IMAGES_BUCKET_ALLOWED = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
}


def resolve_content_type(filename: str, reported_type: Optional[str]) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    inferred = MIME_BY_EXTENSION.get(extension)
    if inferred:
        return inferred
    if reported_type and reported_type != "application/octet-stream":
        return reported_type
    return "application/octet-stream"


def storage_bucket_for_file_type(file_type: str) -> str:
    return "images" if file_type == "photo" else "documents"


def validate_image_content_type(filename: str, reported_type: Optional[str]) -> str:
    content_type = resolve_content_type(filename or "upload", reported_type)
    if content_type not in IMAGES_BUCKET_ALLOWED:
        allowed = ", ".join(sorted(IMAGES_BUCKET_ALLOWED))
        raise ValueError(
            f"Unsupported image type '{content_type}'. Allowed types: {allowed}. "
            "Use JPG, PNG, GIF, or WEBP."
        )
    return content_type

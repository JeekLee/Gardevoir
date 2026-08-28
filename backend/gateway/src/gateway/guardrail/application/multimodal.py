"""Multimodal input extraction for model-tier judgement."""

from dataclasses import dataclass
from typing import Any

from gateway.guardrail.application.port.model_judge import JudgeImage

_INPUT_ROLES = frozenset({"user"})


@dataclass(frozen=True, slots=True)
class ExtractedImages:
    images: tuple[JudgeImage, ...]
    count: int
    data_uri_bytes: int
    limit_error: str = ""


def extract_input_images(
    payload: Any, *, max_images: int, max_data_uri_bytes: int
) -> ExtractedImages:
    """Extract ordered user image references and report configured limit violations."""
    if not isinstance(payload, dict):
        return ExtractedImages((), 0, 0)
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ExtractedImages((), 0, 0)

    images: list[JudgeImage] = []
    count = 0
    data_uri_bytes = 0
    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in _INPUT_ROLES:
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part_index, part in enumerate(content):
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if not isinstance(image_url, dict):
                continue
            url = image_url.get("url")
            if not isinstance(url, str) or not url:
                continue
            count += 1
            if url.startswith("data:"):
                data_uri_bytes += len(url.encode())
            if count <= max_images:
                images.append(
                    JudgeImage(
                        role=role,
                        message_index=message_index,
                        part_index=part_index,
                        url=url,
                    )
                )

    limit_error = ""
    if count > max_images:
        limit_error = "image_count_limit_exceeded"
    elif data_uri_bytes > max_data_uri_bytes:
        limit_error = "image_data_uri_bytes_limit_exceeded"
    return ExtractedImages(tuple(images), count, data_uri_bytes, limit_error)


__all__ = ["ExtractedImages", "extract_input_images"]

"""Course-scoped project profiles and authenticated, locally stored images."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import Field, field_validator, model_validator

from .config import StrictModel
from .pinup import PinConflict, safe_url
from .store import content_hash

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ProfileField = Literal["name", "tagline", "logo", "live_url", "tech", "features", "screenshots"]


class Source(StrictModel):
    url: str = Field(min_length=1, max_length=2000)
    label: str = Field(default="Slack source", max_length=160)

    @field_validator("url")
    @classmethod
    def https(cls, value):
        return safe_url(value)


class Media(StrictModel):
    asset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    alt: str = Field(min_length=1, max_length=400)
    source_url: str = Field(min_length=1, max_length=2000)

    @field_validator("source_url")
    @classmethod
    def https(cls, value):
        return safe_url(value)


class ProjectProfile(StrictModel):
    shared: bool = False
    name: str = Field(default="", max_length=160)
    tagline: str = Field(default="", max_length=500)
    live_url: str = Field(default="", max_length=2000)
    tech: list[str] = Field(default_factory=list, max_length=25)
    features: list[str] = Field(default_factory=list, max_length=5)
    logo: Media | None = None
    screenshots: list[Media] = Field(default_factory=list, max_length=5)
    sources: list[Source] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=2000)
    missing: list[ProfileField] = Field(default_factory=list, max_length=7)
    request_url: str = Field(default="", max_length=2000)

    @field_validator("name", "tagline", "notes", "live_url", "request_url")
    @classmethod
    def trim(cls, value):
        return value.strip()

    @field_validator("live_url", "request_url")
    @classmethod
    def https(cls, value):
        return safe_url(value)

    @field_validator("tech", "features")
    @classmethod
    def items(cls, values):
        if any(not v.strip() or len(v) > 600 for v in values):
            raise ValueError("Use nonempty items of at most 600 characters")
        return [v.strip() for v in values]

    @model_validator(mode="after")
    def sourced(self):
        if (
            any(
                (
                    self.name,
                    self.tagline,
                    self.live_url,
                    self.tech,
                    self.features,
                    self.notes,
                    self.logo,
                    self.screenshots,
                )
            )
            and not self.sources
        ):
            raise ValueError("Link the sources supporting this profile")
        return self


class ProfileUpdate(StrictModel):
    profile: ProjectProfile
    expected_revision: str | None = None


def scope(store, project_id):
    course = store.course()
    if not course or not any(p.id == project_id for p in course.projects):
        raise KeyError(project_id)
    return f"{course.id}/{project_id}"


def saved_profile(store, project_id, shared=False):
    value = store.get("showcase/" + scope(store, project_id))
    if value and shared and not value["profile"]["shared"]:
        return None
    return value


def save_profile(store, project_id, update):
    prefix = scope(store, project_id)
    assets = update.profile.screenshots + ([update.profile.logo] if update.profile.logo else [])
    for asset in assets:
        if not store.get(f"showcase_media/{prefix}/{asset.asset_id}"):
            raise ValueError("Upload each image to this project before using it")
    value = {
        "profile": update.profile.model_dump(mode="json"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM settings WHERE key=?", ("showcase/" + prefix,)).fetchone()
        previous = json.loads(row["value"]) if row else None
        if (content_hash(previous) if previous else None) != update.expected_revision:
            raise PinConflict("This profile changed. Refresh before saving your changes.")
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("showcase/" + prefix, json.dumps(value)))
        for asset in assets:
            key = f"showcase_media/{prefix}/{asset.asset_id}"
            media = json.loads(
                db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()["value"]
            )
            media["updated_at"] = value["updated_at"]
            db.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(media), key))
    store.audit("project_profile_updated", {"project_id": project_id, "revision": content_hash(value)})
    return {**value, "revision": content_hash(value)}


async def upload_image(request, store, project_id):
    prefix = scope(store, project_id)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Use an image smaller than 5 MB")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP") or im.width * im.height > 20_000_000:
                raise ValueError("Use a PNG, JPEG, or WebP under 20 megapixels")
            im.load()
            # Decode and re-encode rather than serving arbitrary uploads or EXIF metadata.
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            im.thumbnail((2400, 2400))
            output = io.BytesIO()
            im.save(output, "PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Use a valid PNG, JPEG, or WebP image") from exc
    data = output.getvalue()
    asset_id = hashlib.sha256(data).hexdigest()
    store.set(
        f"showcase_media/{prefix}/{asset_id}",
        {"data": base64.b64encode(data).decode(), "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    return {"asset_id": asset_id}


def image_bytes(store, project_id, asset_id, shared=False):
    prefix = scope(store, project_id)
    if shared:
        profile = saved_profile(store, project_id, shared=True)
        if not profile:
            raise KeyError(asset_id)
        p = profile["profile"]
        assets = p["screenshots"] + ([p["logo"]] if p["logo"] else [])
        if asset_id not in {a["asset_id"] for a in assets}:
            raise KeyError(asset_id)
    value = store.get(f"showcase_media/{prefix}/{asset_id}")
    if not value:
        raise KeyError(asset_id)
    return base64.b64decode(value["data"])

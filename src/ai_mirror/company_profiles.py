"""Read-only, private company enrichment; never a second project record store."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    entrepreneur: str = Field(max_length=160)
    company: str = Field(max_length=160)


class CompanyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    group_id: str = Field(pattern=r"^(1135|255)-[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=160)
    website_url: str = Field(default="", max_length=1000)
    logo_file: str = Field(default="", pattern=r"^$|^[a-z0-9][a-z0-9-]{0,79}\.(svg|png|webp|jpg|jpeg)$")
    identity: Identity

    @field_validator("website_url")
    @classmethod
    def safe_website(cls, value):
        if value:
            parsed = urlsplit(value)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or any(c.isspace() for c in value)):
                raise ValueError("Company websites must be complete HTTPS URLs")
        return value


class CompanyCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(ge=1, le=1)
    offering: str = Field(pattern=r"^entr-5500-fall-2026$")
    companies: list[CompanyProfile] = Field(max_length=100)


def catalog_path(roster_path: str) -> Path | None:
    if not roster_path:
        return None
    roster = Path(roster_path)
    return roster.with_name(roster.stem + ".companies.json")


def load_profiles(roster_path: str) -> dict[str, CompanyProfile]:
    """Missing, malformed or duplicate metadata yields no enrichment, not lost records."""
    path = catalog_path(roster_path)
    if path is None:
        return {}
    try:
        if path.stat().st_size > 131072:
            return {}
        catalog = CompanyCatalog.model_validate(json.loads(path.read_text()))
        profiles = {entry.group_id: entry for entry in catalog.companies}
        return profiles if len(profiles) == len(catalog.companies) else {}
    except (OSError, UnicodeError, ValueError, ValidationError):
        return {}


def project_company(profiles: dict[str, CompanyProfile], group_id: str, progress) -> dict | None:
    profile = profiles.get(group_id)
    if profile is None:
        return None
    # A later founder/company change needs fresh verification, not an inherited logo.
    for key in ("entrepreneur", "company"):
        if getattr(progress, key).strip().casefold() != getattr(profile.identity, key).strip().casefold():
            return None
    return {"name": profile.name, "website_url": profile.website_url, "logo_file": profile.logo_file}

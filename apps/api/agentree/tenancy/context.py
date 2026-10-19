"""Trusted tenant context.

A TenantContext is created only by trusted server code after authorization:
membership resolution (dashboard), validated public page/widget configuration
(public), or a job payload written by trusted code (worker). Never build one
directly from a client-supplied business id.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class TenantSource(StrEnum):
    MEMBERSHIP = "membership"
    PUBLIC = "public"
    JOB = "job"
    PROVISIONING = "provisioning"


@dataclass(frozen=True, slots=True)
class TenantContext:
    business_id: UUID
    source: TenantSource

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, UUID):
            raise TypeError("business_id must be a UUID")

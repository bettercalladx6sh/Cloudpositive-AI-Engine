from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.session import Session
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class AwsIdentity:
    """Identity information for the AWS credentials being used."""

    account_id: str
    arn: str
    user_id: str


class AwsClient:
    """
    Centralized AWS client factory.

    Uses boto3's standard credential provider chain. Credentials are never
    stored, logged, or hardcoded by this class.
    """

    def __init__(self, region: str) -> None:
        """Create an AWS client factory for a specific region."""
        if not region.strip():
            raise ValueError("AWS region cannot be empty.")

        self._region = region
        self._session = boto3.Session(region_name=region)

    @property
    def region(self) -> str:
        """Return the configured AWS region."""
        return self._region

    def client(self, service_name: str) -> BaseClient:
        """
        Create a boto3 client for an AWS service.

        The client uses the credentials and configuration resolved by
        boto3's standard credential provider chain.
        """
        if not service_name.strip():
            raise ValueError("AWS service name cannot be empty.")

        return self._session.client(service_name)

    def identity(self) -> AwsIdentity:
        """
        Return the AWS identity associated with the active credentials.

        This makes an actual STS GetCallerIdentity API call.
        """
        sts_client = self.client("sts")

        response: dict[str, Any] = sts_client.get_caller_identity()

        account_id = response.get("Account")
        arn = response.get("Arn")
        user_id = response.get("UserId")

        if not account_id or not arn or not user_id:
            raise RuntimeError(
                "AWS STS returned an incomplete caller identity."
            )

        return AwsIdentity(
            account_id=account_id,
            arn=arn,
            user_id=user_id,
        )


@lru_cache(maxsize=16)
def get_aws_client(region: str) -> AwsClient:
    """
    Return a cached AWS client factory for the requested region.

    Caching prevents unnecessary boto3 Session creation while allowing
    different AWS regions to have independent clients.
    """
    return AwsClient(region)


def get_boto_session() -> Session:
    """
    Return a boto3 botocore session for inspecting AWS configuration.

    This does not make an AWS API request.
    """
    return boto3.Session()._session
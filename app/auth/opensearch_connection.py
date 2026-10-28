
import os
from pathlib import Path

from dotenv import load_dotenv
from opensearchpy import OpenSearch
from opensearchpy.exceptions import (
    AuthenticationException,
    ConnectionError as OpenSearchConnectionError,
    OpenSearchException,
)

# Load .env from the project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def get_opensearch_connection():
    """
    Create and return an OpenSearch client.

    SSL certificate verification is disabled as requested.

    Returns:
        OpenSearch: Configured OpenSearch client.

    Raises:
        ValueError: If required configuration is missing.
        OpenSearchException: If the connection test fails.
    """
    url = os.getenv("OPENSEARCH_URL")
    username = os.getenv("OPENSEARCH_USER")
    password = os.getenv("OPENSEARCH_PASSWORD")

    if not url:
        raise ValueError("Missing OPENSEARCH_URL in .env")

    if not username or not password:
        raise ValueError(
            "Missing OPENSEARCH_USER or OPENSEARCH_PASSWORD in .env"
        )

    client = OpenSearch(
        hosts=[url],
        http_auth=(username, password),
        use_ssl=url.lower().startswith("https://"),
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False,
        timeout=10,
        max_retries=2,
        retry_on_timeout=True,
    )

    try:
        # Verify server connectivity and credentials
        info = client.info()

        print("✅ OpenSearch connection successful!")
        print(f"Server: {url}")
        print(f"Cluster: {info.get('cluster_name', 'Unknown')}")
        print(f"Version: {info.get('version', {}).get('number', 'Unknown')}")

        return client

    except Exception:
        client.close()
        raise


if __name__ == "__main__":
    try:
        client = get_opensearch_connection()
        client.close()
        print("OpenSearch client closed.")

    except (
        ValueError,
        AuthenticationException,
        OpenSearchConnectionError,
        OpenSearchException,
    ) as error:
        print(f"❌ OpenSearch connection failed: {error}")

    except Exception as error:
        print(f"❌ Unexpected error: {error}")

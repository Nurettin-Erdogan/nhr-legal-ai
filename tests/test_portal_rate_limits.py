"""A source's 429 is a stop signal, never a burst of immediate retries."""

from urllib.error import HTTPError
from urllib.request import Request

import pytest

from ingestion.aym.portal import AymPortalClient, AymPortalError
from ingestion.danistay.portal import DanistayPortalClient, DanistayPortalError
from ingestion.kdk.portal import KdkPortalClient, KdkPortalError
from ingestion.mevzuat.portal import MevzuatPortalClient, MevzuatPortalError
from ingestion.yargitay.portal import PortalError, YargitayPortalClient


class _RateLimitedOpener:
    def __init__(self):
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        raise HTTPError(request.full_url, 429, "rate limited", {}, None)


@pytest.mark.parametrize(
    ("client_class", "invoke", "error_class"),
    [
        (YargitayPortalClient, lambda client: client._request(""), PortalError),
        (DanistayPortalClient, lambda client: client._request(""), DanistayPortalError),
        (MevzuatPortalClient, lambda client: client._request("", {}), MevzuatPortalError),
        (KdkPortalClient, lambda client: client._request(""), KdkPortalError),
        (AymPortalClient, lambda client: client._open(Request(client.base_url)), AymPortalError),
    ],
)
def test_429_stops_request_without_immediate_retry(client_class, invoke, error_class):
    opener = _RateLimitedOpener()
    client = client_class(opener=opener, max_retries=3)
    with pytest.raises(error_class, match="429"):
        invoke(client)
    assert opener.calls == 1

import os
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from backend.routers.query import authorize_query


def test_missing_token_denied():
    with pytest.raises(HTTPException) as error:
        authorize_query(None, None)
    assert error.value.status_code == 401


def test_service_token_never_accepts_empty_secret():
    with patch.dict(os.environ, {"BACKEND_SERVICE_TOKEN": ""}):
        with pytest.raises(HTTPException) as error:
            authorize_query(None, "anything")
    assert error.value.status_code == 401


def test_service_token_avoids_upstream():
    with patch.dict(os.environ, {"BACKEND_SERVICE_TOKEN": "server-only-value"}), patch(
        "backend.routers.query.requests.post"
    ) as upstream:
        authorize_query(None, "server-only-value")
        upstream.assert_not_called()


def test_user_token_checked_with_upstream():
    response = Mock(status_code=200)
    response.json.return_value = {"code": "200"}
    with patch("backend.routers.query.requests.post", return_value=response) as upstream:
        authorize_query("user-token", None)
        assert upstream.call_args.kwargs["headers"] == {"Octopus-Token": "user-token"}


def test_expired_user_token_denied():
    response = Mock(status_code=200)
    response.json.return_value = {"code": "401"}
    with patch("backend.routers.query.requests.post", return_value=response):
        with pytest.raises(HTTPException) as error:
            authorize_query("expired-token", None)
    assert error.value.status_code == 401

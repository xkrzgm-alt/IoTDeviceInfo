import base64
import json
import logging
import random
import string
from typing import Any, Optional

import requests
from Crypto.Cipher import PKCS1_v1_5, AES
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad

from config import (
    ROUTER_CODE_CLIENT_ID,
    ROUTER_CODE_TENANT_ID,
    ROUTER_CODE_PUB_KEY,
    ROUTER_CODE_USER,
    ROUTER_CODE_PWD,
    ROUTER_CODE_LOGIN_URL,
    ROUTER_CODE_QUERY_URL,
    DASH_USER,
    DASH_PWD,
    DASH_ROUTER_LOGIN_URL,
    DASH_ROUTER_QUERY_URL,
)


class DashRouterFetcher:
    """Resolve router records through dash.vendera.ai (the default source)."""

    def __init__(self):
        self.token: Optional[str] = None

    def get_auth_token(self) -> Optional[str]:
        try:
            response = requests.post(
                DASH_ROUTER_LOGIN_URL,
                json={"username": DASH_USER, "password": DASH_PWD},
                headers={
                    "accept": "application/json, text/plain, */*",
                    "content-type": "application/json;charset=UTF-8",
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            self.token = (data.get("data") or {}).get("token")
            if self.token:
                logging.info("Dash router module - Login successful")
                return self.token
            logging.error("Dash router module - Login succeeded but no token was returned")
        except Exception as e:
            logging.error(f"Dash router module - Login failed: {e}")
        return None

    def _query(self, **params) -> list[dict[str, Any]]:
        if not self.token and not self.get_auth_token():
            return []
        params.setdefault("pageNum", 1)
        params.setdefault("pageSize", 10)
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            response = requests.get(
                DASH_ROUTER_QUERY_URL, headers=headers, params=params, timeout=10
            )
            if response.status_code == 401:
                self.token = None
                if not self.get_auth_token():
                    return []
                headers["Authorization"] = f"Bearer {self.token}"
                response = requests.get(
                    DASH_ROUTER_QUERY_URL, headers=headers, params=params, timeout=10
                )
            response.raise_for_status()
            body = response.json()
            records = (body.get("data") or {}).get("records", [])
            if body.get("code") == 200 and isinstance(records, list):
                return [row for row in records if isinstance(row, dict)]
            logging.error(f"Dash router query failed: {body.get('message', 'Unknown error')}")
        except Exception as e:
            logging.error(f"Dash router query exception: {e}")
        return []

    def get_router_record(self, machine_id: str) -> Optional[dict[str, Any]]:
        rows = self._query(machineId=machine_id)
        if rows:
            return rows[0]
        return None

    def get_router_record_by_code(self, router_code: str) -> Optional[dict[str, Any]]:
        rows = self._query(code=router_code)
        if rows:
            return rows[0]
        return None


class AppBossRouterFetcher:
    """Legacy app-boss router lookup used as the fallback source."""

    def __init__(self):
        self.username = ROUTER_CODE_USER
        self.password = ROUTER_CODE_PWD
        self.token: Optional[str] = None

    @staticmethod
    def _generate_random_aes_key(length: int = 16) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    @staticmethod
    def _rsa_encrypt(plaintext: str) -> str:
        pem_key = f"-----BEGIN PUBLIC KEY-----\n{ROUTER_CODE_PUB_KEY}\n-----END PUBLIC KEY-----"
        cipher = PKCS1_v1_5.new(RSA.import_key(pem_key))
        return base64.b64encode(cipher.encrypt(plaintext.encode("utf-8"))).decode("utf-8")

    @staticmethod
    def _aes_encrypt(plaintext: str, aes_key_str: str) -> str:
        cipher = AES.new(aes_key_str.encode("utf-8"), AES.MODE_ECB)
        return base64.b64encode(
            cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size, style="pkcs7"))
        ).decode("utf-8")

    def get_auth_token(self) -> Optional[str]:
        try:
            aes_key = self._generate_random_aes_key()
            payload = {
                "clientId": ROUTER_CODE_CLIENT_ID,
                "grantType": "password",
                "tenantId": ROUTER_CODE_TENANT_ID,
                "username": self.username,
                "password": self.password,
            }
            encrypted_payload = self._aes_encrypt(
                json.dumps(payload, separators=(",", ":")), aes_key
            )
            headers = {
                "accept": "application/json, text/plain, */*",
                "clientid": ROUTER_CODE_CLIENT_ID,
                "content-type": "application/json;charset=UTF-8",
                "encrypt-key": self._rsa_encrypt(
                    base64.b64encode(aes_key.encode("utf-8")).decode("utf-8")
                ),
                "isencrypt": "true",
                "origin": "https://app-boss-usa.vendera.ai",
                "referer": "https://app-boss-usa.vendera.ai/login?redirect=/index",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            response = requests.post(
                ROUTER_CODE_LOGIN_URL, json=encrypted_payload, headers=headers, timeout=10
            )
            response.raise_for_status()
            self.token = (response.json().get("data") or {}).get("access_token")
            if self.token:
                logging.info("App-boss router fallback - Login successful")
                return self.token
        except Exception as e:
            logging.error(f"App-boss router fallback - Login failed: {e}")
        return None

    def _query(self, **params) -> list[dict[str, Any]]:
        if not self.token and not self.get_auth_token():
            return []
        params.setdefault("pageNum", 1)
        params.setdefault("pageSize", 10)
        try:
            response = requests.get(
                ROUTER_CODE_QUERY_URL,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "ClientId": ROUTER_CODE_CLIENT_ID,
                    "Accept": "application/json, text/plain, */*",
                },
                params=params,
                timeout=10,
            )
            if response.status_code == 401:
                self.token = None
                if not self.get_auth_token():
                    return []
                return self._query(**params)
            body = response.json()
            if body.get("code") == 200:
                return [row for row in body.get("rows", []) if isinstance(row, dict)]
            logging.error(f"App-boss router query failed: {body.get('msg', 'Unknown error')}")
        except Exception as e:
            logging.error(f"App-boss router query exception: {e}")
        return []

    def get_router_record(self, machine_id: str) -> Optional[dict[str, Any]]:
        rows = self._query(machineId=machine_id)
        if rows:
            row = dict(rows[0])
            row.setdefault("code", row.get("routerCode"))
            row.setdefault("machineId", row.get("machineId"))
            return row
        return None

    def get_router_record_by_code(self, router_code: str) -> Optional[dict[str, Any]]:
        rows = self._query(routerCode=router_code)
        if rows:
            row = dict(rows[0])
            row.setdefault("code", row.get("routerCode"))
            row.setdefault("machineId", row.get("machineId"))
            return row
        return None


class RouterCodeFetcher:
    """Resolve router/device associations via dash, then app-boss fallback."""

    def __init__(self):
        self.dash = DashRouterFetcher()
        self.app_boss = AppBossRouterFetcher()

    def get_router_record(self, machine_id: str) -> Optional[dict[str, Any]]:
        record = self.dash.get_router_record(machine_id)
        if record:
            logging.info(f"Dash resolved device [{machine_id}] to router [{record.get('code')}]")
            return record
        logging.warning(f"Dash lookup found no router for device [{machine_id}]; trying app-boss")
        record = self.app_boss.get_router_record(machine_id)
        if record:
            logging.info(f"App-boss resolved device [{machine_id}] to router [{record.get('code')}]")
        return record

    def get_router_record_by_code(self, router_code: str) -> Optional[dict[str, Any]]:
        record = self.dash.get_router_record_by_code(router_code)
        if record:
            return record
        logging.warning(f"Dash lookup found no device for router [{router_code}]; trying app-boss")
        return self.app_boss.get_router_record_by_code(router_code)

    def get_router_code(self, machine_id: str) -> Optional[str]:
        record = self.get_router_record(machine_id)
        return record.get("code") if record else None

    def get_machine_id_by_router_sn(self, router_sn: str) -> Optional[str]:
        record = self.get_router_record_by_code(router_sn)
        return record.get("machineId") if record else None

import base64
import json
import logging
import random
import string
from typing import Optional

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
)


class RouterCodeFetcher:
    """Fetch the router SN (RouterCode) corresponding to a device"""

    def __init__(self):
        self.username = ROUTER_CODE_USER
        self.password = ROUTER_CODE_PWD
        self.token: Optional[str] = None

    @staticmethod
    def _generate_random_aes_key(length: int = 16) -> str:
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(length))

    @staticmethod
    def _rsa_encrypt(plaintext: str) -> str:
        pem_key = f"-----BEGIN PUBLIC KEY-----\n{ROUTER_CODE_PUB_KEY}\n-----END PUBLIC KEY-----"
        rsa_key = RSA.import_key(pem_key)
        cipher = PKCS1_v1_5.new(rsa_key)
        encrypted_bytes = cipher.encrypt(plaintext.encode('utf-8'))
        return base64.b64encode(encrypted_bytes).decode('utf-8')

    @staticmethod
    def _aes_encrypt(plaintext: str, aes_key_str: str) -> str:
        key_bytes = aes_key_str.encode('utf-8')
        cipher = AES.new(key_bytes, AES.MODE_ECB)
        padded_data = pad(plaintext.encode('utf-8'), AES.block_size, style='pkcs7')
        encrypted_bytes = cipher.encrypt(padded_data)
        return base64.b64encode(encrypted_bytes).decode('utf-8')

    def get_auth_token(self) -> Optional[str]:
        try:
            dynamic_aes_key = self._generate_random_aes_key(16)
            payload_dict = {
                "clientId": ROUTER_CODE_CLIENT_ID,
                "grantType": "password",
                "tenantId": ROUTER_CODE_TENANT_ID,
                "username": self.username,
                "password": self.password,
            }
            json_str = json.dumps(payload_dict, separators=(',', ':'))
            encrypted_payload = self._aes_encrypt(json_str, aes_key_str=dynamic_aes_key)
            aes_key_base64 = base64.b64encode(dynamic_aes_key.encode('utf-8')).decode('utf-8')
            header_encrypt_key = self._rsa_encrypt(aes_key_base64)

            headers = {
                "accept": "application/json, text/plain, */*",
                "clientid": ROUTER_CODE_CLIENT_ID,
                "content-type": "application/json;charset=UTF-8",
                "encrypt-key": header_encrypt_key,
                "isencrypt": "true",
                "origin": "https://app-boss-usa.vendera.ai",
                "referer": "https://app-boss-usa.vendera.ai/login?redirect=/index",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }

            response = requests.post(ROUTER_CODE_LOGIN_URL, json=encrypted_payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("data", {}).get("access_token")
                if self.token:
                    logging.info("Router SN module - Login successful, obtained Bearer Token")
                    return self.token
            logging.error("Router SN module - Login failed or no Token obtained")
            return None
        except Exception as e:
            logging.error(f"Router SN module - Login exception: {str(e)}")
            return None

    def _query_router_list(self, **params) -> list:
        """Query the routerInfo list endpoint with arbitrary params. Returns rows list."""
        if not self.token:
            self.get_auth_token()
        if not self.token:
            return []

        headers = {
            "Authorization": f"Bearer {self.token}",
            "ClientId": ROUTER_CODE_CLIENT_ID,
            "Accept": "application/json, text/plain, */*",
        }
        params.setdefault("pageNum", 1)
        params.setdefault("pageSize", 10)

        try:
            response = requests.get(ROUTER_CODE_QUERY_URL, headers=headers, params=params, timeout=10)
            data = response.json()
            if data.get("code") == 200:
                return data.get("rows", [])
            logging.error(f"Router SN query failed: {data.get('msg', 'Unknown error')}")
            return []
        except Exception as e:
            logging.error(f"Router SN query exception: {str(e)}")
            return []

    def get_router_code(self, machine_id: str) -> Optional[str]:
        rows = self._query_router_list(machineId=machine_id)
        if rows:
            router_code = rows[0].get("routerCode")
            logging.info(f"Device [{machine_id}] corresponding Router SN: {router_code}")
            return router_code
        return None

    def get_machine_id_by_router_sn(self, router_sn: str) -> Optional[str]:
        """Reverse lookup: given a router SN, return the associated machine/device ID."""
        rows = self._query_router_list(routerCode=router_sn)
        if rows:
            machine_id = rows[0].get("machineId")
            logging.info(f"Router SN [{router_sn}] corresponding Device ID: {machine_id}")
            return machine_id
        logging.warning(f"No device ID found for Router SN [{router_sn}]")
        return None

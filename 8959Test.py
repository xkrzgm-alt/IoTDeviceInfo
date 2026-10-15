import os
import requests
from datetime import datetime, timedelta

# ==========================================
# 配置参数 (InHand Device Manager)
# ==========================================
DM_BASE_URL = os.environ.get("DM_BASE_URL", "https://iot.inhandnetworks.com")
DM_CLIENT_ID = os.environ.get("DM_CLIENT_ID", "")
DM_CLIENT_SECRET = os.environ.get("DM_CLIENT_SECRET", "")
DM_USERNAME = os.environ.get("DM_USERNAME", "")
DM_PASSWORD = os.environ.get("DM_PASSWORD", "")

# ==========================================
# 配置参数 (三三云 / 北向 API - 另一款路由器)
# ==========================================
SANSAN_BASE_URL = os.environ.get("SANSAN_BASE_URL", "https://sandora.hongdian.com")  # 假设的基础URL，如果报错请替换为真实的
SANSAN_TOKEN = os.environ.get("SANSAN_TOKEN", "")

# ==========================================
# 配置参数 (Hologram API)
# ==========================================
HOLOGRAM_API_KEY = os.environ.get("HOLOGRAM_API_KEY", "")
HOLOGRAM_BASE_URL = os.environ.get("HOLOGRAM_BASE_URL", "https://dashboard.hologram.io/api/1")
HOLOGRAM_ORG_ID = os.environ.get("HOLOGRAM_ORG_ID", "")


# ==========================================
# 客户端 1：新增加的另一款路由器北向 API 客户端
# ==========================================

class SansanApiClient:
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token

    def get_router_by_sn(self, target_sn):
        print(f"🔍 [北向API] 正在调用北向 API 查询设备 【{target_sn}】...")

        endpoint = f"{self.base_url}/api/device/get"
        params = {"sn": target_sn}
        headers = {"Authentication": self.token}

        try:
            # 发送请求
            response = requests.get(endpoint, headers=headers, params=params, verify=False)

            # --- 调试代码块开始 ---
            try:
                json_resp = response.json()
                print("\n" + "=" * 60)
                print("🛠️ [调试] 北向 API 返回的所有字段结构：")

                # 递归打印所有 key-value，如果是嵌套字典则显示层级
                def print_dict(d, indent=0):
                    for k, v in d.items():
                        print("  " * indent + f"- {k}: {v}")
                        if isinstance(v, dict):
                            print_dict(v, indent + 1)

                result = json_resp.get("result", {})
                if isinstance(result, dict):
                    print_dict(result)
                else:
                    print(f"  - result: {result}")
                print("=" * 60 + "\n")

            except ValueError:
                print(f"❌ [北向API] JSON 解析失败。原始内容: {response.text}")
            # --- 调试代码块结束 ---

            if not json_resp.get("success"):
                raise Exception(f"北向 API 业务错误：{json_resp.get('message')}")

            return json_resp.get("result", {})

        except Exception as e:
            print(f"❌ [北向API] 请求异常：{str(e)}")
            raise e


# ==========================================
# 客户端 2：原有的 InHand 路由器客户端
# ==========================================
class InHandApiClient:
    def __init__(self, base_url, client_id, client_secret, username, password):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.access_token = None
        self.token_expiry = None

    def _get_new_token(self):
        url = f"{self.base_url}/oauth2/access_token"
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
        data = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
            "password_type": 1
        }
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()
        self.access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)
        self.token_expiry = datetime.now() + timedelta(seconds=expires_in)

    def _make_request(self, endpoint, params=None):
        if self.access_token is None or datetime.now() >= self.token_expiry:
            self._get_new_token()
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(f"{self.base_url}{endpoint}", headers=headers, params=params)
        if response.status_code == 401:
            self._get_new_token()
            headers["Authorization"] = f"Bearer {self.access_token}"
            response = requests.get(f"{self.base_url}{endpoint}", headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_router_by_sn(self, target_sn):
        print(f"🔍 [InHand] 检测到 RF 设备，调用 InHand 接口查询 【{target_sn}】...")
        params = {"serial_number": target_sn, "cursor": 0, "limit": 10, "verbose": 50}
        response = self._make_request("/api/devices", params=params)
        if not response.get("result"):
            raise Exception(f"❌ 在 InHand 平台未找到 SN 为【{target_sn}】的设备")
        return response["result"][0]


# ==========================================
# 客户端 3：Hologram SIM 卡查询客户端
# ==========================================
class HologramApiClient:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url

    def get_hologram_sim_info(self, iccid, imei):
        search_field = "iccid" if iccid and iccid != "未获取到" else "imei"
        search_value = str(iccid).strip() if iccid and iccid != "未获取到" else str(imei).strip()

        endpoint = f"{self.base_url}/links/cellular"
        params = {"limit": 5}
        if HOLOGRAM_ORG_ID:
            params["orgid"] = int(HOLOGRAM_ORG_ID)
        params["sim" if iccid and iccid != "未获取到" else "imei"] = search_value

        try:
            response = requests.get(endpoint, auth=("apikey", self.api_key), params=params)
            response.raise_for_status()
            sim_list = response.json().get("data", [])

            if not sim_list:
                return None

            sim_data = sim_list[0]
            device_id = sim_data.get("deviceid")

            device_data = {}
            if device_id:
                resp_dev = requests.get(f"{self.base_url}/devices/{device_id}", auth=("apikey", self.api_key))
                if resp_dev.status_code == 200:
                    device_data = resp_dev.json().get("data", {})

            device_cellular_link = {}
            if device_data.get("links") and isinstance(device_data["links"].get("cellular"), list) and len(
                    device_data["links"]["cellular"]) > 0:
                device_cellular_link = device_data["links"]["cellular"][0]

            last_session = device_data.get("lastsession") or device_data.get("last_session") or sim_data.get(
                "last_session") or {}
            last_active = last_session.get("session_begin") or device_cellular_link.get("last_connect_time",
                                                                                        "从未连接 / 未知")

            sim_info = {
                "设备名称 (Device Name)": device_data.get("name", sim_data.get("devicename", "未知")),
                "SIM卡状态 (State)": sim_data.get("state", "未知"),
                "ICCID": sim_data.get("sim", "未知"),
                "IMSI": sim_data.get("imsi", "未知"),
                "所属网络 (Network)": last_session.get("network_name") or device_cellular_link.get("last_network_used",
                                                                                                   "未知"),
                "数据套餐 (Plan)": (device_cellular_link.get("plan", {}).get("name") or "未知").strip(),
                "当月流量 (Bytes)": device_cellular_link.get("cur_billing_data_used", 0),
                "当月流量 (GB)": round(device_cellular_link.get("cur_billing_data_used", 0) / (1024 ** 3), 2),
                "最后活跃时间": last_active,
                "会话开始时间 (Session Begin)": last_session.get("session_begin", "未知"),
                "会话结束时间 (Session End)": last_session.get("session_end", "未知"),
                "会话是否活跃 (Active)": last_session.get("active", "未知")
            }
            return sim_info

        except Exception as e:
            print(f"❌ [Hologram] API 请求出错: {str(e)}")
            return None


def main(target_sn):
    try:
        # ==========================================
        # 智能路由：根据 SN 决定走哪个 API
        # ==========================================
        is_inhand = target_sn.upper().startswith("RF")

        print("\n" + "=" * 60)

        if is_inhand:
            # --- 分支 A: InHand 路由器 ---
            inhand_client = InHandApiClient(DM_BASE_URL, DM_CLIENT_ID, DM_CLIENT_SECRET, DM_USERNAME, DM_PASSWORD)
            router_info = inhand_client.get_router_by_sn(target_sn)

            is_online = router_info.get("online") == 1
            status_text = "🟢 在线 (Online)" if is_online else "🔴 离线 (Offline)"

            info_dict = router_info.get("info") or {}
            imei = info_dict.get("imei", router_info.get("imei", "未获取到"))
            iccid = info_dict.get("iccid", router_info.get("iccid", "未获取到"))

            print(f"🖥️  InHand 设备 【{target_sn}】 状态: {status_text}")
            print(f"🏷️  硬件提取 IMEI: {imei}")
            print(f"💳  硬件提取 ICCID: {iccid}")
            print("=" * 60)

            # InHand 路由器可以继续查询 Hologram
            if (imei and imei != "未获取到") or (iccid and iccid != "未获取到"):
                hologram_client = HologramApiClient(HOLOGRAM_API_KEY, HOLOGRAM_BASE_URL)
                sim_info = hologram_client.get_hologram_sim_info(iccid, imei)

                if sim_info:
                    print(f"\n📲 Hologram SIM 卡关键信息摘要：")
                    for key, val in sim_info.items():
                        print(f"      {key}：{val}")
            else:
                print("\nℹ️ 路由器既未上报 IMEI，也未上报 ICCID，无法继续查询 Hologram SIM 卡状态。")

        else:
            # --- 分支 B: 北向 API (三三云路由器) ---
            sansan_client = SansanApiClient(SANSAN_BASE_URL, SANSAN_TOKEN)
            router_info = sansan_client.get_router_by_sn(target_sn)

            # 解析在线状态
            online_str = router_info.get("onlineStatus", "").lower()
            is_online = (online_str == "online")
            status_text = "🟢 在线 (Online)" if is_online else "🔴 离线 (Offline)"

            # 解析硬件信息
            device_name = router_info.get("name", "未知设备")
            last_live = router_info.get("lastLiveTime", "未知")

            # 解析新字段：IMEI, ICCID, CSQ
            # IMEI 藏在 netInfo 字典里
            net_info = router_info.get("netInfo", {})
            imei = net_info.get("imei", "未获取到")
            # ICCID 即 sim1
            iccid = router_info.get("sim1", "未获取到")
            # CSQ 藏在 netInfo 字典里
            csq = net_info.get("csq", "未获取到")

            print(f"🖥️  第三方设备 【{target_sn}】 状态: {status_text}")
            print(f"📛  设备名称: {device_name}")
            print(f"🕒  最后活跃: {last_live}")
            print(f"🏷️  硬件提取 IMEI: {imei}")
            print(f"💳  硬件提取 ICCID: {iccid}")
            print(f"📶  信号质量 (CSQ): {csq}")
            print("=" * 60)

            # 尝试关联 Hologram 查询 (如果存在 ICCID/IMEI)
            if (imei and imei != "未获取到") or (iccid and iccid != "未获取到"):
                hologram_client = HologramApiClient(HOLOGRAM_API_KEY, HOLOGRAM_BASE_URL)
                sim_info = hologram_client.get_hologram_sim_info(iccid, imei)
                if sim_info:
                    print(f"\n📲 Hologram SIM 卡关键信息摘要：")
                    for key, val in sim_info.items():
                        print(f"      {key}：{val}")
            else:
                print("\nℹ️ 路由器未上报 IMEI/ICCID，无法继续 Hologram 查询。")
    except Exception as e:
        print(f"\n❌ 程序执行错误：{str(e)}")


if __name__ == "__main__":
    # 测试 InHand 路由器
    print("--- 正在测试 InHand 路由器 ---")
    main("RF3022530636134")

    # 测试另一款路由器
    print("\n\n--- 正在测试第三方北向API路由器 ---")
    main("89591025C2700120")  # 替换为真实的 8959 开头的 SN
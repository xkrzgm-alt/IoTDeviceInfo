import logging
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import scrolledtext, messagebox

from device_info import DeviceInfoFetcher, translate_status
from router_code import RouterCodeFetcher
from inhand_client import InHandApiClient
from hongdian_client import HongdianApiClient
from jc_module_client import JCModuleClient
from hologram_client import HologramApiClient
from pos_client import POSClient


# ---------------------------------------------------------------------------
# Data fetching layer
# ---------------------------------------------------------------------------

def _fetch_device_info(target_device_id: str) -> dict:
    fetcher = DeviceInfoFetcher()
    token = fetcher.get_auth_token()
    if token:
        return fetcher.get_device_info(target_device_id, token)
    return {}


def _fetch_router_record(target: str, reverse: bool = False) -> dict | None:
    fetcher = RouterCodeFetcher()
    if reverse:
        return fetcher.get_router_record_by_code(target)
    return fetcher.get_router_record(target)


def _fetch_router_sn(target: str, reverse: bool = False) -> str | None:
    record = _fetch_router_record(target, reverse=reverse)
    if not record:
        return None
    return record.get("machineId") if reverse else record.get("code")


def _fetch_router_and_signal(router_sn: str, device_id: str = "") -> tuple[dict, dict]:
    if router_sn.upper().startswith("RF"):
        return _fetch_inhand(router_sn)
    elif router_sn.upper().startswith("JC"):
        return _fetch_jc_module(router_sn, device_id)
    else:
        return _fetch_hongdian(router_sn)


def _fetch_inhand(router_sn: str) -> tuple[dict, dict]:
    client = InHandApiClient()
    router_info = client.get_router_by_sn(router_sn)

    device_id = router_info.get("Device ID (InHand)")
    logging.info(f"Router internal ID: {device_id}")

    signal_info = {}
    if device_id:
        try:
            signal_info = client.get_4g_signal_info(device_id)
            logging.info("4G signal info retrieved successfully")
        except Exception as e:
            logging.warning(f"4G signal info retrieval failed: {str(e)}")
            signal_info = {"Status": f"Retrieval failed: {str(e)}"}

    return router_info, signal_info


def _fetch_hongdian(router_sn: str) -> tuple[dict, dict]:
    client = HongdianApiClient()
    router_info, signal_info = client.get_router_by_sn(router_sn)
    return router_info, signal_info


def _fetch_jc_module(router_sn: str, machine_code: str) -> tuple[dict, dict]:
    client = JCModuleClient()
    router_info, signal_info = client.get_4g_module_info(router_sn, machine_code)
    return router_info, signal_info


def _fetch_sim_info(router_info: dict) -> dict:
    hologram = HologramApiClient()
    return hologram.get_hologram_sim_info(
        router_info.get("ICCID"), router_info.get("IMEI")
    ) or {}


def _fetch_sim_info_by_iccid(iccid: str) -> dict:
    hologram = HologramApiClient()
    return hologram.get_sim_info_by_iccid(iccid) or {}


def _fetch_pos_info(target_device_id: str) -> dict:
    client = POSClient()
    return client.get_pos_info(target_device_id)


# ---------------------------------------------------------------------------
# Data collection — returns structured results for GUI
# ---------------------------------------------------------------------------

def _timed_call(stage: str, func, *args, **kwargs):
    """Run a network stage and log its duration without exposing arguments."""
    started = time.perf_counter()
    try:
        return func(*args, **kwargs)
    finally:
        logging.info("Query stage %s completed in %.3fs", stage, time.perf_counter() - started)


_QUERY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="device-query")


def collect_device_data(device_id: str, router_sn: str, iccid: str = None) -> dict:
    """Execute queries and return structured data. At least one of device_id,
    router_sn, or iccid must be provided. device_id queries the vendera.ai platform
    and optionally resolves router SN; router_sn queries the InHand/Hongdian router
    platform and Hologram SIM info directly; iccid (alone) queries Hologram SIM info
    by ICCID and returns the linked device id/name.

    Independent external calls are deliberately bounded and run concurrently. Each
    call still has its own failure handling so one optional integration cannot block
    the complete result.
    """
    if not device_id and not router_sn and not iccid:
        return {"error": "Please enter a device ID, router SN, or SIM ICCID!"}

    device_info = {}
    pos_info = {}
    router_info, signal_info = {}, {}
    router_metadata = {}
    sim_info = {}

    if iccid and not device_id and not router_sn:
        # ICCID-only lookup: SIM info + linked device id/name (no device/router/POS)
        sim_info = _timed_call("hologram-sim-by-iccid", _fetch_sim_info_by_iccid, iccid)
        return {
            "device_id": "",
            "router_sn": "",
            "iccid": iccid,
            "device_info": device_info,
            "router_info": router_info,
            "signal_info": signal_info,
            "sim_info": sim_info,
            "pos_info": pos_info,
        }

    if device_id:
        # Device details and the forward association lookup do not depend on one
        # another. Running them together removes one full WAN round trip.
        futures = {
            "device": _QUERY_EXECUTOR.submit(_timed_call, "device-info", _fetch_device_info, device_id),
        }
        if not router_sn:
            futures["router-record"] = _QUERY_EXECUTOR.submit(
                _timed_call, "router-association", _fetch_router_record, device_id
            )
        device_info = futures["device"].result()
        if not router_sn:
            router_record = futures["router-record"].result()
            if router_record:
                router_sn = router_record.get("code") or ""
                router_metadata = router_record
    elif router_sn:
        # Reverse lookup: Router SN → Device ID → device info
        router_record = _timed_call("router-association", _fetch_router_record, router_sn, True)
        if router_record:
            device_id = router_record.get("machineId") or ""
            router_metadata = router_record
        else:
            device_id = ""
        if device_id:
            device_info = _timed_call("device-info", _fetch_device_info, device_id)

    if router_sn and not router_metadata:
        router_metadata = _timed_call(
            "router-association", _fetch_router_record, router_sn, True
        ) or {}

    # POS and router data are independent once the IDs are known.
    if device_id or router_sn:
        futures = {}
        if device_id:
            futures["pos"] = _QUERY_EXECUTOR.submit(
                _timed_call, "pos", _fetch_pos_info, device_id
            )
        if router_sn:
            futures["router"] = _QUERY_EXECUTOR.submit(
                _timed_call, "router-signal", _fetch_router_and_signal, router_sn, device_id
            )
        if "pos" in futures:
            try:
                pos_info = futures["pos"].result()
            except Exception as e:
                logging.error(f"Failed to retrieve POS info: {e}")
        if "router" in futures:
            try:
                router_info, signal_info = futures["router"].result()
                if router_metadata:
                    router_info.update({
                        "Router SN": router_metadata.get("code", router_sn),
                        "Router Metadata": router_metadata,
                    })
                    if router_metadata.get("imei") and not router_info.get("IMEI"):
                        router_info["IMEI"] = router_metadata["imei"]
                    if not router_info.get("Device Model"):
                        model = router_metadata.get("model") or router_metadata.get("brand")
                        if model:
                            router_info["Device Model"] = model
                if signal_info:
                    router_info["4G Signal Info"] = signal_info
                sim_info = _timed_call("hologram-sim", _fetch_sim_info, router_info)
            except Exception as e:
                logging.error(f"Failed to retrieve router/SIM/signal info: {str(e)}")

    return {
        "device_id": device_id,
        "router_sn": router_sn,
        "iccid": iccid,
        "device_info": device_info,
        "router_info": router_info,
        "signal_info": signal_info,
        "sim_info": sim_info,
        "pos_info": pos_info,
    }


# ---------------------------------------------------------------------------
# Format output — convert structured data to text
# ---------------------------------------------------------------------------

def _format_signal_section(signal_info: dict) -> str:
    lines = ["\n    \U0001f4f6 4G Signal Details (Latest Status):"]
    for k, v in signal_info.items():
        prefix = "[*] " if "RSRP" in k or "SNR" in k else "    "
        lines.append(f"    {prefix}{k}: {v}")
    lines.append("\n    Signal Indicator Reference:")
    lines.append("    - RSRP: -44~-90dBm Excellent, -90~-105dBm Good, -105~-120dBm Fair, <-120dBm Poor")
    lines.append("    - SNR: 10~40dB Excellent, 0~10dB Good, -10~0dB Fair, <-10dB Poor")
    return "\n".join(lines)


def format_results(data: dict) -> str:
    """Format the return value of collect_device_data as display text."""
    if "error" in data:
        return f"[Error] {data['error']}"

    device_id = data["device_id"]
    router_sn = data["router_sn"]
    device_info = data["device_info"]
    router_info = data["router_info"]
    signal_info = data["signal_info"]
    sim_info = data["sim_info"]
    pos_info = data.get("pos_info", {})

    label = device_id or router_sn or data.get("iccid")
    mode = " (Device ID)" if device_id else " (Router SN)" if router_sn else " (SIM ICCID)"

    lines = []
    lines.append("=" * 80)
    lines.append(f"\U0001f4cb Device [{label}] Complete Information Summary{mode}")
    lines.append("=" * 80)

    if device_info:
        lines.append("\n\U0001f4e6 [Device Basic Info]")
        for k, v in device_info.get("Basic Info", {}).items():
            lines.append(f"  {k}: {v}")

        lines.append("\n\U0001f4ca [Device Operating Info]")
        for k, v in device_info.get("Operating Info", {}).items():
            if k == "Channels" and isinstance(v, dict):
                for channel, channel_values in v.items():
                    lines.append(f"  [{channel}]")
                    for channel_key, channel_value in channel_values.items():
                        lines.append(f"    {channel_key}: {channel_value}")
            else:
                lines.append(f"  {k}: {v}")
    else:
        lines.append("\n\U0001f310 Device info not fetched (direct query)")

    lines.append("\n\U0001f4b3 [POS Reader Info]")
    if pos_info:
        for k, v in pos_info.items():
            lines.append(f"  {k}: {v}")
    else:
        lines.append("  No POS info obtained")

    lines.append("\n\U0001f5e1 [Router Info]")
    if router_info:
        for k, v in router_info.items():
            if k == "4G Signal Info":
                if v:
                    lines.append(_format_signal_section(v))
            elif k != "Device ID (InHand)":
                lines.append(f"  {k}: {v}")
    else:
        lines.append("  No router info obtained")

    lines.append("\n\U0001f4f1 [Hologram SIM Card Info]")
    if sim_info:
        for k, v in sim_info.items():
            lines.append(f"  {k}: {v}")
    else:
        lines.append("  No SIM card info obtained")

    lines.append("\n" + "=" * 80)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Logging Handler — redirect logging output to tkinter Text widget
# ---------------------------------------------------------------------------

class TextHandler(logging.Handler):
    """Thread-safe logging handler that sends log records to tkinter Text widget."""

    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s'))

    def emit(self, record):
        msg = self.format(record) + '\n'
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg):
        self.text_widget.insert(tk.END, msg)
        self.text_widget.see(tk.END)


# ---------------------------------------------------------------------------
# GUI main window
# ---------------------------------------------------------------------------

class DeviceQueryApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Device Query Tool")
        self.geometry("900x700")
        self.resizable(True, True)

        # --- Top input bar ---
        input_frame = tk.Frame(self)
        input_frame.pack(fill=tk.X, padx=10, pady=(10, 0))

        # Row 1: Device ID
        row1 = tk.Frame(input_frame)
        row1.pack(fill=tk.X, pady=(0, 4))

        tk.Label(row1, text="Device ID:", font=("Microsoft YaHei", 11), width=10, anchor="e").pack(side=tk.LEFT)

        self.device_entry = tk.Entry(row1, font=("Consolas", 12), width=30)
        self.device_entry.pack(side=tk.LEFT, padx=5)
        self.device_entry.bind("<Return>", lambda _: self._on_query())

        # Row 2: Router SN
        row2 = tk.Frame(input_frame)
        row2.pack(fill=tk.X)

        tk.Label(row2, text="Router SN:", font=("Microsoft YaHei", 11), width=10, anchor="e").pack(side=tk.LEFT)

        self.router_entry = tk.Entry(row2, font=("Consolas", 12), width=30)
        self.router_entry.pack(side=tk.LEFT, padx=5)
        self.router_entry.bind("<Return>", lambda _: self._on_query())

        # Row 3: SIM ICCID
        row3 = tk.Frame(input_frame)
        row3.pack(fill=tk.X)

        tk.Label(row3, text="SIM ICCID:", font=("Microsoft YaHei", 11), width=10, anchor="e").pack(side=tk.LEFT)

        self.iccid_entry = tk.Entry(row3, font=("Consolas", 12), width=30)
        self.iccid_entry.pack(side=tk.LEFT, padx=5)
        self.iccid_entry.bind("<Return>", lambda _: self._on_query())

        self.query_btn = tk.Button(
            input_frame, text="Query", font=("Microsoft YaHei", 10),
            command=self._on_query, width=8, height=1
        )
        self.query_btn.pack(pady=(8, 0))

        # --- Result output area ---
        self.output = scrolledtext.ScrolledText(
            self, font=("Consolas", 10), wrap=tk.WORD, state=tk.NORMAL,
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4"
        )
        self.output.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Color tags for highlighting Online/Offline status
        self.output.tag_configure("online", foreground="#98c379")
        self.output.tag_configure("offline", foreground="#e06c75")

        # Install logging handler
        handler = TextHandler(self.output)
        logging.getLogger().addHandler(handler)

        # --- Status bar ---
        self.status_var = tk.StringVar(value="Ready")
        status_bar = tk.Label(
            self, textvariable=self.status_var, bd=1, relief=tk.SUNKEN,
            anchor=tk.W, font=("Microsoft YaHei", 9)
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _on_query(self):
        device_id = self.device_entry.get().strip()
        router_sn = self.router_entry.get().strip()
        iccid = self.iccid_entry.get().strip()
        if not device_id and not router_sn and not iccid:
            messagebox.showwarning("Input Error", "Please enter a device ID, router SN, or SIM ICCID!")
            return

        label = device_id or router_sn or iccid
        self.query_btn.config(state=tk.DISABLED)
        self.status_var.set("Querying...")
        sep = "─" * 60
        self.output.insert(tk.END, f"\n{sep}\n")
        self.output.insert(tk.END, f"Start querying: {label}\n")
        self.output.insert(tk.END, f"{sep}\n")
        self.output.see(tk.END)

        threading.Thread(target=self._run_query, args=(device_id, router_sn, iccid), daemon=True).start()

    def _run_query(self, device_id: str, router_sn: str, iccid: str):
        try:
            data = collect_device_data(device_id, router_sn, iccid)
            result_text = format_results(data)
        except Exception as e:
            result_text = f"\n[Exception] {str(e)}\n"

        self.after(0, self._on_query_done, result_text)

    def _on_query_done(self, result_text: str):
        self.output.insert(tk.END, result_text + "\n")
        self._highlight_status()
        self.output.see(tk.END)
        self.query_btn.config(state=tk.NORMAL)
        self.status_var.set("Ready")

    def _highlight_status(self):
        """Apply green/red tags to status/state keywords in the output widget.
        Order matters: longer patterns are processed first so they don't get
        partially over-tagged by shorter substrings (e.g. 'Abnormal/Disconnected'
        before 'Normal')."""
        self.output.tag_configure("online", foreground="#98c379")
        self.output.tag_configure("offline", foreground="#e06c75")
        self.output.tag_configure("warn", foreground="#e5c07b")

        # Red — abnormal / offline / stopped / disconnected
        red_patterns = [
            "Abnormal/Disconnected", "[Offline]", "Never Connected",
            "Abnormal", "Offline", "Disconnected", "Inactive", "Stopped",
        ]
        # Green — normal / online / running / connected
        green_patterns = [
            "[Online]", "Online", "Normal", "Connected", "Running",
        ]
        # Amber — transient / unknown / warning-like
        warn_patterns = [
            "Unknown", "Not Found",
        ]

        for pattern in red_patterns:
            self._tag_pattern(pattern, "offline")
        for pattern in green_patterns:
            self._tag_pattern(pattern, "online")
        for pattern in warn_patterns:
            self._tag_pattern(pattern, "warn")

    def _tag_pattern(self, pattern: str, tag: str):
        """Search for *pattern* in the output widget and apply *tag* to every
        occurrence that is not already covered by a status tag."""
        start = "1.0"
        while True:
            pos = self.output.search(pattern, start, stopindex=tk.END)
            if not pos:
                break
            end = f"{pos}+{len(pattern)}c"
            existing = self.output.tag_names(pos)
            # Skip if any status tag already covers this position
            if not {"online", "offline", "warn"} & set(existing):
                self.output.tag_add(tag, pos, end)
            start = end


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = DeviceQueryApp()
    app.mainloop()

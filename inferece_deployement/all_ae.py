# all_ae.py
# --------------------------------------------------------------------------------------
# Fixes: Keras 3-safe prediction, non-GUI plotting, robust SSH with retries/backoff,
#        safer G-code parsing, thread safety, consistent per-job paths.
#        NEW: figures are saved once per second (atomic) so Streamlit always sees updates.
# --------------------------------------------------------------------------------------
import tempfile
import os
import re
import json
import time
import csv
from pathlib import Path
from threading import Thread, Lock

import numpy as np
import pandas as pd
import paramiko

# --- Matplotlib: force non-GUI backend BEFORE importing pyplot ---
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

# Reduce TF log noise (optional)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import tensorflow as tf  # noqa: E402
import keras             # noqa: E402

from octorest import OctoRest  # noqa: E402
from datetime import datetime

# =================== Shared session config ===================
try:
    with open(r"inferece_deployement\session_config.json", "r") as f:
        session = json.load(f)
except FileNotFoundError:
    raise RuntimeError("Missing session_config.json. Please launch from stream1.py.")

ip_address = session["ip"]
job_folder = session["job_folder"]

# Per-job paths
raw_dir        = os.path.join(job_folder, "raw_images")
processed_dir  = os.path.join(job_folder, "processed_images")
ae_data_path   = os.path.join(job_folder, "AE_data", "ae_hits.tsv")
cv_csv_path    = os.path.join(job_folder, "cv_detections.csv")

# Static images for your frontend
static_dir = Path(r"database\static")
static_dir.mkdir(parents=True, exist_ok=True)
PLOT_WAVEFORM_PATH = static_dir / "plot1.png"
PLOT_GEOMETRY_PATH = static_dir / "plot2.png"

# Ensure per-job directories exist
Path(raw_dir).mkdir(parents=True, exist_ok=True)
Path(processed_dir).mkdir(parents=True, exist_ok=True)
Path(ae_data_path).parent.mkdir(parents=True, exist_ok=True)

# =================== OctoPrint client ===================
def make_client(url, apikey):
    try:
        return OctoRest(url=url, apikey=apikey)
    except Exception as ex:
        print(f"[OctoPrint] connection failed: {ex}")
        return None

client = make_client(f"http://{ip_address}", '0B280554DA16426CB85536D88A82B672')

# =================== AE Model ===================
model_path = r"models\class_bi.h5"
model = keras.models.load_model(model_path, compile=False)

def _predict_scalar(m, inputs):
    """Run model.predict and return a single float scalar (Keras 3 safe)."""
    y = m.predict(inputs, verbose=0)
    if isinstance(y, (list, tuple)):
        y = y[0]
    y = np.asarray(y)
    if y.size == 0:
        raise RuntimeError("Empty prediction output.")
    return float(y.squeeze())

# =================== Shared state ===================
df = pd.DataFrame(columns=['X', 'Y', 'Z'])

# Locks
state_lock = Lock()   # protects df & defect_points
fig1_lock  = Lock()   # protects fig1 (waveform)
fig2_lock  = Lock()   # protects fig2 (geometry)

last_z = 0.0
defect_points = []         # list of (X, Y, Z)
consecutive_defects = 0    # counter

desired_order = [
    'timestamp', 'trai', 'amplitude', 'duration', 'energy', 'rms',
    'rise_time', 'counts', 'samples', 'waveform', 'class', 'probability'
]

# =================== Helpers ===================
_num = r"-?\d+(?:\.\d+)?"

def extract_xyz_from_gcode(gcode_line: str, last_z_val: float):
    """Parse X/Y/Z floats from a G-code line. Keeps last Z if absent."""
    x = y = None
    mx = re.search(rf"\bX({_num})\b", gcode_line)
    my = re.search(rf"\bY({_num})\b", gcode_line)
    mz = re.search(rf"\bZ({_num})\b", gcode_line)

    if mx:
        try: x = float(mx.group(1))
        except Exception: x = None
    if my:
        try: y = float(my.group(1))
        except Exception: y = None
    if mz:
        try: last_z_val = float(mz.group(1))
        except Exception: pass
    return x, y, last_z_val

def _atomic_save_figure(fig, path: Path):
    """
    Save figure atomically and write a .stamp file with UTC ISO time
    so Streamlit can reliably detect freshness.
    Uses a temp file with the SAME extension to avoid Matplotlib format confusion.
    """
    path = Path(path)
    ext = (path.suffix.lower().lstrip(".") or "png")  # e.g., "png", "jpg", ...

    # Make a temp file in the same directory with the same suffix (extension)
    with tempfile.NamedTemporaryFile(delete=False, suffix=path.suffix, dir=path.parent) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Explicitly pass the format so Matplotlib doesn't guess from weird suffixes
        fig.savefig(tmp_path, format=ext)
        os.replace(tmp_path, path)  # atomic replace
    finally:
        # In case something went wrong before replace
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

    # Touch/update a stamp file so the frontend can detect updates
    stamp = path.with_suffix(path.suffix + ".stamp")
    with open(stamp, "w", encoding="utf-8") as f:
        f.write(datetime.utcnow().isoformat() + "Z")

# =================== Plotting ===================
fig1, axs = plt.subplots(2, 1, figsize=(8, 8))     # waveform + dB scatter
fig2 = plt.figure(figsize=(8, 8))                   # 3D geometry
ax3d = fig2.add_subplot(111, projection='3d')

non_def_x, non_def_y, def_x, def_y = [], [], [], []

def update_geometry_plot():
    """Daemon thread: updates the 3D geometry figure (drawing only)."""
    while True:
        try:
            with state_lock:
                df_local = df.copy()
                defect_pts_local = list(defect_points)

            with fig2_lock:
                ax3d.clear()
                if not df_local.empty:
                    ax3d.plot(df_local['X'], df_local['Y'], df_local['Z'], c='r', label='Print Path')
                if defect_pts_local:
                    dx, dy, dz = zip(*defect_pts_local)
                    ax3d.scatter(dx, dy, dz, c='b', marker='o', s=30, label='Defects')

                ax3d.set_xlabel('X'); ax3d.set_ylabel('Y'); ax3d.set_zlabel('Z')
                if ax3d.has_data():
                    ax3d.legend(loc='best')
                fig2.canvas.draw_idle()
        except Exception as e:
            print(f"[PLOT-3D] {e}")
        time.sleep(0.5)  # draw fairly often so the saved image reflects new points

def update_waveform_plots(waveform, defect: bool, timestamp: str, amplitude: float):
    """Draw waveform and dB scatter onto fig1 (drawing only)."""
    try:
        with fig1_lock:
            axs[0].clear()
            axs[0].plot(waveform, color='red' if defect else 'green')
            axs[0].set_title("Raw AE Waveform")
            axs[0].set_xlabel("Sample"); axs[0].set_ylabel("Amplitude")

            amp = float(amplitude) if amplitude is not None else 0.0
            db = 20 * np.log10(max(amp, 1e-12) * 1e6)

            if defect:
                def_x.append(timestamp); def_y.append(db)
            else:
                non_def_x.append(timestamp); non_def_y.append(db)

            axs[1].clear()
            if non_def_x:
                axs[1].scatter(non_def_x, non_def_y, c='blue', s=5, label="Non-Defective")
            if def_x:
                axs[1].scatter(def_x, def_y, c='red',  s=5, label="Defective")
            axs[1].set_xlabel("Time"); axs[1].set_ylabel("dB (ref µV)")
            if non_def_x or def_x:
                axs[1].legend(loc='best')

            fig1.canvas.draw_idle()
    except Exception as e:
        print(f"[PLOT-WF] {e}")

def periodic_plot_saver():
    """Daemon thread: save BOTH figures every 1 second (atomic + stamp)."""
    while True:
        try:
            with fig1_lock:
                _atomic_save_figure(fig1, PLOT_WAVEFORM_PATH)
        except Exception as e:
            print(f"[SAVE fig1] {e}")
        try:
            with fig2_lock:
                _atomic_save_figure(fig2, PLOT_GEOMETRY_PATH)
        except Exception as e:
            print(f"[SAVE fig2] {e}")
        time.sleep(1.0)

# =================== SSH Streaming (robust) ===================
def tail_remote_file_and_update_df(host, username, password, remote_file):
    """Tails OctoPrint's serial.log over SFTP and updates df with XY(Z). Reconnects on failure."""
    global last_z, df
    backoff = 2
    while True:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh_client.connect(
                hostname=host,
                username=username,
                password=password,
                banner_timeout=60,
                auth_timeout=30,
                timeout=30
            )
            sftp_client = ssh_client.open_sftp()
            remote_fh = sftp_client.file(remote_file, 'r')
            remote_fh.seek(0, 2)  # tail from end
            print(f"Monitoring {remote_file} on {host}...")

            backoff = 2  # reset after successful connect
            while True:
                line = remote_fh.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                line = line.strip()
                if not line:
                    continue

                x, y, last_z = extract_xyz_from_gcode(line, last_z)
                if x is not None and y is not None:
                    with state_lock:
                        df = pd.concat(
                            [df, pd.DataFrame({'X': [x], 'Y': [y], 'Z': [last_z]})],
                            ignore_index=True
                        )
        except Exception as e:
            print(f"[SSH tail] {e} — retrying in {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        finally:
            try: ssh_client.close()
            except Exception: pass

def process_record(record: dict):
    """Handle one JSON record from the Pi (spotwave_ae.py output)."""
    global consecutive_defects

    if 'data' not in record or not isinstance(record['data'], list):
        return

    waveform = record.pop("data")
    if not waveform:
        return

    # Derived fields
    try:
        record["rms"] = float((sum(float(x)*float(x) for x in waveform) / len(waveform)) ** 0.5)
    except Exception:
        record["rms"] = 0.0
    record["waveform"] = ",".join(map(str, waveform))

    timestamp = record.get("time")
    if not timestamp:
        return
    record["timestamp"] = timestamp

    # Pull features safely
    def _f(key):
        try:
            return float(record.get(key, 0.0))
        except Exception:
            return 0.0

    sample = {
        'amplitude': _f('amplitude'),
        'duration': _f('duration'),
        'energy': _f('energy'),
        'rms': _f('rms'),
        'rise_time': _f('rise_time'),
        'counts': _f('counts')
    }

    # Model inference
    input_dict = {k: np.array([v], dtype=np.float32) for k, v in sample.items()}
    try:
        prediction = _predict_scalar(model, input_dict)
    except Exception as e:
        print(f"[MODEL] predict error: {e}")
        return

    defect = round(prediction + 0.9) == 1  # preserves your original logic
    record['class'] = 'defected' if defect else 'non-defected'
    record['probability'] = float(prediction)

    # Draw plots
    update_waveform_plots(waveform, defect, timestamp, sample['amplitude'])

    # Mark XYZ for defects
    with state_lock:
        if defect and not df.empty:
            last_vals = df.iloc[-1][['X', 'Y', 'Z']].to_list()
            defect_points.append(tuple(last_vals))
            print(f"[DEFECT] X={last_vals[0]}, Y={last_vals[1]}, Z={last_vals[2]}")
            consecutive_defects += 1
        else:
            consecutive_defects = 0

    if consecutive_defects >= 5 and client:
        try:
            print("[ACTION] 5 consecutive defects detected. Pausing printer.")
            client.pause()
            consecutive_defects = 0
        except Exception as e:
            print(f"[OctoPrint] pause failed: {e}")

    # Persist AE hit
    record['samples'] = len(waveform)
    ordered = {k: record.get(k) for k in desired_order}
    try:
        pd.DataFrame([ordered]).to_csv(
            ae_data_path,
            mode="a",
            header=not os.path.exists(ae_data_path),
            index=False,
            sep="\t",
            quoting=csv.QUOTE_MINIMAL
        )
    except Exception as e:
        print(f"[AE save] {e}")

def stream_from_pi():
    """Runs spotwave_ae.py on the Pi and streams JSONL. Reconnects on failure with backoff."""
    backoff = 2
    while True:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        channel = None
        try:
            ssh.connect(
                ip_address,
                username="pi",
                password="1234",
                banner_timeout=60,
                auth_timeout=30,
                timeout=30
            )
            transport = ssh.get_transport()
            channel = transport.open_session()
            channel.get_pty()
            channel.exec_command("python3 /home/pi/spotwave_ae.py")

            buffer = ""
            backoff = 2  # reset on success
            while not channel.exit_status_ready():
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="ignore")
                    if not chunk:
                        time.sleep(0.1)
                        continue
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            process_record(record)
                        except json.JSONDecodeError:
                            continue
                else:
                    time.sleep(0.2)
        except Exception as e:
            print(f"[SSH stream] {e} — reconnecting in {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        finally:
            try:
                if channel is not None:
                    channel.close()
            except Exception:
                pass
            try:
                ssh.close()
            except Exception:
                pass

# =================== Start everything ===================
if __name__ == "__main__":
    host = ip_address
    username = 'pi'
    password = '1234'
    remote_file = '/home/pi/.octoprint/logs/serial.log'

    Thread(target=tail_remote_file_and_update_df,
           args=(host, username, password, remote_file),
           daemon=True).start()

    Thread(target=update_geometry_plot, daemon=True).start()
    Thread(target=periodic_plot_saver, daemon=True).start()   # <-- save both plots every 1s

    # Blocking loop; Ctrl+C to stop
    stream_from_pi()

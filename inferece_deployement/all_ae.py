# Insert at the top of all_ae.py, all_cv.py, features.py, gcode_server_godot.py
import json
import os

# Load shared session config
try:
    with open(r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\test1\session_config.json", "r") as f:
        session = json.load(f)
except FileNotFoundError:
    raise RuntimeError("Missing session_config.json. Please launch from stream1.py.")

ip_address = session["ip"]
job_folder = session["job_folder"]

# Use these wherever applicable
raw_dir = os.path.join(job_folder, "raw_images")
processed_dir = os.path.join(job_folder, "processed_images")
ae_data_path = os.path.join(job_folder, "AE_data", "ae_hits.tsv")
cv_csv_path = os.path.join(job_folder, "cv_detections.csv")





import paramiko
import time
import pandas as pd
import matplotlib.pyplot as plt
import tensorflow as tf
from threading import Thread
from pathlib import Path
import numpy as np
import keras
import json
import os
from mpl_toolkits.mplot3d import Axes3D
from octorest import OctoRest

# === OctoPrint Setup ===
def make_client(url, apikey):
    try:
        return OctoRest(url=url, apikey=apikey)
    except ConnectionError as ex:
        print(ex)

# For OctoPrint clients:
client = make_client(f"http://{ip_address}", '0B280554DA16426CB85536D88A82B672')

#client = make_client('http://150.250.209.49', '0B280554DA16426CB85536D88A82B672')

# === Model Load ===
model_path = r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\static\models\class_bi.h5"
model = keras.models.load_model(model_path, compile=False)

# === Tracking XYZ from GCODE ===
df = pd.DataFrame(columns=['X', 'Y', 'Z'])
last_z = 0.0

defect_points = []  # (X, Y, Z) for plotting
consecutive_defects = 0  # counter for consecutive defects

local_tsv_path = r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\dynamic\ae_hits.tsv"
desired_order = [
    'timestamp', 'trai', 'amplitude', 'duration', 'energy', 'rms',
    'rise_time', 'counts', 'samples', 'waveform', 'class', 'probability'
]

# === G-code XY Parsing ===
def extract_xyz_from_gcode(gcode_line, last_z):
    x = y = None
    if 'X' in gcode_line:
        x_val = gcode_line.split('X')[1].split()[0].split('*')[0]
        x = float(x_val) if x_val.replace('.', '', 1).isdigit() else None
    if 'Y' in gcode_line:
        y_val = gcode_line.split('Y')[1].split()[0].split('*')[0]
        y = float(y_val) if y_val.replace('.', '', 1).isdigit() else None
    if 'Z' in gcode_line:
        z_val = gcode_line.split('Z')[1].split()[0].split('*')[0]
        last_z = float(z_val) if z_val.replace('.', '', 1).isdigit() else last_z
    return x, y, last_z

# === Plotting Function ===
fig1, axs = plt.subplots(2, 1, figsize=(8, 8))
fig2 = plt.figure(figsize=(8, 8))
ax3d = fig2.add_subplot(111, projection='3d')
non_def_x, non_def_y, def_x, def_y = [], [], [], []

def update_geometry_plot():
    while True:
        ax3d.clear()
        if not df.empty:
            ax3d.plot(df['X'], df['Y'], df['Z'], c='r', label='Print Path')
        if defect_points:
            dx, dy, dz = zip(*defect_points)
            ax3d.scatter(dx, dy, dz, c='b', marker='o', s=30, label='Defects')
        ax3d.set_xlabel('X')
        ax3d.set_ylabel('Y')
        ax3d.set_zlabel('Z')
        ax3d.legend()
        fig2.tight_layout()
        fig2.canvas.draw()
        plt.figure(fig2.number)
        plt.savefig(r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\static\plot2.png")
        time.sleep(1)

# === Stream GCODE from remote ===
def tail_remote_file_and_update_df(host, username, password, remote_file):
    global df, last_z
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh_client.connect(hostname=host, username=username, password=password)
        sftp_client = ssh_client.open_sftp()
        remote_fh = sftp_client.file(remote_file, 'r')
        remote_fh.seek(0, 2)
        print(f"Monitoring {remote_file} on {host}...")

        while True:
            line = remote_fh.readline().strip()
            if line:
                x, y, last_z = extract_xyz_from_gcode(line, last_z)
                if x is not None and y is not None:
                    df = pd.concat([df, pd.DataFrame({'X': [x], 'Y': [y], 'Z': [last_z]})], ignore_index=True)
            time.sleep(0.1)
    except Exception as e:
        print(f"[SSH ERROR] {e}")
    finally:
        ssh_client.close()

# === Unified Processing ===
def process_record(record):
    global df, defect_points, consecutive_defects

    if 'data' not in record or not isinstance(record['data'], list):
        return  # Skip incomplete

    waveform = record.pop("data")
    record["rms"] = (sum(x**2 for x in waveform) / len(waveform)) ** 0.5
    record["waveform"] = ",".join(map(str, waveform))
    timestamp = record.get("time")
    if not timestamp:
        return
    record["timestamp"] = timestamp

    sample = {
        'amplitude': record['amplitude'],
        'duration': record['duration'],
        'energy': record['energy'],
        'rms': record['rms'],
        'rise_time': record['rise_time'],
        'counts': record['counts']
    }

    input_dict = {k: tf.convert_to_tensor([v]) for k, v in sample.items()}
    prediction = model.predict(input_dict, verbose=0)[0][0]
    defect = round(prediction + 0.9) == 1

    record['class'] = 'defected' if defect else 'non-defected'
    record['probability'] = float(prediction)

    # === Plot waveform ===
    axs[0].clear()
    axs[0].plot(waveform, color='red' if defect else 'green')
    axs[0].set_title("Raw AE Waveform")

    db = 20 * np.log10(record['amplitude'] * 1e6)
    if defect:
        def_x.append(timestamp)
        def_y.append(db)
    else:
        non_def_x.append(timestamp)
        non_def_y.append(db)

    axs[1].clear()
    axs[1].scatter(non_def_x, non_def_y, c='blue', s=5, label="Non-Defective")
    axs[1].scatter(def_x, def_y, c='red', s=5, label="Defective")
    axs[1].legend()

    fig1.tight_layout()
    fig1.canvas.draw()
    plt.figure(fig1.number)
    plt.savefig(r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\static\plot1.png")

    if defect and not df.empty:
        last_x, last_y, last_z = df.iloc[-1]
        defect_points.append((last_x, last_y, last_z))
        print(f"[DEFECT] X={last_x}, Y={last_y}, Z={last_z}")
        consecutive_defects += 1
    else:
        consecutive_defects = 0

    if consecutive_defects >= 5:
        try:
            print("[ACTION] 5 consecutive defects detected. Pausing printer.")
            client.pause()
            consecutive_defects = 0
        except Exception as e:
            print(f"[ERROR] Failed to pause printer: {e}")

    record['samples'] = len(waveform)
    ordered = {k: record.get(k) for k in desired_order}
    df_save = pd.DataFrame([ordered])
    df_save.to_csv(local_tsv_path, mode="a", header=not os.path.exists(local_tsv_path), index=False, sep="\t", quoting=1)

# === Stream JSON Records from Pi ===
def stream_from_pi():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip_address, username="pi", password="1234")
    transport = ssh.get_transport()
    channel = transport.open_session()
    channel.get_pty()
    channel.exec_command("python3 /home/pi/spotwave_ae.py")

    buffer = ""
    try:
        while not channel.exit_status_ready():
            if channel.recv_ready():
                chunk = channel.recv(2048).decode("utf-8")
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    try:
                        record = json.loads(line.strip())
                        process_record(record)
                    except json.JSONDecodeError:
                        continue
            else:
                time.sleep(0.5)
    finally:
        channel.close()
        ssh.close()

# === Start Everything ===
host = ip_address
username = 'pi'
password = '1234'
remote_file = '/home/pi/.octoprint/logs/serial.log'

Thread(target=tail_remote_file_and_update_df, args=(host, username, password, remote_file), daemon=True).start()
Thread(target=update_geometry_plot, daemon=True).start()
stream_from_pi()
#plt.show()

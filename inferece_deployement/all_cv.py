# Insert at the top of all_ae.py, all_cv.py, features.py, gcode_server_godot.py
import json
import os
import sys

# Load shared session config
try:
    with open(r"inferece_deployement\session_config.json", "r") as f:
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

import csv
import time
import cv2
import torch
from datetime import datetime
from octorest import OctoRest
from pathlib import Path

# Paths setup (your dynamic DB paths kept as-is)
BASE_DIR = r"database\dynamic"
RAW_DIR = os.path.join(BASE_DIR, "raw_images")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed_images")
CSV_FILE = os.path.join(BASE_DIR, "cv_detections.csv")
STATIC_FLASK_IMG = r"database\static\plot4.png"

# Create folders
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STATIC_FLASK_IMG), exist_ok=True)

# Create CSV if not exists
if not os.path.isfile(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "raw_image_path", "processed_image_path", "defect_class", "x", "y", "width", "height", "confidence"])

# ---------------- YOLOv5 repo/weights ----------------
REPO_ROOT = Path(__file__).resolve().parents[1]
Y5_DIR = REPO_ROOT / "models" / "yolov5"
WEIGHTS = REPO_ROOT / "models" / "best.pt"

if not (Y5_DIR / "hubconf.py").exists():
    raise RuntimeError(
        f"YOLOv5 repo not found at: {Y5_DIR}\n"
        f"Clone it or set Y5_DIR correctly."
    )
if not WEIGHTS.exists():
    raise FileNotFoundError(f"Weights not found at: {WEIGHTS}")

def load_yolov5_model(weights_path: Path, y5_dir: Path):
    """
    Load YOLOv5 with torch.hub while temporarily forcing torch.load(weights_only=False)
    to remain compatible with PyTorch >= 2.6.
    """
    orig_load = torch.load

    def patched_load(*args, **kwargs):
        # Only override if caller didn't specify
        kwargs.setdefault("weights_only", False)
        return orig_load(*args, **kwargs)

    torch.load = patched_load
    try:
        model = torch.hub.load(
            str(y5_dir),
            model='custom',
            path=str(weights_path),
            source='local',
            force_reload=True  # helps avoid stale hub cache
        )
    finally:
        # always restore
        torch.load = orig_load
    return model
# -----------------------------------------------------

def make_client(url, apikey):
    """Create OctoRest client"""
    try:
        return OctoRest(url=url, apikey=apikey)
    except ConnectionError as ex:
        print("Connection failed:", ex)
        return None

def get_printer_state(client):
    return client.job_info().get('state')

def pause_print(client):
    client.pause()

def monitor_and_detect():
    print('...Loading YOLOv5 model...')
    model = load_yolov5_model(WEIGHTS, Y5_DIR)
    # Optional: tweak thresholds
    # model.conf = 0.25
    # model.iou = 0.45
    print('...YOLOv5 model ready...')

    # For OctoPrint clients:
    client = make_client(f"http://{ip_address}", '0B280554DA16426CB85536D88A82B672')
    if not client:
        return

    print('...Connected to OctoPrint...')
    while get_printer_state(client) != 'Printing':
        print('...Still Waiting For Printer...')
        time.sleep(5)

    print('...Scanning Images...')
    buffer = 0

    while True:
        cap = cv2.VideoCapture(f"http://{ip_address}/webcam/?action=stream")
        if not cap.isOpened():
            print("Error: Could not open video stream.")
            break

        ret, frame = cap.read()
        if not ret:
            print("End of stream or error.")
            break

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        raw_path = os.path.join(RAW_DIR, f"{timestamp}_raw.jpg")
        processed_path = os.path.join(PROCESSED_DIR, f"{timestamp}_processed.jpg")

        # Save raw image (your original dual-save kept)
        # cv2.imwrite(raw_path, frame.copy())
        cv2.imwrite(os.path.join(raw_dir, f"{timestamp}_raw.jpg"), frame)

        # Run inference
        results = model(frame)
        dfResults = results.pandas().xywh[0]

        # Annotate frame
        if not dfResults.empty:
            for _, row in dfResults.iterrows():
                xcenter, ycenter = int(row['xcenter']), int(row['ycenter'])
                width, height = int(row['width']), int(row['height'])
                left = int(xenter - width / 2)
                top = int(ycenter - height / 2)
                right = int(xcenter + width / 2)
                bottom = int(ycenter + height / 2)

                cv2.rectangle(frame, (left, top), (right, bottom), (255, 0, 0), 2)
                cv2.putText(frame, row['name'], (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

                # Log detection
                with open(CSV_FILE, mode='a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        timestamp,
                        raw_path,
                        processed_path,
                        row['name'],
                        xcenter,
                        ycenter,
                        width,
                        height,
                        row['confidence']
                    ])

        # Save processed image
        # cv2.imwrite(processed_path, frame)
        cv2.imwrite(os.path.join(processed_dir, f"{timestamp}_processed.jpg"), frame)

        # Save for Flask
        cv2.imwrite(STATIC_FLASK_IMG, frame)

        # Defect logic
        defect_names = dfResults["name"].values if not dfResults.empty else []
        defect_detected = any(d in defect_names for d in ['spaghettification', 'underextrusion', 'overextrusion', 'stringing'])

        if defect_detected:
            print(f"Defect(s) detected: {defect_names}")
            buffer += 1
        else:
            buffer = 0

        if buffer > 2:
            pause_print(client)
            print("Printing paused due to repeated defects.")

        time.sleep(1)

if __name__ == '__main__':
    monitor_and_detect()

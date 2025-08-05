import os
import csv
import time
import cv2
import torch
from datetime import datetime
from octorest import OctoRest


# Paths setup
BASE_DIR = r"C:\Users\djeri\OneDrive\Desktop\3d_printing_loop\AE"
RAW_DIR = os.path.join(BASE_DIR, "raw_images")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed_images")
CSV_FILE = os.path.join(BASE_DIR, "cv_detections.csv")
STATIC_FLASK_IMG = r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\static\plot4.png"

# Create folders
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STATIC_FLASK_IMG), exist_ok=True)

# Create CSV if not exists
if not os.path.isfile(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "raw_image_path", "processed_image_path", "defect_class", "x", "y", "width", "height", "confidence"])


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
    print('...Loading Model...')
    model = torch.hub.load(
        r'C:\Users\djeri\OneDrive\Desktop\3d_printing_loop\yolov5\yolov5',
        model='custom',
        path=r'C:\Users\djeri\OneDrive\Desktop\3d_printing_loop\OneDrive_2025-01-13\01. CODES\01. AI CODES\images\best.pt',
        source='local'
    )

    client = make_client(
        'http://150.250.209.49',
        '0B280554DA16426CB85536D88A82B672'
    )
    if not client:
        return

    print('...Connected to OctoPrint...')
    while get_printer_state(client) != 'Printing':
        print('...Still Waiting For Printer...')
        time.sleep(5)

    print('...Scanning Images...')
    buffer = 0

    while True:
        cap = cv2.VideoCapture('http://150.250.209.49/webcam/?action=stream')
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

        # Save raw image
        cv2.imwrite(raw_path, frame.copy())

        # Run inference
        results = model(frame)
        dfResults = results.pandas().xywh[0]

        # Annotate frame
        if not dfResults.empty:
            for _, row in dfResults.iterrows():
                xcenter, ycenter = int(row['xcenter']), int(row['ycenter'])
                width, height = int(row['width']), int(row['height'])
                left = int(xcenter - width / 2)
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
        cv2.imwrite(processed_path, frame)

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

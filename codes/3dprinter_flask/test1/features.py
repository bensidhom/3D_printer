import json
import os
import time
from octorest import OctoRest
import matplotlib.pyplot as plt

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

# OctoPrint server details
OCTOPRINT_URL = f"http://{ip_address}"
API_KEY = '0B280554DA16426CB85536D88A82B672'

# Initialize data storage for plotting
timestamps = []
bed_temps = []
tool_temps = []

try:
    # Connect to OctoPrint server
    client = OctoRest(url=OCTOPRINT_URL, apikey=API_KEY)

    # Initialize Matplotlib plot
    fig, ax = plt.subplots(figsize=(8, 8))
    bed_line, = ax.plot([], [], label="Bed Temperature")
    tool_line, = ax.plot([], [], label="Tool Temperature")
    ax.set_xlim(0, 300)  # Adjust as needed for your duration
    ax.set_ylim(0, 250)  # Adjust based on max temperature
    ax.set_xlabel("Time (seconds)")
    ax.set_ylabel("Temperature (°C)")
    ax.legend()

    start_time = time.time()

    while True:
        # Fetch temperature data
        temperature = client.printer()["temperature"]
        current_time = time.time() - start_time

        # Extract and store current bed and tool temperatures
        bed_temp = temperature["bed"]["actual"] if "bed" in temperature else None
        tool_temp = temperature["tool0"]["actual"] if "tool0" in temperature else None

        # Update data lists
        timestamps.append(current_time)
        bed_temps.append(bed_temp if bed_temp is not None else 0)
        tool_temps.append(tool_temp if tool_temp is not None else 0)

        # Update plot data
        bed_line.set_xdata(timestamps)
        bed_line.set_ydata(bed_temps)
        tool_line.set_xdata(timestamps)
        tool_line.set_ydata(tool_temps)

        # Adjust plot limits dynamically
        ax.set_xlim(0, max(timestamps) + 10)
        ax.set_ylim(0, max(max(bed_temps), max(tool_temps)) + 10)

        # Redraw the plot
        plt.savefig(r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\static\plot3.png")  # Overwrite the same image every second

        # Wait for 1 second before the next update
        time.sleep(1)
except KeyboardInterrupt:
    print("Real-time plotting stopped.")
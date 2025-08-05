import streamlit as st
import os
import time
from datetime import datetime
import requests
from octorest import OctoRest
import threading
import logging
from logging.handlers import RotatingFileHandler
from PIL import Image
import numpy as np
import json

# Configuration
UPLOAD_FOLDER = r'C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

CONFIG_PATH = r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\test1\session_config.json"

def get_saved_ip():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f).get("ip", "192.168.1.20")
    return "192.168.1.20"

OCTO_URL = f"http://{get_saved_ip()}"
API_KEY = "0B280554DA16426CB85536D88A82B672"
PLOT_PATHS = [
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\static\plot1.png",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\static\plot2.png",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\static\plot3.png",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\static\plot4.png"
]

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler("app.log", maxBytes=5_000_000, backupCount=3)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
logger.handlers = [file_handler]

# Streamlit UI
st.set_page_config(layout="wide", page_title="3D Printer Dashboard")

if 'auto_refresh' not in st.session_state:
    st.session_state.auto_refresh = True

st.title("3D Printer Monitoring & Control")

# IP Input Section
ip_input = st.text_input("Printer IP Address", get_saved_ip())
if st.button("Save IP"):
    with open(CONFIG_PATH, "w") as f:
        json.dump({"ip": ip_input}, f)
    st.success("IP address saved! Please reload to apply changes.")

# Initialize OctoPrint client
try:
    client = OctoRest(url=f"http://{get_saved_ip()}", apikey=API_KEY)
except Exception as e:
    st.error(f"Failed to connect to OctoPrint: {str(e)}")
    client = None

# Background scripts
scripts = [
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\test1\all_ae.py",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\test1\all_cv.py",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\test1\features.py",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\test1\gcode_server_godot.py"
]

def run_script(script_path):
    os.system(f"python {script_path}")

def start_scripts():
    for script in scripts:
        thread = threading.Thread(target=run_script, args=(script,))
        thread.start()

# Start background scripts
threading.Thread(target=start_scripts, daemon=True).start()

# OctoPrint functions
def send_octoprint_command(command, action=None):
    try:
        payload = {"command": command}
        if action:
            payload["action"] = action

        response = requests.post(
            f"http://{get_saved_ip()}/api/job",
            headers={"Content-Type": "application/json", "X-Api-Key": API_KEY},
            json=payload,
            timeout=10
        )
        logger.info(f"Command '{command}' sent. Status: {response.status_code}")
        return response.status_code == 204
    except Exception as e:
        logger.error("Error sending OctoPrint command:", exc_info=e)
        return False

def get_job_status():
    try:
        response = requests.get(
            f"http://{get_saved_ip()}/api/job",
            headers={"X-Api-Key": API_KEY},
            timeout=5
        )
        return response.json()
    except Exception as e:
        logger.error("Error retrieving job status:", exc_info=e)
        return {}

def get_octoprint_files():
    try:
        if client:
            files = client.files()['files']
            return [file['name'] for file in files]
    except Exception as e:
        logger.error("Error retrieving OctoPrint files:", exc_info=e)
    return []

def load_plot_image(index):
    try:
        if os.path.exists(PLOT_PATHS[index]):
            return Image.open(PLOT_PATHS[index])
        return Image.fromarray(np.zeros((300, 400, 3), dtype=np.uint8))
    except Exception as e:
        logger.error(f"Error loading plot {index+1}:", exc_info=e)
        return Image.fromarray(np.zeros((300, 400, 3), dtype=np.uint8))

# Status display
# Status display
status_col1, status_col2, status_col3 = st.columns(3)
job_status = get_job_status() or {}
status = job_status.get("state", "Unknown")
progress_data = job_status.get("progress") or {}
completion = progress_data.get("completion")
completion = completion if isinstance(completion, (int, float)) else 0.0
job_file_data = job_status.get("job") or {}
current_file = job_file_data.get("file", {}).get("name", "---")

status_col1.metric("Status", status)
status_col2.metric("Progress", f"{completion:.1f}%")
status_col3.metric("Current File", current_file)

# File upload section
with st.expander("Upload G-code to OctoPrint"):
    uploaded_file = st.file_uploader("Choose a G-code file", type="gcode")
    if uploaded_file and st.button("Upload File"):
        try:
            local_path = os.path.join(UPLOAD_FOLDER, uploaded_file.name)
            with open(local_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            logger.info(f"Uploading: {uploaded_file.name}")
            if client:
                client.upload(local_path, location="local", select=False)
                st.success("File uploaded successfully!")
            else:
                st.error("OctoPrint connection not available")
        except Exception as e:
            logger.error("Upload error:", exc_info=e)
            st.error(f"Upload failed: {str(e)}")

# Print control section
with st.expander("Print Controls"):
    octoprint_files = get_octoprint_files()
    selected_file = st.selectbox("Select a file to print", [""] + octoprint_files)
    job_name = st.text_input("Job Name", "Unnamed")

    col1, col2, col3, col4 = st.columns(4)

    if col1.button("🚀 Start Print"):
        if selected_file:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            job_folder = os.path.join(r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\Database\dynamic", f"{job_name}_{timestamp}")
            os.makedirs(job_folder, exist_ok=True)

            config = {
                "ip": ip_input,
                "job_name": job_name,
                "timestamp": timestamp,
                "job_folder": job_folder
            }
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f)

            try:
                if client:
                    client.select( selected_file)
                    time.sleep(1)
                    if get_job_status().get("state") == "Operational":
                        if send_octoprint_command("start"):
                            st.success("Print started successfully!")
                        else:
                            st.error("Failed to start print")
                    else:
                        st.warning("Printer is not operational")
            except Exception as e:
                logger.error("Failed to start print:", exc_info=e)
                st.error(f"Failed to start print: {str(e)}")
        else:
            st.warning("Please select a file to print")

    if col2.button("⏸️ Pause"):
        if send_octoprint_command("pause", action="pause"):
            st.success("Print paused")
        else:
            st.error("Failed to pause print")

    if col3.button("▶️ Resume"):
        if send_octoprint_command("pause", action="resume"):
            st.success("Print resumed")
        else:
            st.error("Failed to resume print")

    if col4.button("⛔ Cancel", type="primary"):
        if send_octoprint_command("cancel"):
            st.success("Print cancelled")
        else:
            st.error("Failed to cancel print")

# Monitoring plots
st.header("Monitoring Plots")
plot_col1, plot_col2, plot_col3, plot_col4 = st.columns(4)

with plot_col1:
    st.image(load_plot_image(0), caption="AE Classification", use_container_width=True)
with plot_col2:
    st.image(load_plot_image(1), caption="AE Detection", use_container_width=True)
with plot_col3:
    st.image(load_plot_image(2), caption="Temperature", use_container_width=True)
with plot_col4:
    st.image(load_plot_image(3), caption="YOLO Detection", use_container_width=True)

st.session_state.auto_refresh = st.checkbox("Auto-refresh status", st.session_state.auto_refresh)
if st.session_state.auto_refresh:
    time.sleep(5)
    st.rerun()

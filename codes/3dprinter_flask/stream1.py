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

# Configuration
UPLOAD_FOLDER = r'C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

OCTO_URL = "http://150.250.209.49"
API_KEY = "0B280554DA16426CB85536D88A82B672"
PLOT_PATHS = [
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\static\plot1.png",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\static\plot2.png",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\static\plot3.png",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\static\plot4.png"
]

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler("app.log", maxBytes=5_000_000, backupCount=3)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
logger.handlers = [file_handler]

# Initialize OctoPrint client
try:
    client = OctoRest(url=OCTO_URL, apikey=API_KEY)
except Exception as e:
    st.error(f"Failed to connect to OctoPrint: {str(e)}")
    client = None

# Background scripts
scripts = [
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\all_ae.py",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\all_cv.py",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\features.py",
    r"C:\Users\djeri\OneDrive\Desktop\3dprinter_flask\gcode_server_godot.py"
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
            f"{OCTO_URL}/api/job",
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
            f"{OCTO_URL}/api/job",
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
    """Load plot image with error handling"""
    try:
        if os.path.exists(PLOT_PATHS[index]):
            return Image.open(PLOT_PATHS[index])
        # Return blank image if file doesn't exist
        return Image.fromarray(np.zeros((300, 400, 3), dtype=np.uint8))
    except Exception as e:
        logger.error(f"Error loading plot {index+1}:", exc_info=e)
        return Image.fromarray(np.zeros((300, 400, 3), dtype=np.uint8))

# Streamlit UI
st.set_page_config(layout="wide", page_title="3D Printer Dashboard")

# Session state for auto-refresh
if 'auto_refresh' not in st.session_state:
    st.session_state.auto_refresh = True

# Title and status
st.title("3D Printer Monitoring & Control")

# Status display
status_col1, status_col2, status_col3 = st.columns(3)
job_status = get_job_status()
status_col1.metric("Status", job_status.get("state", "Unknown"))
status_col2.metric("Progress", f"{job_status.get('progress', {}).get('completion', 0):.1f}%")
status_col3.metric("Current File", job_status.get("job", {}).get("file", {}).get("name", "---"))

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
            job_folder = os.path.join(r"C:\Users\djeri\OneDrive\Desktop\3d_printing_loop\AE", f"{job_name}_{timestamp}")
            os.makedirs(job_folder, exist_ok=True)
            logger.info(f"Job folder created: {job_folder}")
            
            try:
                if client:
                    client.select(selected_file, location="local")
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

# Load and display plot images
with plot_col1:
    st.image(load_plot_image(0), caption="AE Classification", use_container_width=True)
with plot_col2:
    st.image(load_plot_image(1), caption="AE Detection", use_container_width=True)
with plot_col3:
    st.image(load_plot_image(2), caption="Temperature", use_container_width=True)
with plot_col4:
    st.image(load_plot_image(3), caption="YOLO Detection", use_container_width=True)

# Auto-refresh toggle
st.session_state.auto_refresh = st.checkbox("Auto-refresh status", st.session_state.auto_refresh)

# Auto-refresh logic
if st.session_state.auto_refresh:
    time.sleep(5)
    st.rerun()
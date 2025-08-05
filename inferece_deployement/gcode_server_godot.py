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






import re
import socket
import threading
import time
import struct
import math
import os
import paramiko

# Global variable to control the server shutdown
server_running = True

# SSH credentials for the Raspberry Pi
ssh_host = ip_address  # Replace with your Raspberry Pi's IP or hostname
ssh_port = 22
ssh_username = 'pi'  # Default username for Raspberry Pi
ssh_password = '1234'  # Replace with your Raspberry Pi's password
# Path to the log file on the Raspberry Pi
remote_log_file_path = '/home/pi/.octoprint/logs/serial.log'  # Adjust the path as needed

def extract_coordinates_and_speed(gcode_line):
    """
    Extract X, Y, Z coordinates, speed (F), and extrusion (E) from a single line of G-code.
    Returns a tuple (x, y, z, speed, extrusion) where x, y, z, speed, and extrusion are floats or None if not found.
    """
    x_match = re.search(r'X(-?\d*\.\d+|-?\d+)', gcode_line)
    y_match = re.search(r'Y(-?\d*\.\d+|-?\d+)', gcode_line)
    z_match = re.search(r'Z(-?\d*\.\d+|-?\d+)', gcode_line)
    speed_match = re.search(r'F(\d*\.\d+|\d+)', gcode_line)
    extrusion_match = re.search(r'E(-?\d*\.\d+|-?\d+)', gcode_line)
    
    x = float(x_match.group(1)) if x_match else None
    y = float(y_match.group(1)) if y_match else None
    z = float(z_match.group(1)) if z_match else None
    speed = float(speed_match.group(1)) if speed_match else None
    extrusion = float(extrusion_match.group(1)) if extrusion_match else None

    return (x, y, z, speed, extrusion)

def read_new_gcode_lines_remote(ssh_client, file_path, last_position):
    """
    Read new G-code lines from the remote log file that have been added since the last read.
    Returns a tuple (new_lines, new_position), where new_lines is a list of new G-code lines
    and new_position is the updated file position.
    """
    new_lines = []
    try:
        # Open an SFTP session
        sftp = ssh_client.open_sftp()
        with sftp.open(file_path, 'r') as file:
            file.seek(last_position)  # Move to the last read position
            new_lines = file.readlines()  # Read all new lines
            new_position = file.tell()  # Update the last read position
        sftp.close()
        return new_lines, new_position
    except Exception as e:
        print(f"Error reading remote file: {e}")
        return [], last_position

def interpolate_points(start, end, num_points):
    """
    Interpolate a number of points between start and end coordinates.
    """
    start_x, start_y, start_z, start_e = start
    end_x, end_y, end_z, end_e = end
    
    points = []
    
    for i in range(num_points + 1):
        try:
            t = i / num_points
            x = start_x + t * (end_x - start_x)
            y = start_y + t * (end_y - start_y)
            z = start_z + t * (end_z - start_z)
            e = start_e + t * (end_e - start_e)
        except:
            x = end_x
            y = end_y
            z = end_z
            e = end_e
        points.append((x, y, z, e))
    
    return points

def format_message(header, coord, speed, extrusion):
    """
    Formats the coordinate message into a fixed-length 1024-byte format.
    Includes X, Y, Z, speed (S), and extrusion (E) values.
    """
    x, y, z = coord
    print(x, "\t", y, "\t", z, "\t", speed, "\t", extrusion)

    # Create a 1024-byte message
    message = bytearray(1024)  # Initialize a bytearray of 1024 bytes

    # Header (first 3 bytes)
    header_bytes = header.encode('utf-8')[:3]
    message[0:3] = header_bytes.ljust(3, b'\x00')
    
    # Number of variables (next byte)
    message[3] = 5  # Number of variables (X, Y, Z, S, E)
    
    # Coordinates and additional values (next 20 bytes, 4 bytes each for X, Y, Z, S, E)
    coord_bytes = struct.pack('<fffff', x, y, z, speed, extrusion)  # Pack X, Y, Z, S, E as little-endian floats
    message[4:24] = coord_bytes  # Assign to the appropriate slice of the message

    return message

def handle_client(client_socket, ssh_client):
    """
    Handle communication with a single client.
    """
    header = "CRD"  # Header to be added before coordinates
    
    # Initialize X, Y, Z, speed, and extrusion with default values
    X, Y, Z, S, E = [0], [0], [0], [1000], [0]  # Initial values for X, Y, Z, speed, and extrusion
    
    last_time = time.time()
    last_coord = (X[-1], Y[-1], Z[-1], E[-1], S[-1])  # Initialize last_coord with initial values

    # Track the last read position in the log file
    last_position = 0

    # Skip old lines on startup
    sftp = ssh_client.open_sftp()
    with sftp.open(remote_log_file_path, 'r') as file:
        file.seek(0, os.SEEK_END)  # Move to the end of the file
        last_position = file.tell()  # Update the last read position
    sftp.close()

    while server_running:
        # Read new lines from the remote log file
        new_lines, last_position = read_new_gcode_lines_remote(ssh_client, remote_log_file_path, last_position)

        for line in new_lines:
            if 'G1' in line:
                # Extract the G-code part after the ">>>"
                gcode_part = line.split('G1')[-1].strip()
                coord = extract_coordinates_and_speed(gcode_part)
                # Ensure X, Y, Z are not None
                # Update X, Y, Z, speed, and extrusion if new values are found
                if coord[0] is not None:
                    X.append(coord[0])
                if coord[1] is not None:
                    Y.append(coord[1])
                if coord[2] is not None:
                    Z.append(coord[2])
                if coord[3] is not None:
                    S.append(coord[3])
                if coord[4] is not None:
                    E.append(coord[4])

                # Use the latest values for interpolation
                current_coord = (X[-1], Y[-1], Z[-1], E[-1], S[-1])
                print(current_coord)

                if last_coord[4] is not None:  # Ensure speed is available
                    # Calculate distance and time delay based on speed
                    distance = ((current_coord[0] - last_coord[0]) ** 2 +
                                (current_coord[1] - last_coord[1]) ** 2 +
                                (current_coord[2] - last_coord[2]) ** 2) ** 0.5
                    time_delay = distance / (last_coord[4]/60)  # Speed in mm/min, convert to mm/sec
                    num_points = int(math.ceil(time_delay*50))  # Number of points to interpolate
                    points = interpolate_points((last_coord[0], last_coord[1], last_coord[2], last_coord[3]),
                                                (current_coord[0], current_coord[1], current_coord[2], current_coord[3]),
                                                num_points)
                    
                    for point in points:
                        if not server_running:
                            break
                        
                        # Include speed and extrusion in the message
                        message_bytes = format_message(header, (point[0], point[1], point[2]), current_coord[4], current_coord[3])
                        try:
                            client_socket.sendall(message_bytes)
                        except socket.error as e:
                            print(f"Socket error: {e}")
                            break
                        
                        time.sleep(0.01)
                    
                    last_coord = current_coord  # Update last_coord for the next iteration
                    last_time = time.time()
        
        time.sleep(0.1)  # Wait before checking the log file again

    client_socket.close()

def start_tcp_server(host, port):
    """
    Starts a TCP server that listens for incoming connections and handles clients.
    """
    global server_running
    
    # Establish SSH connection to the Raspberry Pi
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh_client.connect(ssh_host, port=ssh_port, username=ssh_username, password=ssh_password)
        print(f"Connected to Raspberry Pi at {ssh_host}")
    except Exception as e:
        print(f"Failed to connect to Raspberry Pi: {e}")
        return

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((host, port))
        server_socket.listen()
        print(f"Server listening on {host}:{port}...")
        
        while server_running:
            try:
                client_socket, client_address = server_socket.accept()
                print(f"Connection from {client_address}")
                
                # Handle client in a new thread
                client_handler = threading.Thread(target=handle_client, args=(client_socket, ssh_client))
                client_handler.start()
            except socket.error as e:
                print(f"Socket error: {e}")
                break
    
    print("Server is shutting down...")
    ssh_client.close()

def main():
    # Configuration
    tcpip_host = '127.0.0.1'  
    tcpip_port = 50003         

    try:
        # Start the server
        start_tcp_server(tcpip_host, tcpip_port)
    except KeyboardInterrupt:
        # Handle server shutdown on keyboard interrupt
        global server_running
        server_running = False

if __name__ == '__main__':
    main()
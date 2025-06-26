# Importing the required libraries

import tensorflow as tf
from pathlib import Path
import vallenae as vae
import keras
import time
import octoRest

model = keras.models.load_model(r"C:/Users/Aaron/Desktop/3DPrintingMonitoringSystem/3DPrMonSys/AcousticModel/Models/class_bi.h5") #or .h5 Path for model

i=0
x=[]
z=[]

Client = octoRest.make_client('http://127.0.0.1:5000/#temp',
                                  '403A165A87B947F78542F056D8F3F369')  # replace with the url of octoprint and apikey(found in the settings)
print('...Connected to Octoprint...')
while octoRest.state(Client) != 'Printing from SD':  # Holds on this line until the printer is Printing
    time.sleep(5)
    print('...Still Waiting For Printer...')

while octoRest.state(Client) == 'Printing from SD':
    PRIDB  = Path(r'C:/Users/Aaron/Desktop/3DPrintingMonitoringSystem/3DPrMonSys/AcousticModel/TestData/print2.pridb//') #Path For database
    with vae.io.PriDatabase(PRIDB) as pridb:
        full_df = pridb.read_hits()
    filtered_df = full_df[["amplitude","duration", "energy","rms", "rise_time","counts"]]

    #x=filtered_df.values[i]
    sample = {
    'amplitude':filtered_df.values[i][0],
    'duration':filtered_df.values[i][1],
    'energy':filtered_df.values[i][2],
    'rms':filtered_df.values[i][3],
    'rise_time':filtered_df.values[i][4],
    'counts':filtered_df.values[i][5]
         }

    input_dict = {name: tf.convert_to_tensor([value]) for name, value in sample.items()}
    predictions = model.predict(input_dict)
    #print("label: ",pd.Series(predictions[0]).idxmax()) Change this for when not binary
    #print("label: ",round(predictions[0][0]))
    print(predictions)

    #Take Action
    if round(predictions[0][0])==1:
           octoRest.pause(Client)  # Pause the print job if 5 defects detected consecutively

    i=i+1
    if i==len(filtered_df):
        while True:
            PRIDB  = Path(r'C:/Users/Aaron/Desktop/3DPrintingMonitoringSystem/3DPrMonSys/AcousticModel/TestData/print2.pridb//') #Path for database
            with vae.io.PriDatabase(PRIDB) as pridb:
                full_df = pridb.read_hits()
            filtered_df = full_df[["amplitude","duration", "energy","rms", "rise_time","counts"]]
            if i< len(filtered_df):
                break


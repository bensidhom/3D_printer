import octoRest
import imageDownloader
import time
import torch
#import pandas as pd

if __name__ == '__main__':

    # Define the path to the model (.pt File) 
    print('...Loading Model...')
    model = torch.hub.load(r'c:\Users\Aaron\Desktop\3DPrintingMonitoringSystem\3DPrMonSys\yolov5\\', 'custom', 
                       path= r'c:\Users\Aaron\Desktop\3DPrintingMonitoringSystem\3DPrMonSys\LocalModel\best.pt\\', source='local') 
    Name = 'Test'  # replace with the file name for the photos
    n = 1
    buffer = 0
    Client = octoRest.make_client('http://127.0.0.1:5000/#temp',
                                  '403A165A87B947F78542F056D8F3F369')  # replace with the url of octoprint and apikey(found in the settings)
    print('...Connected to Octoprint...')
    while octoRest.state(Client) != 'Printing from SD':  # Holds on this line until the printer is Printing
        time.sleep(5)
        print('...Still Waiting For Printer...')

    print('...Scanning Images...')
    while octoRest.state(Client) == 'Printing from SD':  # Loops while the printer is printing
        imageDownloader.image_download('http://127.0.0.1:8888/out.jpg', 
                                       Name + str(n))  # Replace with the url of the snapshot   
        path = ('/Users/Aaron/Desktop/3DPrintingMonitoringSystem/3DPrMonSys/FullLoopTrial/',Name + str(n),'.jpg')  # Define the path to save the image
        path = ''.join(path)  # Convert from raw string to string
        inference = model(path)  # Run an inference on the image
        #inference.show()
        
        #Initialize a dataframe - might not need this anymore - I just check if it is empty
       # d = {'xcenter': [0, 0], 'ycenter': [0, 0], 'width': [0, 0], 'height': [0, 0], 'confidence': [0, 0], 'class': [0, 0], 'name': [0, 0]}
       # dfResults = pd.DataFrame(data=d)
        dfResults = inference.pandas().xywh[0]
        
        # Check if the dataframe is empty
        if len(dfResults) > 0:
            defect = str(dfResults["name"].values[0])
        else:
            defect = 'none'
        # print(defect)

        if 'spaghettification' in defect or 'underextrusion' in defect or 'overextrusion' in defect or 'stringing' in defect:  # Check if the inference contains defects
            print('defect:')
            if 'spaghettification' in defect:
                print('spaghettification')
            if 'underextrusion' in defect:
                print('underextrusion')
            if 'overextrusion' in defect:
                print('overextrusion') 
            if 'stringing' in defect:
                print('stringing')
            buffer += 1  # Add 1 to buffer when defect is detected
        else:
            buffer = 0  # Reset buffer to 0 if defect is not detected

        if buffer > 0:
           octoRest.pause(Client)  # Pause the print job if 5 defects detected consecutively

        if n > 5:
            imageDownloader.image_delete(Name + str(n - 5))  # Delete previous images to preserve space

        n = n + 1  # Add 1 to file name
        time.sleep(1)  # replace with seconds between each snapshot

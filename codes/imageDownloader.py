import urllib.request
import pathlib


folder = r'C:\Users\Aaron\Desktop\3DPrintingMonitoringSystem\3DPrMonSys\FullLoopTrial\\'  # replace with folder path of where to save photos (must already have been created)


def image_download(url, name):  # Download an image to a given location from a given URL

    imgURL = url
    fileLocation = (folder, name, '.jpg')
    fileLocation = ''.join(fileLocation)
    urllib.request.urlretrieve(imgURL, fileLocation)


def image_delete(name):  # Delete an image from a certain path

    fileLocation = (folder, name, '.jpg')
    fileLocation = ''.join(fileLocation)
    fileLocation = pathlib.Path(fileLocation)
    pathlib.Path.unlink(fileLocation)

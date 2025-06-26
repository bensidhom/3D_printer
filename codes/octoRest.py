from octorest import OctoRest


def make_client(url, apikey):
    """Creates and returns an instance of the OctoRest client.

    Args:
        url - the url to the OctoPrint server
        apikey - the apikey from the OctoPrint server found in settings
    """
    try:
        client = OctoRest(url=url, apikey=apikey)
        return client
    except ConnectionError as ex:
        # Handle exception as you wish
        print(ex)


def state(client):
    """Returns the current state of the printer

    Args:
        client - the OctoRest client
    """
    info = OctoRest.job_info(client)
    return info.get('state')


def pause(client):
    """Pauses the print job

    Args:
        client - the OctoRest client
    """
    OctoRest.pause(client)


def file_names(client):
    """Retrieves the G-code file names from the
    OctoPrint server and returns a string message listing the
    file names.

    Args:
        client - the OctoRest client
    """
    message = "The GCODE files currently on the printer are:\n\n"
    for k in client.files()['files']:
        message += k['name'] + "\n"
    print(message)


def tempup(client):
    """Increases the Nozzle Temp to 220 degrees"""

    OctoRest.tool_target(
        self=client,
        targets= 220
        )
    
def flowup(client):
    """Increases the Flowrate"""

    OctoRest.flowrate(
        self=client,
        factor= 110
        )

def flowdown(client):
    """Decreases the Flowrate"""

    OctoRest.flowrate(
        self=client,
        factor= 90
        )

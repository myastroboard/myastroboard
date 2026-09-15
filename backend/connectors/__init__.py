from connectors.allsky_connector import AllSkyConnector
from connectors.myastroshine_connector import MyAstroShineConnector

REGISTRY = {
    "allsky": AllSkyConnector,
    "myastroshine": MyAstroShineConnector,
}

from connectors.allsky_connector import AllSkyConnector
from connectors.mqtt_connector import MqttConnector
from connectors.myastroshine_connector import MyAstroShineConnector

REGISTRY = {
    "allsky": AllSkyConnector,
    "myastroshine": MyAstroShineConnector,
    "mqtt": MqttConnector,
}

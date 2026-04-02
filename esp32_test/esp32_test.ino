#include <WiFi.h>
#include <PubSubClient.h>

const char* ssid = "iot-ict-lab24g";
const char* password_wifi = "iot#labclass";

const char* mqtt_server = "192.168.1.144";
const int mqtt_port = 1883;

const char* DEVICE_ID = "d_org_a14c3508_dev_714bab86";
const char* mqtt_username = "d_org_a14c3508_dev_714bab86";
const char* mqtt_password = "836f6ebd9ace4dd5";

WiFiClient espClient;
PubSubClient client(espClient);

void setup_wifi() {
    WiFi.begin(ssid, password_wifi);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("WiFi connected");
}

void reconnect() {
    while (!client.connected()) {
        Serial.print("Attempting MQTT connection...");
        if (client.connect(DEVICE_ID, mqtt_username, mqtt_password)) {
            Serial.println("Connected!");
            client.publish("organizations/org_a14c3508/devices/dev_714bab86/data", "{\"status\":\"online\"}");
        } else {
            Serial.print("failed, rc=");
            Serial.print(client.state());
            delay(2000);
        }
    }
}

void setup() {
    Serial.begin(115200);
    setup_wifi();
    client.setServer(mqtt_server, mqtt_port);
}

void loop() {
    if (!client.connected()) {
        reconnect();
    }
    client.loop();
}

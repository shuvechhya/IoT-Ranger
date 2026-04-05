# IoT Platform API Documentation

## Base URL

```
http://YOUR_SERVER:3000
```

## Authentication

- No authentication required for API calls (internal use)
- MQTT uses per-device credentials

---

## Endpoints

### 1. List Organizations

```http
GET /organizations
```

**Response:**

```json
[
  {"id": "org_xxx", "name": "My Org"},
  {"id": "org_yyy", "name": "Another Org"}
]
```

### 2. Create Organization

```http
POST /organizations
Content-Type: application/json

{"name": "My Organization"}
```

**Response:**

```json
{"id": "org_xxx", "name": "My Organization"}
```

### 3. List Devices in Organization

```http
GET /organizations/{org_id}/devices
```

**Response:**

```json
[
  {
    "id": "dev_xxx",
    "name": "ESP32 Sensor",
    "mqtt_username": "d_org_xxx_dev_xxx",
    "org_id": "org_xxx"
  }
]
```

### 4. Create Device

```http
POST /organizations/{org_id}/devices
Content-Type: application/json

{"name": "ESP32 Sensor"}
```

**Response:**

```json
{
  "id": "dev_xxx",
  "name": "ESP32 Sensor",
  "org_id": "org_xxx",
  "mqtt_username": "d_org_xxx_dev_xxx",
  "mqtt_password": "raw_password"  // Save this! Only shown once
}
```

### 5. MQTT Authentication (Internal)

```http
POST /mqtt/auth
Content-Type: application/x-www-form-urlencoded

username=d_org_xxx_dev_xxx&password=raw_password
```

**Response:**

```json
{"result": "allow"}  // or {"result": "deny"}
```

---

## WebSocket API

### Connection

```javascript
const ws = new WebSocket('ws://YOUR_SERVER:3000/ws/{org_id}');
```

### Server → Client Messages

**1. Initial Device List (on connect)**

```json
{
  "type": "init",
  "devices": [
    {"id": "dev_xxx", "name": "Sensor 1"},
    {"id": "dev_yyy", "name": "Sensor 2"}
  ]
}
```

**2. Device Online/Offline Status**

```json
{
  "type": "device_status",
  "device_id": "dev_xxx",
  "online": true
}
```

**3. Device Data Received**

```json
{
  "type": "device_data",
  "device_id": "dev_xxx",
  "payload": "{\"temp\": 25.5, \"humidity\": 60}",
  "timestamp": "2024-01-15T10:30:00"
}
```

---

## MQTT Configuration for Devices

| Setting         | Value                                             |
| --------------- | ------------------------------------------------- |
| Broker          | YOUR_SERVER_IP                                    |
| Port            | 1883                                              |
| Username        | From device creation response                     |
| Password        | From device creation response                     |
| Topic (publish) | `organizations/{org_id}/devices/{device_id}/data` |

### Example ESP32 Code

```cpp
#include <PubSubClient.h>

const char* mqtt_server = "YOUR_SERVER_IP";
const int mqtt_port = 1883;
const char* mqtt_user = "d_org_xxx_dev_xxx";
const char* mqtt_pass = "password_from_api";
const char* mqtt_topic = "organizations/org_xxx/devices/dev_xxx/data";

WiFiClient espClient;
PubSubClient client(espClient);

void setup() {
  client.setServer(mqtt_server, mqtt_port);
}

void loop() {
  if (!client.connected()) {
    client.connect("d_org_xxx_dev_xxx", mqtt_user, mqtt_pass);
  }
  // Publish sensor data
  client.publish(mqtt_topic, "{\"temp\": 25.5}");
  delay(5000);
}
```

---

## Error Responses

| Status | Meaning                       |
| ------ | ----------------------------- |
| 200    | Success                       |
| 404    | Organization/Device not found |
| 422    | Validation error              |

---

## Rate Limits

- No rate limits (internal use)
- Consider adding if exposed publicly

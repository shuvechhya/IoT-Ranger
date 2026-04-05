import requests

from app.config import EMQX_API_URL, EMQX_PASS, EMQX_USER, WEBHOOK_SECRET


def setup_emqx():
    """Configure EMQX HTTP authentication and webhook rules."""
    try:
        login_resp = requests.post(
            f"{EMQX_API_URL}/api/v5/login",
            json={"username": EMQX_USER, "password": EMQX_PASS},
            timeout=10,
        )
        if login_resp.status_code != 200:
            print(f"Failed to login to EMQX API: {login_resp.status_code}")
            return

        token = login_resp.json().get("token", "")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Configure HTTP authentication
        http_auth_data = {
            "mechanism": "password_based",
            "backend": "http",
            "method": "post",
            "url": "http://backend:3000/mqtt/auth",
            "headers": {"Content-Type": "application/json"},
            "body": {"username": "${username}", "password": "${password}"},
            "enable": True,
            "connect_timeout": 5000,
            "request_timeout": 5000,
        }
        auth_resp = requests.post(
            f"{EMQX_API_URL}/api/v5/authentication",
            headers=headers,
            json=http_auth_data,
            timeout=10,
        )
        print(f"HTTP auth configured: {auth_resp.status_code}")

        # Create webhook connector
        connector_data = {
            "name": "http_webhook_connector",
            "type": "webhook",
            "server": "http://backend:3000",
            "headers": {
                "Content-Type": "application/json",
                "X-Webhook-Secret": WEBHOOK_SECRET,
            },
            "connect_timeout": 5000,
            "request_timeout": 5000,
            "enable_pipelining": 100,
        }
        requests.post(
            f"{EMQX_API_URL}/api/v5/connectors",
            headers=headers,
            json=connector_data,
            timeout=10,
        )
        print("HTTP webhook connector created")

        # Delete old rules
        rules_resp = requests.get(f"{EMQX_API_URL}/api/v5/rules", headers=headers, timeout=10)
        if rules_resp.status_code == 200:
            for rule in rules_resp.json().get("data", []):
                requests.delete(
                    f"{EMQX_API_URL}/api/v5/rules/{rule['id']}", headers=headers, timeout=10
                )

        webhook_action = lambda event_sql, rule_name: {
            "name": rule_name,
            "sql": f'SELECT * FROM "{event_sql}"',
            "actions": [{
                "function": "webhook",
                "args": {
                    "connector": "http_webhook_connector",
                    "url": "http://backend:3000/webhook/emqx/events",
                    "method": "post",
                    "body": {
                        "event": "${event}",
                        "clientid": "${clientid}",
                        "username": "${username}",
                        "timestamp": "${timestamp}",
                    },
                },
            }],
        }

        for sql, name in [
            ("client.connected", "http_client_connected"),
            ("client.disconnected", "http_client_disconnected"),
        ]:
            resp = requests.post(
                f"{EMQX_API_URL}/api/v5/rules",
                headers=headers,
                json=webhook_action(sql, name),
                timeout=10,
            )
            print(f"{name} rule created: {resp.status_code}")

    except Exception as e:
        print(f"Failed to setup EMQX: {e}")

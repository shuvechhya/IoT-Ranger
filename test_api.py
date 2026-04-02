import requests
import json

BASE_URL = "http://localhost:8000"

class TestIoTAPI:
    def __init__(self):
        self.token = None
        self.project_id = None
        self.device_id = None

    def test_register_user(self):
        """Test user registration"""
        response = requests.post(f"{BASE_URL}/auth/register", json={
            "username": "apitest",
            "email": "apitest@test.com",
            "password": "test123"
        })
        print(f"Register: {response.status_code} - {response.json()}")
        assert response.status_code == 200
        return response.json()

    def test_login_user(self):
        """Test user login"""
        response = requests.post(f"{BASE_URL}/auth/login", json={
            "email": "apitest@test.com",
            "password": "test123"
        })
        print(f"Login: {response.status_code} - {response.json()}")
        assert response.status_code == 200
        self.token = response.json()["access_token"]
        return self.token

    def create_project(self):
        """Test creating a project"""
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.post(f"{BASE_URL}/projects", json={
            "name": "Test Project"
        }, headers=headers)
        print(f"Create Project: {response.status_code} - {response.json()}")
        assert response.status_code == 200
        self.project_id = response.json()["id"]
        return self.project_id

    def list_projects(self):
        """Test listing projects"""
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(f"{BASE_URL}/projects", headers=headers)
        print(f"List Projects: {response.status_code} - {response.json()}")
        assert response.status_code == 200

    def create_device(self):
        """Test creating a device"""
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.post(
            f"{BASE_URL}/projects/{self.project_id}/devices",
            json={"name": "Test Device"},
            headers=headers
        )
        print(f"Create Device: {response.status_code} - {response.json()}")
        assert response.status_code == 200
        self.device_id = response.json()["id"]
        return self.device_id

    def list_devices(self):
        """Test listing devices"""
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(
            f"{BASE_URL}/projects/{self.project_id}/devices",
            headers=headers
        )
        print(f"List Devices: {response.status_code} - {response.json()}")
        assert response.status_code == 200

    def get_device_status(self):
        """Test getting device status"""
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(
            f"{BASE_URL}/devices/{self.device_id}/status",
            headers=headers
        )
        print(f"Device Status: {response.status_code} - {response.json()}")
        assert response.status_code == 200

    def run_all_tests(self):
        print("=" * 50)
        print("Running API Tests")
        print("=" * 50)
        
        self.test_register_user()
        self.test_login_user()
        self.create_project()
        self.list_projects()
        self.create_device()
        self.list_devices()
        self.get_device_status()
        
        print("=" * 50)
        print("All tests passed!")
        print("=" * 50)

if __name__ == "__main__":
    test = TestIoTAPI()
    test.run_all_tests()
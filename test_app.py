import pytest
from fastapi.testclient import TestClient
from datetime import date, timedelta
import os
import sqlite3

os.environ["DB_PATH"] = "test_members.db"
os.environ["MOCK_AI"] = "true"

# Now import from main
from main import app, init_db, calculate_days_until_birthday, seed_data, get_db

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    if os.path.exists("test_members.db"):
        os.remove("test_members.db")
    init_db()
    seed_data()
    yield
    if os.path.exists("test_members.db"):
        os.remove("test_members.db")



client = TestClient(app)


def test_add_valid_member():
    response = client.post("/members", json={
        "first_name": "Test",
        "last_name": "User",
        "birth_date": "1990-01-01",
        "country": "USA",
        "city": "Boston"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["first_name"] == "Test"
    assert data["last_name"] == "User"


def test_add_underage_member():
    today = date.today()
    recent_date = today - timedelta(days=365 * 10)

    response = client.post("/members", json={
        "first_name": "Young",
        "last_name": "Person",
        "birth_date": recent_date.strftime("%Y-%m-%d"),
        "country": "USA",
        "city": "Boston"
    })
    assert response.status_code == 422
    assert "18 years old" in response.text


def test_duplicate_member():
    member_data = {
        "first_name": "Duplicate",
        "last_name": "Test",
        "birth_date": "1985-05-15",
        "country": "UK",
        "city": "Manchester"
    }

    response1 = client.post("/members", json=member_data)
    assert response1.status_code == 201

    response2 = client.post("/members", json=member_data)
    assert response2.status_code == 400
    assert "already exists" in response2.json()["detail"]


def test_list_members():
    response = client.get("/members")
    assert response.status_code == 200
    members = response.json()
    assert isinstance(members, list)
    assert len(members) > 0


def test_sort_by_birthday():
    response = client.get("/members?sort_by_birthday=true")
    assert response.status_code == 200
    members = response.json()

    if len(members) > 1:
        for i in range(len(members) - 1):
            assert members[i]["days_until_birthday"] <= members[i + 1]["days_until_birthday"]


def test_upcoming_birthdays():
    response = client.get("/members?upcoming_only=true")
    assert response.status_code == 200
    members = response.json()

    for member in members:
        assert member["days_until_birthday"] <= 30


def test_generate_birthday_message_friendly():
    members_response = client.get("/members")
    members = members_response.json()

    if len(members) > 0:
        member_id = members[0]["id"]

        response = client.post(f"/members/{member_id}/birthday-message?tone=friendly")
        assert response.status_code == 200

        data = response.json()
        assert "message" in data
        assert "explanation" in data
        assert "model" in data["explanation"]
        assert "rationale" in data["explanation"]
        assert len(data["explanation"]["rationale"]) > 20


def test_generate_birthday_message_formal():
    members_response = client.get("/members")
    members = members_response.json()

    if len(members) > 0:
        member_id = members[0]["id"]

        response = client.post(f"/members/{member_id}/birthday-message?tone=formal")
        assert response.status_code == 200

        data = response.json()
        assert "message" in data
        assert data["explanation"]["parameters"]["tone"] == "formal"


def test_send_email_dry_run():
    members_response = client.get("/members")
    members = members_response.json()

    if len(members) > 0:
        member_id = members[0]["id"]

        response = client.post(f"/members/{member_id}/send-email?tone=friendly&dry_run=true")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "dry_run"
        assert "email" in data
        assert data["email"]["dry_run"] == True


def test_calculate_days_until_birthday():
    today = date.today()

    today_str = today.strftime("%Y-%m-%d")
    assert calculate_days_until_birthday(today_str) == 0

    tomorrow = today + timedelta(days=1)
    tomorrow_birth = date(1990, tomorrow.month, tomorrow.day)
    assert calculate_days_until_birthday(tomorrow_birth.strftime("%Y-%m-%d")) == 1

    yesterday = today - timedelta(days=1)
    if yesterday.year == today.year:
        yesterday_birth = date(1990, yesterday.month, yesterday.day)
        days = calculate_days_until_birthday(yesterday_birth.strftime("%Y-%m-%d"))
        assert days > 300


def test_member_not_found():
    response = client.get("/members/99999")
    assert response.status_code == 404


def test_invalid_tone():
    members_response = client.get("/members")
    members = members_response.json()

    if len(members) > 0:
        member_id = members[0]["id"]
        response = client.post(f"/members/{member_id}/birthday-message?tone=invalid")
        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

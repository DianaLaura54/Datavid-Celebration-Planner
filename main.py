from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, field_validator, ValidationError
from datetime import datetime, date, timedelta
from typing import Optional, List
import sqlite3
import os
from contextlib import contextmanager, asynccontextmanager
import pytz


DB_PATH = os.getenv("DB_PATH", "members.db")
MOCK_AI = os.getenv("MOCK_AI", "true").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")


COUNTRY_TIMEZONES = {
    "USA": "America/New_York",
    "UK": "Europe/London",
    "Germany": "Europe/Berlin",
    "Japan": "Asia/Tokyo",
    "Australia": "Australia/Sydney",
    "India": "Asia/Kolkata",
    "Brazil": "America/Sao_Paulo",
    "Canada": "America/Toronto"
}

COUNTRY_LANGUAGES = {
    "USA": "en", "UK": "en", "Canada": "en", "Australia": "en",
    "Germany": "de", "Japan": "ja", "Brazil": "pt", "India": "hi"
}


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                birth_date TEXT NOT NULL,
                country TEXT NOT NULL,
                city TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(first_name, last_name, country, city)
            )
        """)
        conn.commit()


def seed_data():
    sample_members = [
        ("John", "Smith", "1990-03-15", "USA", "New York"),
        ("Emma", "Johnson", "1985-07-22", "UK", "London"),
        ("Hans", "Mueller", "1992-11-08", "Germany", "Berlin"),
        ("Yuki", "Tanaka", "1988-01-30", "Japan", "Tokyo"),
        ("Sophie", "Martin", "1995-05-12", "Canada", "Toronto"),
        ("Raj", "Patel", "1987-09-25", "India", "Mumbai")
    ]

    with get_db() as conn:
        for member in sample_members:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO members 
                    (first_name, last_name, birth_date, country, city, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (*member, datetime.now().isoformat()))
            except:
                pass
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):

    init_db()
    seed_data()
    yield



app = FastAPI(title="Datavid Celebration Planner", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"[DEBUG] Validation Error: {exc.errors()}")
    errors = exc.errors()
    error_messages = []
    for error in errors:
        field = " -> ".join(str(x) for x in error["loc"])
        message = error["msg"]
        error_messages.append(f"{field}: {message}")

    return JSONResponse(
        status_code=422,
        content={"detail": " | ".join(error_messages)}
    )


class Member(BaseModel):
    first_name: str
    last_name: str
    birth_date: str
    country: str
    city: str

    @field_validator('birth_date')
    def validate_birth_date(cls, v):
        try:
            birth = datetime.strptime(v, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError('Birth date must be in YYYY-MM-DD format')

        today = date.today()
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))

        if age < 18:
            raise ValueError(f'Member must be at least 18 years old. Current age would be {age}')

        return v


class MemberResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    birth_date: str
    country: str
    city: str
    days_until_birthday: Optional[int] = None


class BirthdayMessage(BaseModel):
    message: str
    explanation: dict


def calculate_days_until_birthday(birth_date_str: str) -> int:
    birth = datetime.strptime(birth_date_str, '%Y-%m-%d').date()
    today = date.today()

    next_birthday = date(today.year, birth.month, birth.day)
    if next_birthday < today:
        next_birthday = date(today.year + 1, birth.month, birth.day)

    return (next_birthday - today).days


def generate_ai_message(member: dict, tone: str = "friendly") -> BirthdayMessage:

    if MOCK_AI or not OPENAI_API_KEY:

        tone_templates = {
            "friendly": f" Happy Birthday, {member['first_name']}! Wishing you an amazing day filled with joy and laughter from all of us at Datavid!",
            "formal": f"Dear {member['first_name']} {member['last_name']}, On behalf of Datavid, we wish you a very happy birthday and continued success in the year ahead."
        }

        message = tone_templates.get(tone, tone_templates["friendly"])

        explanation = {
            "model": "mock-generator-v1",
            "method": "template_based_generation",
            "parameters": {
                "tone": tone,
                "language": COUNTRY_LANGUAGES.get(member['country'], 'en')
            },
            "rationale": f"Generated using a rule-based template system with {tone} tone. "
                         f"Personalized with member's first name and considering cultural context from {member['country']}."
        }

        return BirthdayMessage(message=message, explanation=explanation)

    else:

        import openai
        openai.api_key = OPENAI_API_KEY

        lang = COUNTRY_LANGUAGES.get(member['country'], 'en')

        prompt = f"""Generate a birthday message for a Datavid company member with these details:
- Name: {member['first_name']} {member['last_name']}
- Location: {member['city']}, {member['country']}
- Tone: {tone}
- Language preference: {lang}

Create a warm, personal birthday message (2-3 sentences max) that reflects the specified tone."""

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=150
            )

            message = response.choices[0].message.content.strip()

            explanation = {
                "model": "gpt-3.5-turbo",
                "method": "chat_completion",
                "parameters": {
                    "temperature": 0.7,
                    "tone": tone,
                    "max_tokens": 150
                },
                "rationale": f"Generated using OpenAI GPT-3.5 with {tone} tone setting and temperature 0.7 for creative variation. "
                             f"Prompt included member's name, location ({member['country']}), and language preference to ensure cultural appropriateness."
            }

            return BirthdayMessage(message=message, explanation=explanation)

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")


@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/members", status_code=201)
def create_member(member: Member):
    print(f"[DEBUG] Received member data: {member}")
    try:
        with get_db() as conn:
            try:
                cursor = conn.execute("""
                    INSERT INTO members (first_name, last_name, birth_date, country, city, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (member.first_name, member.last_name, member.birth_date,
                      member.country, member.city, datetime.now().isoformat()))
                conn.commit()

                return {"id": cursor.lastrowid, **member.model_dump()}
            except sqlite3.IntegrityError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Member with name '{member.first_name} {member.last_name}' in {member.city}, {member.country} already exists"
                )
    except ValueError as e:
        print(f"[DEBUG] Validation error: {e}")  # Debug logging
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/members", response_model=List[MemberResponse])
def list_members(sort_by_birthday: bool = False, upcoming_only: bool = False):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM members").fetchall()

    members = []
    for row in rows:
        member_dict = dict(row)
        member_dict['days_until_birthday'] = calculate_days_until_birthday(row['birth_date'])
        members.append(member_dict)

    if upcoming_only:
        members = [m for m in members if m['days_until_birthday'] <= 30]

    if sort_by_birthday:
        members.sort(key=lambda x: x['days_until_birthday'])

    return members


@app.get("/members/{member_id}")
def get_member(member_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    member_dict = dict(row)
    member_dict['days_until_birthday'] = calculate_days_until_birthday(row['birth_date'])
    return member_dict


@app.post("/members/{member_id}/birthday-message")
def generate_birthday_message(
        member_id: int,
        tone: str = Query("friendly", pattern="^(friendly|formal)$")
):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    member_dict = dict(row)
    return generate_ai_message(member_dict, tone)


@app.post("/members/{member_id}/send-email")
def send_birthday_email(
        member_id: int,
        tone: str = Query("friendly", pattern="^(friendly|formal)$"),
        dry_run: bool = Query(True)
):

    with get_db() as conn:
        row = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    member_dict = dict(row)
    birthday_msg = generate_ai_message(member_dict, tone)

    email_content = {
        "to": f"{member_dict['first_name'].lower()}.{member_dict['last_name'].lower()}@datavid.com",
        "subject": f"Happy Birthday, {member_dict['first_name']}!",
        "body": birthday_msg.message,
        "dry_run": dry_run
    }

    if dry_run:
        return {
            "status": "dry_run",
            "email": email_content,
            "message": "Email NOT sent (dry-run mode). Email content logged above."
        }
    else:

        print(f"[EMAIL] To: {email_content['to']}")
        print(f"[EMAIL] Subject: {email_content['subject']}")
        print(f"[EMAIL] Body: {email_content['body']}")

        return {
            "status": "sent",
            "email": email_content,
            "message": "Email sent successfully (simulated)"
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
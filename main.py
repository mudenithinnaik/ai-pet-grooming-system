import os
import base64
import json
import boto3
import anthropic
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import uvicorn

app = FastAPI(title="AI Pet Grooming System", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
s3_client = boto3.client("s3", aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"), aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"), region_name=os.getenv("AWS_REGION", "us-east-1"))
S3_BUCKET = os.getenv("S3_BUCKET_NAME", "pet-grooming-images")

class GroomingResult(BaseModel):
    breed_guess: str
    size: str
    size_reason: str
    weight_estimate: str
    coat_type: str
    coat_condition: str
    wash_temp: str
    wash_duration: str
    shampoo_type: str
    brush_type: str
    grooming_frequency: str
    special_notes: str
    image_url: str = ""
    timestamp: str = ""

def upload_to_s3(file_bytes, filename, content_type):
    try:
        key = f"uploads/{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
        s3_client.put_object(Bucket=S3_BUCKET, Key=key, Body=file_bytes, ContentType=content_type)
        return f"https://{S3_BUCKET}.s3.amazonaws.com/{key}"
    except Exception as e:
        print(f"S3 upload failed: {e}")
        return ""

def analyze_with_claude(image_base64, media_type):
    prompt = """You are an AI pet grooming assistant. Analyze this dog image and respond ONLY with a JSON object (no markdown, no backticks). Fields: breed_guess, size (Small|Medium|Large|Extra Large), size_reason, weight_estimate, coat_type (Short|Medium|Long|Curly|Double Coat|Wire), coat_condition (Excellent|Good|Fair|Needs Attention), wash_temp, wash_duration, shampoo_type, brush_type, grooming_frequency, special_notes"""
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=1000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_base64}},
            {"type": "text", "text": prompt}
        ]}]
    )
    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    return json.loads(text.replace("```json","").replace("```","").strip())

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("templates/index.html") as f:
        return f.read()

@app.post("/analyze", response_model=GroomingResult)
async def analyze_pet(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 10MB")
    image_url = upload_to_s3(file_bytes, file.filename, file.content_type)
    image_base64 = base64.b64encode(file_bytes).decode("utf-8")
    try:
        result = analyze_with_claude(image_base64, file.content_type)
    except Exception as e:
        raise HTTPException(500, f"Analysis error: {str(e)}")
    result["image_url"] = image_url
    result["timestamp"] = datetime.utcnow().isoformat()
    return GroomingResult(**result)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

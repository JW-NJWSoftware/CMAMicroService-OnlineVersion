import pathlib
import os
import io
import uuid
import PyPDF2
import PyPDF2
import nltk
import re
from heapq import nlargest
from nltk.tokenize import sent_tokenize
from nltk.corpus import stopwords
from nltk.probability import FreqDist
from functools import lru_cache
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Request,
    File,
    UploadFile,
    Header
    )
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic_settings import BaseSettings

# NLTK resources
nltk.download('punkt')
nltk.download('stopwords')

class Settings(BaseSettings):
    debug: bool = False
    echo_active: bool = False
    app_auth_token: str = ""
    app_auth_token_prod: str = ""
    skip_auth: bool = False

    class Config:
        env_file = ".env"

@lru_cache
def get_settings():
    return Settings()

settings = get_settings()
DEBUG=settings.debug

BASE_DIR = pathlib.Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"

app = FastAPI()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def verify_auth(authorization = Header(None), settings:Settings = Depends(get_settings)):
    if settings.debug and settings.skip_auth:
        return
    if authorization is None:
        raise HTTPException(detail="Invalid authorization", status_code=401)
    label, token = authorization.split()
    if token != settings.app_auth_token:
        raise HTTPException(detail="Invalid authorization", status_code=401)

def extract_text_from_pdf(file_path):
    try:
        with open(file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            num_pages = len(pdf_reader.pages)
            text = ''
            for page_num in range(num_pages):
                page = pdf_reader.pages[page_num]
                text += page.extract_text()

        cleaned_text = re.sub(r'\t+', '', text)
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
        cleaned_text = cleaned_text.strip()

        sentences = cleaned_text.split('.')
        cleaned_sentences = []
        for sentence in sentences:
            if len(sentence.strip()) >= 10 and sentence.strip()[0].isupper():
                cleaned_sentences.append(sentence.strip())
        cleaned_text = '. '.join(cleaned_sentences)
            
        return cleaned_text
        
    except FileNotFoundError:
        print(f"File '{file_path}' not found.")
        return None

def extract_text_from_txt(file_path):
    try:
        with open(file_path, 'r') as file:
            text = file.read()
        return text
    except FileNotFoundError:
        print(f"File '{file_path}' not found.")
        return None

def generate_text_summary(text):
    num_sentences=5
    sentences = sent_tokenize(text)

    # Preprocess the text
    stopwords_list = set(stopwords.words('english'))
    words = nltk.word_tokenize(text.lower())
    words = [word for word in words if word.isalnum() and word not in stopwords_list]

    # Calculate word frequency
    frequency = FreqDist(words)

    # Calculate sentence scores based on word frequency
    sentence_scores = {}
    for sentence in sentences:
        for word in nltk.word_tokenize(sentence.lower()):
            if word in frequency:
                if len(sentence.split(' ')) < 30:  # Ignore very long sentences
                    if sentence not in sentence_scores:
                        sentence_scores[sentence] = frequency[word]
                    else:
                        sentence_scores[sentence] += frequency[word]

    # Get the top 'num_sentences' sentences with highest scores
    summary_sentences = nlargest(num_sentences, sentence_scores, key=sentence_scores.get)
    summary = ' '.join(summary_sentences)
    return summary


@app.get("/", response_class=HTMLResponse)
def home_view(request: Request, settings:Settings = Depends(get_settings)):
    return templates.TemplateResponse("home.html", {"request": request})

@app.post("/")
async def file_analysis_view(file:UploadFile = File(...), authorization = Header(None), settings:Settings = Depends(get_settings)):
    verify_auth(authorization, settings)
    data = {}
    UPLOAD_DIR.mkdir(exist_ok=True)

    bytes_str = io.BytesIO(await file.read())
    fname = pathlib.Path(file.filename)
    fext = fname.suffix
    dest = UPLOAD_DIR / f"{uuid.uuid1()}{fext}"

    with open(str(dest), 'wb') as out:
        out.write(bytes_str.read())

    file_extension = str(fname).split('.')[-1].lower()

    try:
        if file_extension == 'txt':
            text = extract_text_from_txt(dest)
            summary = generate_text_summary(text)
            data = {
                "filetype":"Plain text document",
                "summary":summary,
                "text":text
                }
        elif file_extension == 'pdf':
            text = extract_text_from_pdf(dest)
            summary = generate_text_summary(text)
            data = {
                "filetype":"PDF document",
                "summary":summary,
                "text":text
                }
        else:
            data = {
                "filetype":"Unknown",
                "summary":"Sorry, a summary cannot be generated for this file format, this may not be a text format or may be a format only supported by your local instance of the application."
                }

    # Delete the file from the uploads directory
    finally:
        try:
            dest.unlink()  # Delete the file
        except Exception as e:
            print(f"Error deleting file: {e}")

    return data

@app.post("/file-echo/", response_class=FileResponse)
async def file_upload(file:UploadFile = File(...), settings:Settings = Depends(get_settings)):
    if not settings.echo_active:
        raise HTTPException(detail="Invalid endpoint", status_code=400)

    UPLOAD_DIR.mkdir(exist_ok=True)

    bytes_str = io.BytesIO(await file.read())
    fname = pathlib.Path(file.filename)
    fext = fname.suffix
    dest = UPLOAD_DIR / f"{uuid.uuid1()}{fext}"

    with open(str(dest), 'wb') as out:
        out.write(bytes_str.read())
    return dest
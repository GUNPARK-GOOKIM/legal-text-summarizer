import requests
import docx
import re
import time
import json
import hashlib
import os
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from collections import OrderedDict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PyPDF2 import PdfReader

# --- CONFIGURATION ---
API_KEY = os.environ.get("SCALEDOWN_API_KEY", "PASTE_YOUR_API_KEY")
SCALEDOWN_URL = "https://api.scaledown.xyz/compress/raw/"
COMPRESS_MODEL = "gpt-4o-mini"
OLLAMA_URL_GENERATE = "http://localhost:11434/api/generate"
OLLAMA_URL_CHAT = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3"

# --- APP INITIALIZATION ---
app = FastAPI(title="Legal AI Streaming Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- STATE & RETRIES ---
rate_lock = Lock()
last_call = [0]
rate_limit_level = 2

session = requests.Session()
retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

# --- MODELS ---
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]

# --- HELPER FUNCTIONS ---
def throttle():
    with rate_lock:
        now = time.time()
        delay = max(0, (1 / rate_limit_level) - (now - last_call[0]))
        if delay > 0:
            time.sleep(delay)
        last_call[0] = time.time()

def read_docx(file_obj):
    try:
        doc = docx.Document(file_obj)
        return "\n\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        print(f"[ERROR] Reading docx: {e}")
        return ""

def read_pdf(file_obj):
    try:
        reader = PdfReader(file_obj)
        text = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text.append(page_text.strip())
        return "\n\n".join(text)
    except Exception as e:
        print(f"[ERROR] Reading pdf: {e}")
        return ""

def clean_text(text):
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def split_sections(text):
    pattern = r'\n(?=\d+(?:\.\d+)*[\.\)]\s|[A-Z][A-Z\s]{3,}:)'
    return [s.strip() for s in re.split(pattern, text) if s.strip()]

def chunk_text(text, max_chars=2000):
    chunks = []
    while len(text) > max_chars:
        split = text.rfind("\n", 0, max_chars)
        if split == -1: split = text.rfind(". ", 0, max_chars)
        if split == -1: split = max_chars
        chunks.append(text[:split])
        text = text[split:]
    chunks.append(text)
    return chunks

def call_scaledown_api(payload, headers, retries=3):
    for attempt in range(retries):
        try:
            throttle()
            response = session.post(SCALEDOWN_URL, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 429:
                print(f"   [SCALEDOWN WARNING] Rate limited (Attempt {attempt + 1}). Retrying...")
                time.sleep(2 ** attempt)
                continue
                
            if not response.ok:
                print(f"   [SCALEDOWN ERROR {response.status_code}] {response.text}")
                response.raise_for_status()

            data = response.json()
            output = data.get("results", {}).get("compressed_prompt")
            
            if isinstance(output, str):
                return output.strip()
            else:
                print(f"   [SCALEDOWN ERROR] API responded, but 'compressed_prompt' was missing: {data}")
                
        except Exception as e:
            print(f"   [SCALEDOWN EXCEPTION] Request failed on attempt {attempt + 1}: {e}")
            time.sleep(2 ** attempt)
            
    return None

def compress_text(text, section_id):
    chunks = chunk_text(clean_text(text))
    outputs = []
    headers = {"x-api-key": API_KEY, "Content-Type": "application/json"}

    for cid, chunk in enumerate(chunks):
        payload = {
            "context": f"You are processing SECTION {section_id}.{cid} of a legal document.\nINPUT:\n{chunk}\nOUTPUT:",
            # 1. Balanced prompt: Keep the "What" and "Who", cut the "Boilerplate"
            "prompt": "Compress this legal text by removing redundant phrasing and boilerplate while strictly preserving all specific legal obligations, dates, and parties involved.",
            "model": COMPRESS_MODEL,
            # 2. Numerical Sweet Spot: 0.5 tells the API to aim for 50% of original size
            "scaledown": {"rate": 0.5} 
        }
        
        print(f"\n>>> [SCALEDOWN] Sending Section {section_id}, Chunk {cid} ({len(chunk)} characters)...")
        out = call_scaledown_api(payload, headers)
        
        # Validation
        if not out:
            print(f"<<< [SCALEDOWN] ❌ FAILED or empty response. Reverting to original text.")
            outputs.append(chunk)
        # CHANGED: Just check if it's ridiculously short (under 20 chars) instead of a strict 10% rule
        elif len(out) < 20: 
            print(f"<<< [SCALEDOWN] ⚠️ REJECTED: Output too short ({len(out)} chars). Reverting to original.")
            outputs.append(chunk)
        else:
            print(f"<<< [SCALEDOWN] ✅ SUCCESS! Reduced from {len(chunk)} to {len(out)} characters.")
            outputs.append(out)

    return "\n\n".join(outputs)

def summarize_with_ollama(text):
    print(f"\n>>> [OLLAMA] Sending {len(text.split())} words to Ollama for final summary...")
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"You are an expert Indian Legal Assistant. Summarize the following highly compressed legal document clearly and concisely:\n\n{text}",
        "stream": False
    }
    try:
        response = requests.post(OLLAMA_URL_GENERATE, json=payload, timeout=300)
        response.raise_for_status()
        reply = response.json().get("response", "Error generating summary.")
        print(f"<<< [OLLAMA] ✅ Summary received successfully! (Length: {len(reply.split())} words)")
        return reply
    except Exception as e:
        print(f"<<< [OLLAMA ERROR] Failed to connect or generate: {e}")
        return f"Error: {str(e)}"

# --- FASTAPI ENDPOINTS ---

@app.post("/process-logic-stream")
async def process_logic_stream(text: str = Form(None), file: UploadFile = File(None)):
    
    # 1. READ THE FILE FIRST (Asynchronously so we don't block)
    document_text = ""
    try:
        if file:
            filename = file.filename.lower()
            print(f"\n[SYSTEM] Receiving file upload: {filename}")
            content = await file.read()
            if filename.endswith('.txt'): document_text = content.decode('utf-8', errors='ignore')
            elif filename.endswith('.docx'): document_text = read_docx(io.BytesIO(content))
            elif filename.endswith('.pdf'): document_text = read_pdf(io.BytesIO(content))
            else: return JSONResponse(status_code=400, content={"error": "Unsupported file format."})
        elif text:
            print("\n[SYSTEM] Receiving raw text input.")
            document_text = text.strip()
            
        if not document_text:
            return JSONResponse(status_code=400, content={"error": "Could not extract text."})
    except Exception as e:
        print(f"[SYSTEM ERROR] File read error: {e}")
        return JSONResponse(status_code=500, content={"error": f"File read error: {e}"})

    # 2. RUN HEAVY LOGIC IN A SYNCHRONOUS GENERATOR
    def event_stream(doc_text):
        try:
            # STEP 1: Reading
            yield json.dumps({"step": "reading", "reduction": 0}) + "\n"
            orig_words = len(doc_text.split())
            print(f"[PIPELINE] Document parsed. Total Original Words: {orig_words}")

            # STEP 2: Compressing
            yield json.dumps({"step": "compressing", "reduction": 0, "original_tokens": orig_words, "compressed_tokens": orig_words}) + "\n"
            
            sections = split_sections(doc_text)
            compressed_sections = []

            print(f"[PIPELINE] Splitting into {len(sections)} sections and beginning compression...")
            
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(compress_text, sec, str(i)) for i, sec in enumerate(sections)]
                for future in futures:
                    compressed_sections.append(future.result())

            full_compressed_text = "\n\n".join(compressed_sections)
            comp_words = len(full_compressed_text.split())
            reduction = int((1 - (comp_words / orig_words)) * 100) if orig_words > 0 else 0

            # --- THE FINAL CHECK ---
            if reduction == 0:
                print("\n[PIPELINE WARNING] ⚠️ ZERO COMPRESSION ACHIEVED. The original text will be sent to Ollama.")
            else:
                print(f"\n[PIPELINE SUCCESS] 🎉 COMPRESSION COMPLETE. Reduced from {orig_words} to {comp_words} words ({reduction}% reduction).")

            # STEP 3: Summarizing
            yield json.dumps({
                "step": "summarizing", 
                "reduction": reduction, 
                "original_tokens": orig_words, 
                "compressed_tokens": comp_words
            }) + "\n"

            final_summary = summarize_with_ollama(full_compressed_text)

            # STEP 4: Done
            yield json.dumps({
                "step": "done", 
                "summary": final_summary, 
                "reduction": reduction, 
                "original_tokens": orig_words, 
                "compressed_tokens": comp_words
            }) + "\n"

        except Exception as e:
            print(f"[CRITICAL ERROR] Pipeline failed: {e}")
            yield json.dumps({"step": "error", "message": str(e)}) + "\n"

    # 3. RETURN THE STREAM
    return StreamingResponse(event_stream(document_text), media_type="application/x-ndjson")

@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    try:
        print("\n>>> [OLLAMA CHAT] Received follow-up question. Generating response...")
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "stream": False
        }
        response = requests.post(OLLAMA_URL_CHAT, json=payload, timeout=60)
        response.raise_for_status()
        reply_content = response.json().get("message", {}).get("content", "Error communicating with Ollama.")
        print("<<< [OLLAMA CHAT] ✅ Response generated.")
        return {"reply": reply_content}
    except Exception as e:
        print(f"<<< [OLLAMA CHAT ERROR] {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
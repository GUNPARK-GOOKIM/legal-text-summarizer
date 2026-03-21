⚖️ Legal AI Assistant: Token-Reduced Summarization
This project is a high-performance legal document processing pipeline. It uses the Scaledown API to compress heavy legal text into a "sweet spot" (approx. 50% reduction) and then uses Local Ollama (Llama 3) to generate a clean, final summary and chat-ready analysis.

🏗️ System Architecture
Frontend (Streamlit): User interface for document upload (PDF, DOCX, TXT) and chat.

Backend (FastAPI): Orchestrates the streaming pipeline and file parsing.

Compression (Scaledown API): Intelligent token reduction to fit local AI context windows.

Inference (Ollama): Local LLM execution for data privacy and final summarization.

🛠️ Prerequisites & Installation
1. Local AI Engine (Ollama)
The system requires Ollama to be running locally to handle the final summarization and chat.

Download: ollama.com

Install: Follow the OS-specific instructions.

Model Setup: Open your terminal and run the following command to download the model used in the code:

Bash
ollama pull llama3
2. Python Environment
Ensure you have Python 3.9+ installed.

Navigate to the project root folder:

Bash
cd D:\law
Install all required Python libraries:

Bash
pip install -r requirements.txt
3. API Configuration
The backend requires a Scaledown API Key to function.

Open main.py.

Replace YOUR_API_KEY_HERE with your active Scaledown key.

Security Note: Do not commit this key to public repositories.

🚀 How to Run
You must run the Backend and the Frontend simultaneously in two separate terminal windows.

Step 1: Start the Backend (FastAPI)
Bash
uvicorn main:app --reload
Port: 8000

Status: Wait for Uvicorn running on http://127.0.0.1:8000.

Step 2: Start the Frontend (Streamlit)
Bash
streamlit run your_frontend_filename.py
URL: The app will automatically open in your browser (usually http://localhost:8501).

📁 Supported Formats
DOCX: Full paragraph parsing.

PDF: Text extraction via PyPDF2.

TXT: Standard UTF-8 encoding.

Chat Paste: Raw text can be pasted directly into the assistant.

⚡ Performance Monitor
The dashboard includes a real-time monitor showing:

Token Reduction %: The efficiency of the Scaledown compression.

Word Count Tracking: Comparison between original, compressed, and saved words.

Downloadable Output: Generates a professional .docx summary upon completion.

⚠️ Troubleshooting
0% Reduction: Check your Scaledown API key and ensure the rate is set correctly (e.g., 0.5).

Ollama Timeout: If the summary takes too long, ensure your PC isn't overloaded. The backend timeout is currently set to 300s.

Connection Error: Ensure the Backend (Port 8000) is running before trying to upload a file in the Frontend.
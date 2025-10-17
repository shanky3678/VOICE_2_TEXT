from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel
import tempfile, shutil
from template.index import index

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

model = WhisperModel("small", device="cpu")

@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        with tmp as f:
            shutil.copyfileobj(audio.file, f)
        segments, info = model.transcribe(tmp.name, beam_size=5)
        text = " ".join(seg.text for seg in segments)
        return JSONResponse(content={"text": text, "duration": info.duration}, status_code=201)
    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))

@app.get("/runme")
def runme():
    return "Server is warmed up!!"

@app.get("/", response_class=HTMLResponse)
def html():
    return index

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port= 8000, reload=True)
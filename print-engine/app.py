from fastapi import FastAPI
from pydantic import BaseModel
from generator import generate_print_job
from fastapi.staticfiles import StaticFiles


app = FastAPI()
app.mount("/books", StaticFiles(directory="/books"), name="books")

class PrintRequest(BaseModel):
    book_path: str
    spine_mode: str = "auto"
    back_mode: str = "auto"
    paper_thickness: float = 0.06
    page_count: int | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/preview")
def preview_layout(request: PrintRequest):
    result = generate_print_job(
        config=request.dict(),
        preview_only=True
    )
    return {"status": "success", **result}


@app.post("/generate")
def generate_pdf(request: PrintRequest):
    result = generate_print_job(
        config=request.dict(),
        preview_only=False
    )
    return {"status": "success", **result}
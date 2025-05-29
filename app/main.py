from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
import PyPDF2
import io
import os # Added for GOOGLE_API_KEY
import google.generativeai as genai # Added for Gemini API
import httpx # Added for making HTTP requests
from fastapi.middleware.cors import CORSMiddleware

from . import models
from .models import SessionLocal, engine, get_db, Project, Page, ProjectResponse, PageResponse, GeneratedHtmlResponse # Removed FormData, ChatMessage and related Pydantic models

models.Base.metadata.create_all(bind=engine) # Creates tables if they don't exist (dev only)

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Initialize Gemini client
# IMPORTANT: Set your GOOGLE_API_KEY environment variable before running the app.
try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    gemini_model = genai.GenerativeModel('gemini-1.5-flash') # User updated to gemini-1.5-flash or similar
except KeyError:
    print("ERROR: GOOGLE_API_KEY environment variable not set.")
    # Potentially exit or disable Gemini-dependent features
    gemini_model = None 
except Exception as e:
    print(f"Error initializing Gemini client: {e}")
    gemini_model = None

# HTTP client for calling external services
http_client = httpx.AsyncClient()

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

# --- API Endpoints ---

# Project Management
@app.post("/projects/", response_model=models.ProjectResponse)
async def create_project( 
    file: UploadFile = File(...), 
    db: Session = Depends(get_db)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF files are allowed.")

    pdf_content = await file.read() # Read once
    project_name = file.filename
    
    CHAT_SERVICE_BASE_URL = "http://localhost:8090/chat" # Define chat service URL

    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
        num_pages = len(pdf_reader.pages)

        # 1. Create a new chat session with the external service
        chat_session_id = None
        try:
            response = await http_client.post("http://localhost:8090/chat/new")
            response.raise_for_status() # Raise an exception for HTTP errors
            chat_session_data = response.json()
            print(f"Chat session created: {chat_session_data}") # Debug log
            chat_session_id = chat_session_data.get("id")
            if not chat_session_id:
                raise HTTPException(status_code=500, detail="Failed to create chat session: session_id not in response")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Error calling chat service (new session): {exc}")
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=f"Chat service error (new session): {exc.response.text}")
        except Exception as e: # Catch other potential errors like JSON decoding
            raise HTTPException(status_code=500, detail=f"Unexpected error during chat session creation: {str(e)}")


        db_project = models.Project(
            name=project_name, 
            pdf_file=pdf_content, 
            total_pages=num_pages,
            chat_session_id=chat_session_id # Store the session ID
        )
        db.add(db_project)
        db.commit()
        db.refresh(db_project)

        # Extract text and create page entries
        for i in range(num_pages):
            page_text = pdf_reader.pages[i].extract_text()
            db_page = models.Page(
                page_number=i + 1,
                text_content=page_text if page_text else "", # Ensure text_content is not None
                project_id=db_project.id,
                generated_form_html=None # Initialize with no form
            )
            db.add(db_page)
        db.commit()
        db.refresh(db_project) # Refresh to get pages loaded for the response

        # 2. Upload the PDF to the newly created chat session
        if chat_session_id:
            try:
                files = {'file': (file.filename, io.BytesIO(pdf_content), file.content_type)}
                # Reset file pointer for httpx
                # We need to pass a new BytesIO object for the file content
                # as the previous one might have its pointer at the end after PdfReader
                pdf_content_for_upload = io.BytesIO(pdf_content)

                # Constructing the message payload
                # Assuming the external chat service expects a message field for text
                # and can handle file uploads alongside.
                # If it only takes a file, adjust the payload accordingly.
                # For now, let's assume it can take a 'message' and a 'file'.
                # If the API expects only the file, then data can be None or an empty dict.
                message_payload = {"message": f"PDF document '{project_name}' uploaded."}

                response = await http_client.post(
                    f"http://localhost:8090/chat/{chat_session_id}/message",
                    files={'file': (file.filename, pdf_content_for_upload, file.content_type)},
                    data=message_payload # Send some context if the API supports it
                )
                response.raise_for_status()
            except httpx.RequestError as exc:
                # Log this error but don't fail the whole project creation,
                # as the project is already in DB.
                # Consider how to handle this partial failure (e.g., background retry)
                print(f"Error uploading PDF to chat service (session {chat_session_id}): {exc}")
                # Optionally, you could update the project to indicate the chat upload failed
                # or raise a non-blocking warning to the client.
            except httpx.HTTPStatusError as exc:
                print(f"Chat service error during PDF upload (session {chat_session_id}): {exc.response.status_code} - {exc.response.text}")
            except Exception as e:
                print(f"Unexpected error during PDF upload to chat (session {chat_session_id}): {str(e)}")


        return db_project
    except Exception as e:
        db.rollback()
        # Log the full exception for debugging
        print(f"Error during project creation: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing PDF or creating project: {str(e)}")

@app.get("/projects/", response_model=List[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).all()

@app.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@app.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    return

# PDF Interaction & Viewing
@app.get("/projects/{project_id}/pages/", response_model=List[PageResponse])
def list_project_pages(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return db.query(Page).filter(Page.project_id == project_id).order_by(Page.page_number).all()

@app.get("/projects/{project_id}/pages/{page_number}/pdf")
async def get_pdf_page_display(project_id: int, page_number: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.pdf_file:
        raise HTTPException(status_code=404, detail="PDF file not found for this project")
    
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(project.pdf_file))
        if not (0 < page_number <= len(pdf_reader.pages)):
            raise HTTPException(status_code=404, detail=f"Page number {page_number} out of range. PDF has {len(pdf_reader.pages)} pages.")

        pdf_writer = PyPDF2.PdfWriter()
        pdf_writer.add_page(pdf_reader.pages[page_number - 1])  # PyPDF2 pages are 0-indexed

        output_pdf_buffer = io.BytesIO()
        pdf_writer.write(output_pdf_buffer)
        output_pdf_buffer.seek(0)

        from fastapi.responses import Response
        return Response(content=output_pdf_buffer.read(), media_type="application/pdf")
    except Exception as e:
        # Log the exception e for debugging if necessary
        raise HTTPException(status_code=500, detail=f"Error processing PDF page: {str(e)}")


@app.get("/projects/{project_id}/pages/{page_number}/text", response_model=PageResponse)
def get_page_text_content(project_id: int, page_number: int, db: Session = Depends(get_db)):
    page = db.query(Page).filter(Page.project_id == project_id, Page.page_number == page_number).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page

# Dynamic Digital Form System
@app.post("/projects/{project_id}/pages/{page_number}/form/generate", response_model=dict)
async def generate_form_fields(project_id: int, page_number: int, db: Session = Depends(get_db)):
    page = db.query(models.Page).filter(models.Page.project_id == project_id, models.Page.page_number == page_number).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    # If HTML already exists, return it
    if page.generated_form_html:
        return {"html_content": page.generated_form_html, "source": "cache"}

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project or not project.pdf_file:
        raise HTTPException(status_code=404, detail="Project or PDF file not found")

    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(project.pdf_file))
        if not (0 < page_number <= len(pdf_reader.pages)):
            raise HTTPException(status_code=404, detail=f"Page number {page_number} out of range. PDF has {len(pdf_reader.pages)} pages.")

        pdf_writer = PyPDF2.PdfWriter()
        pdf_writer.add_page(pdf_reader.pages[page_number - 1])
        single_page_pdf_buffer = io.BytesIO()
        pdf_writer.write(single_page_pdf_buffer)
        single_page_pdf_buffer.seek(0)
        pdf_page_bytes = single_page_pdf_buffer.read()

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="GOOGLE_API_KEY not configured.")
        genai.configure(api_key=api_key)

        model = genai.GenerativeModel('gemini-2.5-flash-preview-05-20')
        prompt = """You are Expert in reading complex documents.
        Task for you: Extract the information from the document, You need to convert physical document into a digital verion which imitates the physical form , keep information prefilled and editable.Rememeber the accuracy of the information extracted specially filled information is absolutely important.You need to take care of multilingual , checkboxes and handwritten complexity within document. give me the html with good stylinng for review, if you are not confident on any field or section enough mark that area as red so that Human can rectify that easily. The output should be the html page content without suffix or prefix."""
        pdf_blob = {
            'mime_type': 'application/pdf',
            'data': pdf_page_bytes
        }

        response = await model.generate_content_async([prompt, pdf_blob])

        if response.parts:
            html_content = response.text
            if html_content.startswith("```html"):
                html_content = html_content[7:]
            if html_content.startswith("```"):
                 html_content = html_content[3:]
            if html_content.endswith("```"):
                html_content = html_content[:-3]
            html_content = html_content.strip()
            
            # Store the generated HTML in the database
            page.generated_form_html = html_content
            db.commit()
            db.refresh(page)
            
            return {"html_content": html_content, "source": "generated"}
        else:
            error_detail = "AI model did not return expected content."
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                error_detail += f" Reason: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}"
            raise HTTPException(status_code=500, detail=error_detail)

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating form fields: {str(e)}")

@app.get("/projects/{project_id}/pages/{page_number}/form/html", response_model=models.GeneratedHtmlResponse)
async def get_or_generate_form_html(project_id: int, page_number: int, db: Session = Depends(get_db)):
    db_page = db.query(models.Page).filter(models.Page.project_id == project_id, models.Page.page_number == page_number).first()
    
    if not db_page:
        raise HTTPException(status_code=404, detail="Page not found")

    if db_page.generated_form_html is not None:
        return models.GeneratedHtmlResponse(html_content=db_page.generated_form_html)
    else:
        # If generated_form_html is None, it means the form has not been generated yet.
        raise HTTPException(
            status_code=404, 
            detail=f"HTML form for page {page_number} has not been generated yet. Use the POST /projects/{project_id}/pages/{page_number}/form/generate endpoint to create it."
        )

# Main application entry point for Uvicorn
# To run: uvicorn app.main:app --reload

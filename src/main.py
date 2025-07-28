from fastapi import FastAPI
from router.router import router as docs_router

app = FastAPI()
app.include_router(docs_router)
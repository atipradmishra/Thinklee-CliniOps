"""Background document ingestion.

Embedding a document is slow — about 1.1 s per 1000-character chunk on CPU, so
roughly a minute for a ten-page PDF and several for a large one. Doing that
inside the HTTP request meant uploads either timed out at the proxy or held a
server thread for minutes. Uploads now stage their bytes to disk, record an
IngestionJob, and return straight away; this module does the work afterwards.

Why an in-process thread rather than Celery or RQ
-------------------------------------------------
A separate worker process would import app.utils.embeding_utils and load its
own copy of intfloat/multilingual-e5-large — about 1.3 GB resident. On the
current 3.7 GB host that does not fit alongside the web worker, and the OOM
killer would take one of them. A thread inside the existing process shares the
single already-loaded model.

The executor is deliberately single-threaded: embedding is CPU- and
memory-bound, so running two ingestions at once makes both slower and risks
the memory ceiling. Jobs queue instead.

The trade-off is that a restart loses in-flight work. reconcile_stale_jobs()
marks those jobs 'interrupted' on boot so they surface in the UI rather than
appearing to run forever. If this ever needs to survive restarts or scale past
one box, swap _EXECUTOR for a real queue — the job table is already the
contract.
"""

import os
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.chunks import Chunk
from app.models.file_metadata import FileMetadata
from app.models.ingestion_job import IngestionJob
from app.models.user import User
from app.utils.embeding_utils import get_embeddings
from app.utils.unstructured_ingest import (
    chunk_text,
    detect_language,
    extract_text_from_file,
)

ALLOWED_UNSTRUCTURED = (".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".pptx", ".csv")

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------

def staging_root(app):
    return os.path.join(app.instance_path, "ingest_jobs")


def stage_uploads(app, job_id, files):
    """Persist the uploaded FileStorage objects so they outlive the request.

    Returns the staging directory. Werkzeug's temporary files are closed when
    the request ends, so the bytes have to be copied somewhere durable before
    the response is returned.
    """
    target = os.path.join(staging_root(app), str(job_id))
    os.makedirs(target, exist_ok=True)

    staged = 0
    for index, storage in enumerate(files):
        name = secure_filename(storage.filename or f"upload_{index}")
        if not name:
            name = f"upload_{index}"
        # Prefix with the index so two files of the same name both survive.
        storage.save(os.path.join(target, f"{index:04d}__{name}"))
        staged += 1

    return target, staged


def _expand(staging_dir):
    """Yield (display_name, path) for every ingestible file, expanding zips."""
    import zipfile

    entries = []
    for entry in sorted(os.listdir(staging_dir)):
        path = os.path.join(staging_dir, entry)
        if not os.path.isfile(path):
            continue

        display = entry.split("__", 1)[-1]

        if display.lower().endswith(".zip"):
            extract_to = os.path.join(staging_dir, f"_unzipped_{entry}")
            os.makedirs(extract_to, exist_ok=True)
            try:
                with zipfile.ZipFile(path, "r") as archive:
                    for member in archive.infolist():
                        if member.is_dir() or member.filename.startswith("__MACOSX"):
                            continue
                        inner = os.path.basename(member.filename)
                        if not inner or not inner.lower().endswith(ALLOWED_UNSTRUCTURED):
                            continue
                        archive.extract(member, extract_to)
                        entries.append((inner, os.path.join(extract_to, member.filename)))
            except zipfile.BadZipFile:
                entries.append((display, None))  # reported as a failure below
            continue

        entries.append((display, path))

    return entries


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------

def enqueue(app, job_id):
    """Hand a queued job to the worker thread."""
    _EXECUTOR.submit(_run_job, app, job_id)


def _finish(job, status, error=None):
    job.status = status
    job.error = error
    job.finished_at = datetime.now()
    db.session.commit()


def _run_job(app, job_id):
    """Entry point on the worker thread. Never raises."""
    with app.app_context():
        job = None
        try:
            job = db.session.get(IngestionJob, job_id)
            if job is None or job.status != "queued":
                return

            user = db.session.get(User, job.user_id)
            if user is None:
                _finish(job, "failed", "The user who started this job no longer exists.")
                return

            job.status = "running"
            job.started_at = datetime.now()
            db.session.commit()

            _ingest(job, user)

        except Exception:
            app.logger.exception("Ingestion job %s crashed", job_id)
            try:
                if job is not None:
                    db.session.rollback()
                    _finish(job, "failed", traceback.format_exc(limit=3))
            except Exception:
                app.logger.exception("Could not record failure for job %s", job_id)
        finally:
            try:
                if job is not None and job.staging_dir:
                    shutil.rmtree(job.staging_dir, ignore_errors=True)
            except Exception:
                pass
            # Return the thread's connection rather than holding it open; this
            # matters on SQLite, where a lingering connection blocks writers.
            db.session.remove()


def _ingest(job, user):
    """Process every staged file, committing after each one.

    Per-file commits mean a failure late in a batch does not discard the work
    already done, and the UI can show progress as it goes.
    """
    files = _expand(job.staging_dir)

    job.total_files = len(files)
    job.results = []
    db.session.commit()

    results = []

    for display_name, path in files:
        outcome = {"filename": display_name, "success": False, "message": "", "chunks": 0}

        try:
            if path is None:
                raise ValueError("Could not read this archive")

            size_bytes = os.path.getsize(path)
            if size_bytes == 0:
                raise ValueError("The file is empty")

            text = extract_text_from_file(path)
            if not text.strip():
                raise ValueError("No readable text could be extracted")

            language = detect_language(text)
            chunks = chunk_text(text)
            if not chunks:
                raise ValueError("The document produced no text chunks")

            embeddings = get_embeddings(chunks, normalize=True)
            if len(embeddings) != len(chunks):
                raise RuntimeError("Embedding count did not match chunk count")

            file_meta = FileMetadata(
                user_id=user.id,
                organization_id=user.organization_id,
                original_filename=display_name,
                file_size=size_bytes,
                language=language,
            )
            db.session.add(file_meta)
            db.session.flush()

            import json

            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                db.session.add(
                    Chunk(
                        file_metadata_id=file_meta.id,
                        chunk_index=index,
                        text=chunk,
                        embedding_json=json.dumps(embedding),
                    )
                )

            db.session.commit()

            outcome["success"] = True
            outcome["chunks"] = len(chunks)
            outcome["message"] = f"Indexed {len(chunks)} passages"
            job.succeeded_files += 1

        except Exception as exc:
            db.session.rollback()
            outcome["message"] = str(exc)[:300] or exc.__class__.__name__
            job.failed_files += 1

        results.append(outcome)

        # Reassign rather than mutate: a JSON column is only marked dirty when
        # the attribute itself is replaced.
        job.processed_files = len(results)
        job.results = list(results)
        db.session.commit()

    if job.succeeded_files and job.failed_files:
        _finish(job, "partial")
    elif job.succeeded_files:
        _finish(job, "succeeded")
    else:
        _finish(job, "failed", "No file could be ingested.")


# ---------------------------------------------------------------------------
# Boot-time reconciliation
# ---------------------------------------------------------------------------

def reconcile_stale_jobs(app):
    """Close out jobs orphaned by a restart.

    In-process jobs do not survive the process, so anything left 'queued' or
    'running' at boot is dead. Mark it so the UI stops showing a spinner that
    will never resolve.
    """
    with app.app_context():
        try:
            stale = IngestionJob.query.filter(
                IngestionJob.status.in_(("queued", "running"))
            ).all()

            for job in stale:
                job.status = "interrupted"
                job.error = "The server restarted while this job was running. Please upload again."
                job.finished_at = datetime.now()
                if job.staging_dir:
                    shutil.rmtree(job.staging_dir, ignore_errors=True)

            if stale:
                db.session.commit()
                app.logger.warning("Marked %d ingestion job(s) interrupted after restart", len(stale))

            # Sweep any staging directories left behind by an unclean exit.
            root = staging_root(app)
            if os.path.isdir(root):
                live = {str(j.id) for j in IngestionJob.query.filter(
                    IngestionJob.status.in_(("queued", "running"))
                ).all()}
                for entry in os.listdir(root):
                    if entry not in live:
                        shutil.rmtree(os.path.join(root, entry), ignore_errors=True)

        except Exception:
            # Never let housekeeping stop the app from starting.
            app.logger.exception("Could not reconcile stale ingestion jobs")
            db.session.rollback()
        finally:
            db.session.remove()

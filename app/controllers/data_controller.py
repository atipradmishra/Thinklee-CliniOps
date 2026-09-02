import json
import base64
import os
import re
from app.models.user import User
import pandas as pd
from app.models.chunks import Chunk
from app.models.file_metadata import FileMetadata
from app.models.table_metadata import TableMetadata
from app.utils.embeding_utils import get_embeddings
from app.utils.unstructured_ingest import chunk_text, detect_language, extract_text_from_file
from app.utils import s3_utils
from app.utils.db_connections import (
    ALL_SOURCE_TYPES,
    DISPLAY_NAMES,
    OBJECT_STORE_TYPES,
    RDS_ENGINES,
    ConnectionConfigError,
    decode_secret,
    encode_secret,
    normalize_config,
    probe_connection,
)
from flask import request, jsonify
from app.models.data_connection import DataSourceConnection
from flask_jwt_extended import get_jwt_identity, jwt_required
from app.extensions import db
import tempfile
from werkzeug.utils import secure_filename
import zipfile
from sqlalchemy import desc
from werkzeug.datastructures import FileStorage

# Kept as a module-level alias: other call sites still import `decode`.
decode = decode_secret

@jwt_required()
def save_connection():
    data = request.get_json() or {}
    user = User.query.get(get_jwt_identity())
    try:
        source_type = (data.get('source_type') or '').strip().lower()
        if source_type not in ALL_SOURCE_TYPES:
            return jsonify({
                "status": "error",
                "message": f"Unsupported source type: {source_type or '(none)'}"
            }), 400

        if not (data.get('source_name') or '').strip():
            return jsonify({"status": "error", "message": "Connection name is required"}), 400

        rds_engine = (data.get('rds_engine') or '').strip().lower() or None
        if source_type == 'rds' and rds_engine not in RDS_ENGINES:
            return jsonify({
                "status": "error",
                "message": "Select an RDS engine (MySQL, MariaDB, PostgreSQL or SQL Server)."
            }), 400

        cfg = normalize_config(data, decode_password=False)

        conn = DataSourceConnection(
            user_id=user.id,
            organization_id=user.organization_id,
            source_type=source_type,
            source_name=data.get('source_name').strip(),
            username=cfg['username'],
            password=encode_secret(cfg['password']),
            host=cfg['host'],
            port=str(cfg['port']) if cfg['port'] else None,
            server=data.get('server'),
            database=cfg['database'],
            driver=cfg['driver'],
            rds_engine=rds_engine,
            snowflake_account=cfg['snowflake_account'],
            snowflake_warehouse=cfg['snowflake_warehouse'],
            snowflake_schema=cfg['snowflake_schema'],
            s3_access_key=cfg['s3_access_key'],
            s3_secret_key=encode_secret(cfg['s3_secret_key']),
            s3_region=cfg['s3_region'],
            s3_bucket=cfg['s3_bucket'],
            s3_prefix=cfg['s3_prefix'],
            sqlite_path=cfg['sqlite_path'],
        )

        db.session.add(conn)
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Connection saved successfully!",
            "connection_id": conn.id
        }), 200

    except Exception as e:
        db.session.rollback()
        print(f"Error saving connection: {e}")
        return jsonify({"status": "error", "message": "Failed to save connection", "details": str(e)}), 500

@jwt_required()
def delete_connection(connection_id):
    user = User.query.get(get_jwt_identity())
    try:
        conn = DataSourceConnection.query.filter_by(id=connection_id, organization_id=user.organization_id, is_deleted=False).first()
        if not conn:
            return jsonify({"status": "error", "message": "Connection not found"}), 404
        conn.delete()
        db.session.commit()
        return jsonify({"status": "success", "message": "Connection deleted successfully!"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Failed to delete connection", "details": str(e)}), 500

@jwt_required()
def test_connection():
    """Probe an unsaved connection using the credentials in the form."""
    data = request.get_json() or {}
    source = (data.get('source_type') or '').strip().lower()

    if not source:
        return jsonify({"status": "error", "message": "Source type not provided"}), 400

    if source not in ALL_SOURCE_TYPES:
        return jsonify({"status": "error", "message": f"Unsupported source type: {source}"}), 400

    # Form payloads carry plaintext secrets, so nothing needs decoding here.
    ok, message = probe_connection(data, decode_password=False)

    if ok:
        return jsonify({"status": "success", "message": message}), 200
    return jsonify({"status": "error", "message": message}), 400

@jwt_required()
def get_data_sources():
    try:
        user_id = get_jwt_identity()
        user = db.session.get(User, user_id)

        if not user:
            return jsonify({
                "status": "error",
                "message": "User not found"
            }), 404

        if not user.organization_id:
            return jsonify({
                "status": "error",
                "message": "Organization not set for user"
            }), 403

        data_sources = (
            DataSourceConnection.query
            .filter(
                DataSourceConnection.organization_id == user.organization_id,
                DataSourceConnection.is_deleted.is_(False)
            )
            .order_by(desc(DataSourceConnection.created_at))
            .all()
        )

        return jsonify({
            "status": "success",
            "data_sources": [ds.to_dict() for ds in data_sources]
        }), 200

    except Exception as e:
        # LOG this instead of returning details
        print(f"[get_data_sources] Error: {e}")

        return jsonify({
            "status": "error",
            "message": "Failed to fetch data sources"
        }), 500

@jwt_required()
def edit_connection(connection_id):
    data = request.get_json()
    user = User.query.get(get_jwt_identity())
    try:
        conn = DataSourceConnection.query.filter_by(
            id=connection_id,
            organization_id=user.organization_id,
            is_deleted=False
        ).first()

        if not conn:
            return jsonify({"status": "error", "message": "Connection not found"}), 404

        def get_first(keys):
            return next((data.get(k) for k in keys if data.get(k)), None)

        # Update only provided fields
        if 'source_type' in data:
            conn.source_type = data['source_type']
        if 'source_name' in data:
            conn.source_name = data['source_name']

        username = get_first(('uid', 'username'))
        if username:
            conn.username = username

        password = get_first(('pwd', 'password'))
        if password:
            conn.password = base64.b64encode(password.encode()).decode()

        database = get_first(('sql_database', 'database', 'sf_database'))
        if database:
            conn.database = database

        sqlite_path = get_first(('sqlite_path', 'data_source'))
        if sqlite_path:
            conn.sqlite_path = sqlite_path

        if 'host' in data:
            conn.host = data['host']
        if 'port' in data:
            conn.port = str(data['port']) if data['port'] else None
        if 'server' in data:
            conn.server = data['server']
        if 'driver' in data:
            conn.driver = data['driver']

        if 'rds_engine' in data:
            engine = (data['rds_engine'] or '').strip().lower()
            if conn.source_type == 'rds' and engine not in RDS_ENGINES:
                return jsonify({
                    "status": "error",
                    "message": "Select an RDS engine (MySQL, MariaDB, PostgreSQL or SQL Server)."
                }), 400
            conn.rds_engine = engine or None

        if 'sf_account' in data:
            conn.snowflake_account = data['sf_account']
        if 'warehouse' in data:
            conn.snowflake_warehouse = data['warehouse']
        if 'schema' in data:
            conn.snowflake_schema = data['schema']

        if 's3_access_key' in data:
            conn.s3_access_key = data['s3_access_key']
        if 's3_secret_key' in data and data['s3_secret_key']:
            conn.s3_secret_key = base64.b64encode(data['s3_secret_key'].encode()).decode()
        if 's3_region' in data:
            conn.s3_region = data['s3_region']
        if 's3_bucket' in data:
            conn.s3_bucket = data['s3_bucket']
        if 's3_prefix' in data:
            conn.s3_prefix = data['s3_prefix']

        db.session.commit()

        return jsonify({"status": "success", "message": "Connection updated successfully!"}), 200

    except Exception as e:
        db.session.rollback()
        print(f"Error updating connection: {e}")
        return jsonify({"status": "error", "message": "Failed to update connection", "details": str(e)}), 500

@jwt_required()
def get_data_source(connection_id):
    user = User.query.get(get_jwt_identity())
    try:
        conn = DataSourceConnection.query.filter_by(id=connection_id, organization_id=user.organization_id, is_deleted=False).first()
        if not conn:
            return jsonify({"status": "error", "message": "Connection not found"}), 404
        return jsonify({"status": "success", "data_source": conn.to_dict()}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
@jwt_required()
def test_saved_connection(source_id):
    """Probe a stored connection and persist the resulting status."""
    user = User.query.get(get_jwt_identity())
    conn = DataSourceConnection.query.filter_by(
        id=source_id,
        organization_id=user.organization_id,
        is_deleted=False
    ).first()

    if not conn:
        return jsonify({"status": "error", "message": "Connection not found"}), 404

    ok, message = probe_connection(conn)

    conn.connection_status = "Connected" if ok else "Failed"
    db.session.commit()

    if ok:
        return jsonify({"status": "success", "message": message}), 200
    return jsonify({"status": "error", "message": message}), 400


# --------------------------------------------------------------------------
# Amazon S3 browse + import
#
# S3 holds files, so it cannot back a SQL agent. These endpoints let a user
# list a bucket and pull CSV/Excel objects into an org table through the same
# ingestion path as a manual upload; agents then query those tables normally.
# --------------------------------------------------------------------------

def _load_object_store(connection_id, user):
    """Fetch an object-store connection scoped to the user's organization."""
    conn = DataSourceConnection.query.filter_by(
        id=connection_id,
        organization_id=user.organization_id,
        is_deleted=False
    ).first()

    if not conn:
        return None, (jsonify({"status": "error", "message": "Connection not found"}), 404)

    if conn.source_type not in OBJECT_STORE_TYPES:
        label = DISPLAY_NAMES.get(conn.source_type, conn.source_type)
        return None, (jsonify({
            "status": "error",
            "message": f"{label} is not a file store; browsing is only available for S3."
        }), 400)

    return conn, None


@jwt_required()
def list_s3_objects(connection_id):
    """List the CSV/Excel/JSON objects available under a bucket prefix."""
    user = User.query.get(get_jwt_identity())
    conn, error = _load_object_store(connection_id, user)
    if error:
        return error

    prefix = request.args.get('prefix')
    only_importable = request.args.get('importable', 'false').lower() in ('1', 'true', 'yes')

    try:
        result = s3_utils.list_objects(
            normalize_config(conn),
            prefix=prefix,
            only_importable=only_importable
        )
    except s3_utils.S3Error as exc:
        conn.connection_status = "Failed"
        db.session.commit()
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        print(f"[list_s3_objects] {exc}")
        return jsonify({"status": "error", "message": "Failed to list bucket contents"}), 500

    conn.connection_status = "Connected"
    db.session.commit()

    return jsonify({"status": "success", **result}), 200


@jwt_required()
def import_s3_objects(connection_id):
    """Import selected S3 objects into an organization table.

    Mirrors the manual upload flow: the target table must already have stored
    metadata (created by uploading a metadata file), and each object is run
    through the same ingest_file_to_db() used for browser uploads.
    """
    user = User.query.get(get_jwt_identity())
    conn, error = _load_object_store(connection_id, user)
    if error:
        return error

    data = request.get_json() or {}
    keys = data.get('keys') or []
    table_name = (data.get('table_name') or '').strip()

    if not keys:
        return jsonify({"status": "error", "message": "Select at least one file to import"}), 400
    if not table_name:
        return jsonify({"status": "error", "message": "Target table name is required"}), 400

    table_name = re.sub(r"\s+", "_", table_name).lower()

    existing_meta = TableMetadata.query.filter_by(
        organization_id=user.organization_id,
        table_name=table_name,
        is_deleted=False
    ).first()

    if not existing_meta:
        return jsonify({
            "status": "error",
            "message": (
                f"No table named '{table_name}' exists yet. Create it first under "
                "Upload Data by supplying a metadata file."
            )
        }), 400

    cfg = normalize_config(conn)
    results = []

    for key in keys:
        if not str(key).lower().endswith(s3_utils.IMPORTABLE_EXTENSIONS):
            results.append({
                "key": key,
                "success": False,
                "message": "Only CSV and Excel objects can be imported into a table."
            })
            continue

        try:
            filename, buffer = s3_utils.fetch_object(cfg, key)
            file_storage = FileStorage(
                stream=buffer,
                filename=filename,
                content_type="application/octet-stream"
            )
            outcome = ingest_file_to_db(file_storage, user.id, table_name)
            results.append({
                "key": key,
                "success": outcome.get("success", False),
                "message": outcome.get("message", "")
            })
        except s3_utils.S3Error as exc:
            results.append({"key": key, "success": False, "message": str(exc)})
        except Exception as exc:
            db.session.rollback()
            results.append({"key": key, "success": False, "message": str(exc)})

    imported = sum(1 for r in results if r["success"])
    conn.connection_status = "Connected"
    db.session.commit()

    return jsonify({
        "status": "success",
        "table_name": table_name,
        "imported": imported,
        "total": len(results),
        "results": results
    }), 200




@jwt_required()
def handle_file_upload():
    print("handle_file_upload")
    upload_type = request.form.get('upload_type')
    file_category = request.form.get('file_category', 'structured')
    raw_files = request.files.getlist('files')
    meta_file = request.files.get('meta_file')
    user = User.query.get(get_jwt_identity())

    if not raw_files:
        return jsonify({"status": "error", "message": "At least one data file is required"}), 400

    results = []

    ALLOWED_STRUCTURED = ('.csv', '.xlsx', '.json')
    ALLOWED_UNSTRUCTURED = ('.pdf', '.docx', '.txt', '.md', '.html', '.pptx', '.html', '.csv')

    try:
        # --------------------------------------------------
        # Expand ZIP files
        # --------------------------------------------------
        expanded_files = []   # (source, filename, obj)
        zip_temp_dirs = []

        for file in raw_files:
            if file.filename.lower().endswith(".zip"):
                tmpdir = tempfile.TemporaryDirectory()
                zip_temp_dirs.append(tmpdir)

                zip_path = os.path.join(tmpdir.name, secure_filename(file.filename))
                file.save(zip_path)

                with zipfile.ZipFile(zip_path, "r") as z:
                    for member in z.infolist():
                        if member.is_dir() or member.filename.startswith("__MACOSX"):
                            continue

                        filename = os.path.basename(member.filename)
                        if not filename:
                            continue

                        if file_category == "structured" and not filename.lower().endswith(ALLOWED_STRUCTURED):
                            continue
                        if file_category == "unstructured" and not filename.lower().endswith(ALLOWED_UNSTRUCTURED):
                            continue

                        extracted_path = z.extract(member, tmpdir.name)
                        expanded_files.append(("zip", filename, extracted_path))
            else:
                expanded_files.append(("file", file.filename, file))

        if not expanded_files:
            return jsonify({
                "status": "error",
                "message": "No valid files found inside ZIP"
            }), 400

        # --------------------------------------------------
        # STRUCTURED FILE INGESTION
        # --------------------------------------------------
        if file_category == "structured":

            if upload_type == "new":
                table_name = request.form.get("new_table_name")
                if not table_name:
                    return jsonify({"status": "error", "message": "New table name is required"}), 400
                if not meta_file:
                    return jsonify({"status": "error", "message": "Metadata file is required"}), 400

                table_name = re.sub(r"\s+", "_", table_name.strip()).lower()
                meta_file.seek(0)

                meta = handle_metadata_upload(meta_file, user.id, table_name)
                if not meta["success"]:
                    return jsonify({"status": "error", "message": meta["message"]}), 400

            elif upload_type == "existing":
                table_name = request.form.get("existing_table")
                if not table_name:
                    return jsonify({"status": "error", "message": "Existing table name is required"}), 400

                table_name = re.sub(r"\s+", "_", table_name.strip()).lower()

            else:
                return jsonify({"status": "error", "message": "Invalid upload_type"}), 400

            for source, filename, obj in expanded_files:
                try:
                    if source == "zip":
                        with open(obj, "rb") as f:
                            file_storage = FileStorage(
                                stream=f,
                                filename=filename,
                                content_type="application/octet-stream"
                            )
                            ingest_result = ingest_file_to_db(file_storage, user.id, table_name)
                    else:
                        ingest_result = ingest_file_to_db(obj, user.id, table_name)

                    results.append({
                        "filename": filename,
                        "success": ingest_result.get("success", False),
                        "message": ingest_result.get("message", "")
                    })

                except Exception as e:
                    results.append({
                        "filename": filename,
                        "success": False,
                        "message": str(e)
                    })

            return jsonify({
                "status": "success",
                "table_name": table_name,
                "results": results
            }), 200

        # --------------------------------------------------
        # UNSTRUCTURED FILE INGESTION (RAG)
        # --------------------------------------------------
        elif file_category == "unstructured":
            print("Ingesting unstructured files...")
            for source, filename, obj in expanded_files:
                filepath = None
                try:
                    if source == "zip":
                        filepath = obj
                        size_bytes = os.path.getsize(filepath)
                    else:
                        filename = secure_filename(obj.filename)
                        with tempfile.NamedTemporaryFile(
                            delete=False,
                            suffix=os.path.splitext(filename)[1]
                        ) as tmp:
                            filepath = tmp.name
                            obj.save(filepath)
                        size_bytes = os.path.getsize(filepath)

                    if size_bytes == 0:
                        raise ValueError("Empty file")
                    print(f"File size: {size_bytes}")
                    text = extract_text_from_file(filepath)
                    language = detect_language(text)
                    if not text.strip():
                        raise ValueError("No text extracted")
                    print(f"Extracted {len(text)} characters")
                    chunks = chunk_text(text)
                    print(f"Extracted {len(chunks)} chunks")
                    embeddings = get_embeddings(chunks, normalize=True)
                    print(f"Generated {len(embeddings)} embeddings")

                    file_meta = FileMetadata(
                        user_id=user.id,
                        organization_id=user.organization_id,
                        original_filename=filename,
                        file_size=size_bytes,
                        language=language
                    )
                    db.session.add(file_meta)
                    db.session.flush()

                    print(f"Extracted2 {len(chunks)} chunks")

                    # ---------- EVENT INGESTION ----------
                    # events = extract_events(filepath)

                    # if events:
                    #     event_objects = [
                    #         EventFact(
                    #             file_metadata_id=file_meta.id,
                    #             event_text=ev["event_text"],
                    #             normalized_event_text=ev["normalized_text"],
                    #             event_date=ev["event_date"],
                    #             event_time=ev["event_time"],
                    #             event_datetime=ev["event_datetime"],
                    #             contains_overlast=ev["contains_overlast"]
                    #         )
                    #         for ev in events
                    #     ]

                    #     db.session.bulk_save_objects(event_objects)

                    for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                        db.session.add(Chunk(
                            file_metadata_id=file_meta.id,
                            chunk_index=idx,
                            text=chunk,
                            embedding_json=json.dumps(emb)
                        ))
                    db.session.commit()

                    results.append({
                        "filename": filename,
                        "success": True,
                        "message": f"Extracted {len(chunks)} chunks"
                    })

                except Exception as e:
                    db.session.rollback()
                    results.append({
                        "filename": filename,
                        "success": False,
                        "message": str(e)
                    })

                finally:
                    if source != "zip" and filepath and os.path.exists(filepath):
                        os.remove(filepath)

            return jsonify({"status": "success", "results": results}), 200

        else:
            return jsonify({"status": "error", "message": "Invalid file_category"}), 400

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500

def ingest_file_to_db(file, user_id, table_name):
    user = User.query.get(user_id)
    try:
        existing_meta = TableMetadata.query.filter_by(organization_id=user.organization_id, table_name=table_name).first()
        if not existing_meta:
            return {"success": False, "message": "No metadata found for the table."}
        

        # Load file into DataFrame
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif file.filename.endswith('.xlsx'):
            df = pd.read_excel(file)
        else:
            return {"success": False, "message": "Invalid file format."}

        # Clean column names
        df = df.rename(columns={col: col.strip().replace(" ", "_").lower() for col in df.columns})
        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        df = df.dropna(axis=1, how='all')
        df_columns = df.columns.tolist()


        existing_columns = [col.strip().replace(" ", "_").lower() for col in existing_meta.schema.keys()]
        if set(df_columns) != set(existing_columns):
            return {
                "success": False,
                "message": f"Schema mismatch. Expected columns: {existing_columns}, got: {df_columns}"
            }
        
        # Save to DB using consistent table name
        df.to_sql(f"org_{user.organization_id}_{table_name}", db.engine, index=False, if_exists='append')

        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        new_file = FileMetadata(
                user_id=user_id,
                organization_id=user.organization_id,
                original_filename=file.filename,
                table_metadata_id=existing_meta.id,
                file_size=file_size
            )
        db.session.add(new_file)
        db.session.commit()

        return {"success": True, "table_name": table_name, "message": "File ingested successfully."}

    except Exception as e:
        return {"success": False, "message": f"Error during file ingestion: {str(e)}"}

def handle_metadata_upload(file, user_id, table_name):
    user = User.query.get(user_id)
    try:
        # Check for duplicates
        existing = TableMetadata.query.filter_by(organization_id=user.organization_id, table_name=table_name).first()
        if existing:
            return {"success": False, "message": "Metadata for this table already exists."}

        if file.filename.endswith('.json'):
            try:
                schema = json.load(file)
                if not isinstance(schema, dict):
                    return {"success": False, "message": "Invalid JSON schema format."}
            except Exception as e:
                return {"success": False, "message": f"JSON parsing error: {str(e)}"}

        elif file.filename.endswith('.xlsx'):
            df = pd.read_excel(file)
            required_columns = {'column_name', 'data_type', 'description'}
            if not required_columns.issubset(df.columns):
                return {"success": False, "message": "Metadata file must contain 'column_name' and 'data_type' columns."}
            schema = {
                row['column_name']: {
                    "data_type": row['data_type'],
                    "description": row['description']
                }
                for _, row in df.iterrows()
            }


        elif file.filename.endswith('.csv'):
            df = pd.read_csv(file)
            required_columns = {'column_name', 'data_type', 'description'}
            if not required_columns.issubset(df.columns):
                return {"success": False, "message": "Metadata file must contain 'column_name' and 'data_type' columns."}
            schema = {
                row['column_name']: {
                    "data_type": row['data_type'],
                    "description": row['description']
                }
                for _, row in df.iterrows()
            }

        else:
            return {"success": False, "message": "Unsupported metadata format."}


        # Save metadata
        meta = TableMetadata(user_id=user_id, organization_id=user.organization_id, table_name=table_name, schema=schema)
        db.session.add(meta)
        db.session.commit()

        return {"success": True, "message": "Metadata uploaded successfully.", "schema": schema}

    except Exception as e:
        return {"success": False, "message": f"Error processing metadata: {str(e)}"}

@jwt_required()
def get_uploaded_files():
    try:
        user_id = get_jwt_identity()

        user = db.session.get(User, user_id)
        if not user:
            return jsonify({
                "status": "error",
                "message": "User not found"
            }), 404

        if not user.organization_id:
            return jsonify({
                "status": "success",
                "uploaded_files": []
            }), 200

        uploaded_files = (
            FileMetadata.query
            .filter(
                FileMetadata.organization_id == user.organization_id,
                FileMetadata.is_deleted.is_(False)
            )
            .order_by(desc(FileMetadata.uploaded_at))
            .all()
        )

        return jsonify({
            "status": "success",
            "uploaded_files": [uf.to_dict() for uf in uploaded_files]
        }), 200

    except Exception as e:
        # LOG THIS in real apps
        print(f"[get_uploaded_files] Error: {e}")

        return jsonify({
            "status": "error",
            "message": "Failed to fetch uploaded files"
        }), 500

    
@jwt_required()
def get_existing_tables():
    user = User.query.get(get_jwt_identity())
    try:
        uploaded_files = TableMetadata.query.filter_by(organization_id=user.organization_id, is_deleted=False).all()
        return jsonify({
            "status": "success",
            "tables": [uf.to_dict() for uf in uploaded_files]
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@jwt_required()
def delete_file(file_id):
    user = User.query.get(get_jwt_identity())
    try:
        file = FileMetadata.query.filter_by(id=file_id, organization_id=user.organization_id).first()
        if not file:
            return jsonify({"status": "error", "message": "File not found"}), 404
        print(f"Deleting file: {file.original_filename}")
        file.delete()
        db.session.commit()
        return jsonify({"status": "success", "message": "File deleted successfully!"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Failed to delete file", "details": str(e)}), 500
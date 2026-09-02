from app.models.user import User
from werkzeug.utils import secure_filename
import os
import pandas as pd
from app.models.file_metadata import FileMetadata
from app.utils.prompt_generation import generate_sql_prompts, generate_rag_synthesizer_prompts
from app.models.agent import Agent, AgentFileMap, AgentTableMap, BusinessGlossary
from app.models.table_metadata import TableMetadata
from app.models.data_connection import DataSourceConnection
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import db
import traceback
import tempfile
from sqlalchemy import desc

ALLOWED_EXTENSIONS = {"csv", "xlsx"}

@jwt_required()
def create_agent():
    user = User.query.get(get_jwt_identity())
    try:
        data = request.get_json()
        user_id = get_jwt_identity()

        if not user_id:
            return jsonify({"success": False, "message": "User not authenticated."}), 401

        # Required fields
        name = data.get("name")
        model = data.get("model")
        provider = data.get("provider")
        source_type = data.get("source_type")


        if not all([name, model, source_type]):
            return jsonify({"success": False, "message": "Missing required fields."}), 400

        # Optional field
        data_connection_id = data.get("data_source") if source_type == "datasource" else None

        if source_type == "rag":
            agent_type = "unstructured"
        else:
            agent_type = "structured"

        # Create agent first
        agent = Agent(
            user_id=user.id,
            organization_id=user.organization_id,
            name=name,
            llm_model=model,
            llm_provider=provider,
            temperature=data.get("temperature", 0.7),
            description=data.get("description", ""),
            data_connection_id=data_connection_id,
            sql_system_prompt=data.get("sql_system_prompt"),
            sql_task=data.get("sql_task"),
            sql_instruction=data.get("sql_instruction"),
            synthesizer_system_prompt=data.get("synthesizer_system_prompt"),
            synthesizer_task=data.get("synthesizer_task"),
            synthesizer_instruction=data.get("synthesizer_instruction"),
            rag_system_prompt=data.get("rag_system_prompt"),
            rag_task=data.get("rag_task"),
            rag_instruction=data.get("rag_instruction"),
            agent_type = agent_type
        )

        db.session.add(agent)
        db.session.flush()

        if source_type == "tables":
            table_ids = data.get("tables", [])
            for table_id in table_ids:
                db.session.add(AgentTableMap(agent_id=agent.id, table_id=table_id))

        if source_type == "rag":
            file_ids = data.get("files", [])
            for file_id in file_ids:
                db.session.add(AgentFileMap(agent_id=agent.id, file_id=file_id))

        db.session.commit()

        return jsonify({
            "success": True,
            "agent_id": agent.id,
            "message": "✅ Agent created successfully."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"❌ Server error: {str(e)}"}), 500

@jwt_required()
def get_agents():
    user = User.query.get(get_jwt_identity())
    if not user or not user.id:
        return jsonify({"success": False, "message": "User not authenticated"}), 401

    agents = (
        Agent.query
        .filter_by(organization_id=user.organization_id, is_deleted=False)
        .order_by(desc(Agent.created_at))
        .all()
    )

    return jsonify({
        "success": True,
        "agents": [
            {
                **agent.to_dict(),
                "tables": [
                    t.to_dict()
                    for t in AgentTableMap.query.filter_by(agent_id=agent.id).all()
                ],
                "files": [
                    f.to_dict()
                    for f in AgentFileMap.query.filter_by(agent_id=agent.id).all()
                ],
            }
            for agent in agents
        ],
    }), 200

@jwt_required()
def get_agent(agent_id):
    try:
        user = User.query.get(get_jwt_identity())
        agent = Agent.query.filter_by(id=agent_id, organization_id=user.organization_id).first()

        if not agent:
            return jsonify({"success": False, "message": "Agent not found"}), 404
        
        source_type = "tables" 
        if agent.data_connection_id:
            source_type = "datasource"
        elif agent.agent_type == "unstructured":
            source_type = "rag"
        else: 
            "tables"

        agent_data = {
            "id": agent.id,
            "name": agent.name,
            "llm_model": agent.llm_model,
            "llm_provider": agent.llm_provider,
            "temperature": agent.temperature,
            "description": agent.description,
            "source_type": source_type,
            "data_connection_id": agent.data_connection_id,
            "sql_system_prompt": agent.sql_system_prompt,
            "sql_task": agent.sql_task,
            "sql_instruction": agent.sql_instruction,
            "synthesizer_system_prompt": agent.synthesizer_system_prompt,
            "synthesizer_task": agent.synthesizer_task,
            "synthesizer_instruction": agent.synthesizer_instruction,
            "rag_system_prompt": agent.rag_system_prompt,
            "rag_task": agent.rag_task,
            "rag_instruction": agent.rag_instruction,
            "created_at": agent.created_at.isoformat() if agent.created_at else None,
        }

        agent_data["tables"] = [
            t.table_id for t in AgentTableMap.query.filter_by(agent_id=agent.id).all()
        ]

        agent_data["files"] = [
            f.file_id for f in AgentFileMap.query.filter_by(agent_id=agent.id).all()
        ]

        return jsonify({"success": True, "agent": agent_data}), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"❌ Server error: {str(e)}"}), 500

@jwt_required()
def update_agent(agent_id):
    try:
        data = request.get_json()
        user = User.query.get(get_jwt_identity())


        agent = Agent.query.filter_by(id=agent_id, organization_id=user.organization_id).first()
        if not agent:
            return jsonify({"success": False, "message": "Agent not found or unauthorized."}), 404

        name = data.get("name")
        model = data.get("model")
        provider = data.get("provider")
        source_type = data.get("source_type")

        if not all([name, model, source_type]):
            return jsonify({"success": False, "message": "Missing required fields."}), 400

        data_connection_id = data.get("data_source") if source_type == "datasource" else None

        agent.name = name
        agent.llm_model = model
        agent.llm_provider = provider
        agent.temperature = data.get("temperature", agent.temperature)
        agent.description = data.get("description", agent.description)
        agent.data_connection_id = data_connection_id
        agent.sql_system_prompt = data.get("sql_system_prompt")
        agent.sql_task = data.get("sql_task")
        agent.sql_instruction = data.get("sql_instruction")
        agent.synthesizer_system_prompt = data.get("synthesizer_system_prompt")
        agent.synthesizer_task = data.get("synthesizer_task")
        agent.synthesizer_instruction = data.get("synthesizer_instruction")
        agent.rag_system_prompt = data.get("rag_system_prompt")
        agent.rag_task = data.get("rag_task")
        agent.rag_instruction = data.get("rag_instruction")

        if source_type == "tables":
            AgentTableMap.query.filter_by(agent_id=agent.id).delete()
            table_ids = data.get("tables", [])
            for table_id in table_ids:
                db.session.add(AgentTableMap(agent_id=agent.id, table_id=table_id))

        if source_type == "rag":
            AgentFileMap.query.filter_by(agent_id=agent.id).delete()
            file_ids = data.get("files", [])
            for file_id in file_ids:
                db.session.add(AgentFileMap(agent_id=agent.id, file_id=file_id))

        db.session.commit()

        return jsonify({
            "success": True,
            "agent_id": agent.id,
            "message": "✅ Agent updated successfully."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"❌ Server error: {str(e)}"}), 500

@jwt_required()
def delete_agent(agent_id):
    user = User.query.get(get_jwt_identity())
    agent = Agent.query.filter_by(id=agent_id, organization_id=user.organization_id).first()

    if not agent:
        return jsonify({"success": False, "message": "Agent not found"}), 404

    agent.delete()

    return jsonify({"success": True, "message": "Agent deleted successfully"}), 200



@jwt_required()
def add_glossary():
    data = request.get_json()
    agent_id = data.get('agent_id')

    if not agent_id:
        return jsonify({"success": False, "message": "Agent ID is required"}), 400

    term = data.get('term', '').strip()
    definition = data.get('definition', '').strip()
    category = data.get('category', '').strip()

    if not term:
        return jsonify({"success": False, "message": "Term cannot be empty"}), 400

    new_term = BusinessGlossary(term=term, definition=definition, category=category, agent_id=agent_id,user_id=get_jwt_identity())
    db.session.add(new_term)
    db.session.commit()

    return jsonify({"success": True, "message": "Term added successfully", "id": new_term.id}), 201

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@jwt_required()
def upload_glossary():
    try:
        agent_id = request.form.get("agentId")
        file = request.files.get("file")
        user_id = get_jwt_identity()

        if not agent_id:
            print("Agent ID is required.")
            return jsonify({"success": False, "message": "Agent ID is required."}), 400
        if not file:
            print("A CSV, Excel, or JSON file is required.")
            return jsonify({"success": False, "message": "A CSV, Excel, or JSON file is required."}), 400

        filename = secure_filename(file.filename)
        if not filename.lower().endswith((".csv", ".xlsx", ".json")):
            print("Unsupported file format.")
            return jsonify({"success": False, "message": "Unsupported file format."}), 400

        temp_dir = tempfile.gettempdir()
        filepath = os.path.join(temp_dir, filename)
        file.save(filepath)

        if filename.lower().endswith(".csv"):
            df = pd.read_csv(filepath)
        elif filename.lower().endswith(".xlsx"):
            df = pd.read_excel(filepath)
        elif filename.lower().endswith(".json"):
            try:
                df = pd.read_json(filepath)
            except Exception as e:
                print(e)
                return jsonify({"success": False, "message": f"Invalid JSON format: {str(e)}"}), 400
        else:
            print("Unsupported file type.")
            return jsonify({"success": False, "message": "Unsupported file type."}), 400
        
        df = df.rename(columns={col: col.strip().replace(" ", "_").lower() for col in df.columns})

        required_cols = {"term", "definition"}
        if not required_cols.issubset(df.columns):
            print(f"File must contain columns: {', '.join(required_cols)}")
            return jsonify({
                "success": False,
                "message": f"File must contain columns: {', '.join(required_cols)}"
            }), 400

        for _, row in df.iterrows():
            glossary_item = BusinessGlossary(
                agent_id=agent_id,
                user_id=user_id,
                term=row["term"],
                definition=row["definition"],
                category=row.get("category", None)
            )
            db.session.add(glossary_item)

        db.session.commit()
        return jsonify({
            "success": True,
            "message": f"Uploaded {len(df)} glossary items successfully"
        }), 201

    except Exception as e:
        print(e)
        return jsonify({
            "success": False,
            "message": f"Error processing glossary upload: {str(e)}"
        }), 500

@jwt_required()
def get_glossarys():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"success": False, "message": "User not authenticated"}), 401

    agents = Agent.query.filter_by(
        organization_id=user.organization_id
    ).all()

    agent_ids = [agent.id for agent in agents]

    items = (
        BusinessGlossary.query
        .filter(BusinessGlossary.agent_id.in_(agent_ids))
        .order_by(desc(BusinessGlossary.created_at))
        .all()
    )

    return jsonify({
        "success": True,
        "items": [item.to_dict() for item in items]
    }), 200

@jwt_required()
def get_glossary(item_id):
    item = BusinessGlossary.query.filter_by(id=item_id).first()
    if not item:
        return jsonify({"success": False, "message": "Glossary term not found"}), 404
    return jsonify({"success": True, "item": item.to_dict()}), 200

@jwt_required()
def delete_glossary(item_id):
    glossary_item = BusinessGlossary.query.filter_by(id=item_id).first()

    if not glossary_item:
        return jsonify({"success": False, "message": "Glossary term not found"}), 404

    db.session.delete(glossary_item)
    db.session.commit()

    return jsonify({"success": True, "message": "Term deleted successfully"}), 200



@jwt_required()
def generate_prompts():
    data = request.get_json()
    context = data.get("business_context", "")
    agent_type = data.get("agent_type", "sql")

    if not context:
        return jsonify({"error": "Missing business context"}), 400

    try:
        if agent_type == "rag":
            result = generate_rag_synthesizer_prompts(context)
        else:
            result = generate_sql_prompts(context)

        return jsonify(result)

    except Exception as e:
        print("Prompt generation error:", traceback.format_exc())
        return jsonify({"error": "Failed to generate prompts"}), 500

@jwt_required()
def get_stats():
    try:
        user = User.query.get(get_jwt_identity())

        agents_count = Agent.query.filter_by(organization_id=user.organization_id).count()
        glossary_count = BusinessGlossary.query.filter_by(user_id=user.id).count()
        datasource_count = DataSourceConnection.query.filter_by(organization_id=user.organization_id).count()
        table_count = TableMetadata.query.filter_by(organization_id=user.organization_id).count()

        return jsonify({
            "success": True,
            "stats": {
                "agents": agents_count,
                "glossary": glossary_count,
                "datasources": datasource_count,
                "tables": table_count
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@jwt_required()
def get_files():
    user = User.query.get(get_jwt_identity())
    file_type = request.args.get("type")

    query = FileMetadata.query.filter_by(organization_id=user.organization_id, is_deleted=False)

    if file_type == "unstructured":
        query = query.filter(FileMetadata.table_metadata_id == None)

    files = query.all()
    return jsonify([f.to_dict() for f in files])
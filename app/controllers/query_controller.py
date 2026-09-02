import json
import pickle
from app.models.query_log import QueryLog
from app.models.user import User
from app.services.data_synthesizer_agent import synthesize_result
from app.services.query_rag_agent import generate_rag_response
from app.utils.embeding_utils import get_embeddings, get_similar_feedback
from app.services.followup_query_ageny import follow_up_question_agent
from app.services.query_sql_agent import generate_sql_and_query
from app.utils.agent_utils import is_agent_queryable
from flask import request, jsonify
from app.models.agent import Agent, BusinessGlossary
from flask_jwt_extended import get_jwt_identity, jwt_required
from app.extensions import db
import traceback

@jwt_required()
def copilot_query_agent(agent_id):
    data = request.get_json()
    user = User.query.get(get_jwt_identity())

    agent = Agent.query.get_or_404(agent_id)
    if agent.organization_id != int(user.organization_id):
        return jsonify({"code": 403, "status": "error", "message": "Unauthorized"}), 403

    nlq = data.get("user_query")
    if not nlq:
        return jsonify({"code": 400, "status": "error", "message": "Missing 'user_query'"}), 400

    queryable_info = is_agent_queryable(agent)
    if not queryable_info["status"]:
        return jsonify({
            "code": 400,
            "status": "error",
            "message": f"❌ Agent not queryable: {queryable_info['reason']}",
            "response": "No documents available."
        }), 400

    few_shot_examples = get_similar_feedback(nlq, agent_id=agent_id)

    glossary_items = BusinessGlossary.query.filter_by(agent_id=agent_id).all()
    glossary_text = "\n".join([f"- {g.term}: {g.definition}" for g in glossary_items]) if glossary_items else "No glossary terms provided."

    try:
        if agent.agent_type == "unstructured":
            rag_result = generate_rag_response(
                agent,
                nlq,
                glossary_text=glossary_text,
                chat_history=data.get("chat_history"),
                few_shot_examples=few_shot_examples
            )
            print('[copilot_query_agent] rag_result:', rag_result)
            response = rag_result["response"]
            sql = None

        else:
            result = generate_sql_and_query(
                agent,
                nlq,
                source_type=queryable_info["type"],
                table_names=queryable_info.get("table_names"),
                glossary_text=glossary_text,
                chat_history=data.get("chat_history"),
                few_shot_examples=few_shot_examples
            )
            sql = result["sql"]
            response = synthesize_result(agent, nlq, result["data"], glossary_text, few_shot_examples)
            print('[copilot_query_agent] response:', response)

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({
            "code": 500,
            "status": "error",
            "message": f"Query failed: {str(e)}"
        }), 500

    log = QueryLog(
        user_id=user.id,
        organization_id=agent.organization_id,
        agent_id=agent.id,
        user_query=nlq,
        user_query_embedding=pickle.dumps(get_embeddings(nlq)),
        generated_sql=sql,
        ai_response=response,
        response_embedding=pickle.dumps(get_embeddings(response)),
        source_type=queryable_info["type"]
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        "status": "success",
        "ai_response": response,
        "followups": follow_up_question_agent(agent, nlq, response),
        "query_id": log.id,
        "sql": sql
    }), 200

@jwt_required()
def fetch_query_logs():
    try:
        user = User.query.get(get_jwt_identity())
        agent_id = request.args.get('agent_id')

        query = QueryLog.query.filter_by(organization_id=user.organization_id)

        if agent_id:
            # Optional agent ownership validation
            agent = Agent.query.filter_by(id=agent_id, organization_id=user.organization_id).first()
            if not agent:
                return jsonify({"status": "error", "message": "Invalid or unauthorized agent ID"}), 403
            query = query.filter(QueryLog.agent_id == agent_id, QueryLog.agent.is_deleted == False)

        logs = query.order_by(QueryLog.created_at.desc()).all()

        return jsonify({
            "status": "success",
            "logs": [log.to_dict() for log in logs]
        }), 200

    except Exception as e:
        print("🔥 Error in fetch_query_logs:", traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": "Internal server error"
        }), 500

@jwt_required()
def submit_feedback():
    data = request.get_json()
    query_id = data.get("query_id")
    feedback_type = data.get("feedback_type")
    issues = data.get("issues", [])
    comments = data.get("comments", '')

    if not query_id or not feedback_type:
        return jsonify({"success": False, "error": "Missing query_id or rating"}), 400

    if feedback_type not in ["negative", "positive", "neutral"]:
        return jsonify({"success": False, "error": "Invalid rating type"}), 400

    query_log = QueryLog.query.get(query_id)
    if not query_log:
        return jsonify({"success": False, "error": "Query not found"}), 404

    user_id = get_jwt_identity()
    if int(query_log.user_id) != int(user_id):
        return jsonify({"success": False, "error": "Unauthorized to submit feedback for this query"}), 403

    try:
        query_log.feedback_rating = feedback_type
        query_log.feedback_comment = comments
        query_log.issues= json.dumps(issues),
        if comments:
            query_log.feedback_embedding = pickle.dumps(get_embeddings(comments))

        db.session.commit()

        return jsonify({"success": True, "message": "Feedback submitted successfully"}), 200

    except Exception as e:
        print("🔥 Error in submit_feedback:", traceback.format_exc())
        return jsonify({"success": False, "error": "Internal server error"}), 500
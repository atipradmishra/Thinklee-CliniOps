import base64
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
from app.models.agent import Agent
from app.services.graph_query_agent import generate_sql_and_graph_query
from app.services.query_sql_agent import execute_sql_query
from app.utils.agent_utils import is_agent_queryable
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
import random
from app.extensions import db

@jwt_required()
def graph_query_controller(agent_id):
    user_id = get_jwt_identity()
    data = request.get_json()

    if not data:
        return jsonify({
            "code": 400,
            "status": "error",
            "message": "Missing JSON body in request."
        }), 400

    # Step 1: Verify agent access
    agent = Agent.query.get_or_404(agent_id)
    if agent.user_id != int(user_id):
        return jsonify({
            "code": 403,
            "status": "error",
            "message": "❌ Unauthorized access to the agent."
        }), 403

    # Step 2: Extract the user query
    nlq = next((data.get(k) for k in ['message', 'nlq', 'query', 'question', 'graph_query'] if data.get(k)), None)
    if not nlq:
        return jsonify({
            "code": 400,
            "status": "error",
            "message": "❌ Missing user query in any of: 'message', 'nlq', 'query', 'question', 'user_query'"
        }), 400

    # Step 3: Check if agent is queryable
    queryable_info = is_agent_queryable(agent)
    if not queryable_info.get("status"):
        return jsonify({
            "code": 400,
            "status": "error",
            "message": f"❌ Agent not queryable: {queryable_info.get('reason', 'No datasource connected')}"
        }), 400

    # Step 4: Generate SQL and get results
    try:
        result = generate_sql_and_graph_query(
            agent,
            nlq,
            source_type=queryable_info["type"],
            table_names=queryable_info.get("table_names")
        )
    except Exception as e:
        return jsonify({
            "code": 500,
            "status": "error",
            "message": f"❌ Query execution failed: {str(e)}"
        }), 500

    sql = result.get("sql")
    rows = result.get("data")

    if not rows or not isinstance(rows, list):
        return jsonify({
            "code": 204,
            "status": "success",
            "message": "✅ No data to plot",
            "sql": sql,
            "query": nlq
        }), 200

    # Step 5: Prepare chart data
    first_row = rows[0]
    if len(first_row.keys()) < 2:
        return jsonify({
            "code": 400,
            "status": "error",
            "message": "❌ Expected at least two columns (label, value) in result."
        }), 400
    
    keys = list(first_row.keys())
    label_key, value_key = keys[0], keys[1]

    labels = [str(row[label_key]) for row in rows]
    values = [float(row[value_key]) for row in rows]

    
    unique_keys = set()

    for item in rows:
        unique_keys.update(item.keys())

    label_str = list(unique_keys)[1]
    value_str = list(unique_keys)[0]

    def generate_color():
        return f"#{random.randint(0x111111, 0xFFFFFF):06x}"

    colors = [generate_color() for _ in labels]

    chart_type = "bar"
    if "pie" in nlq.lower():
        chart_type = "pie"
    elif "line" in nlq.lower():
        chart_type = "line"
    elif "scatter" in nlq.lower():
        chart_type = "scatter"
    elif "area" in nlq.lower():
        chart_type = "area"
    elif "histogram" in nlq.lower():
        chart_type = "histogram"
    elif "boxplot" in nlq.lower():
        chart_type = "boxplot"
    elif "donut" in nlq.lower():
        chart_type = "donut"
    elif "radar" in nlq.lower():
        chart_type = "radar"

    return jsonify({
        "code": 200,
        "status": "success",
        "chart_type": chart_type,
        "chart_labels": labels,
        "chart_values": values,
        "chart_colors": colors,
        "label_key": label_str,
        "value_key": value_str, 
        "sql": sql,
        "query": nlq
    }), 200


@jwt_required()
def graph_drilldown_controller():
    data = request.get_json()
    user_id = get_jwt_identity()

    agent_id = data.get("agent_id")
    original_query = data.get("original_query")
    drill_label = data.get("drill_label")
    drill_path = data.get("drill_path", [])

    if not all([agent_id, original_query, drill_label]):
        return jsonify({
            "code": 400,
            "status": "error",
            "message": "❌ Required fields: agent_id, original_query, drill_label"
        }), 400

    # Step 1: Agent access check
    agent = Agent.query.get_or_404(agent_id)
    if agent.user_id != int(user_id):
        return jsonify({
            "code": 403,
            "status": "error",
            "message": "❌ Unauthorized agent access."
        }), 403

    # Step 2: Append the current label to the drill path
    new_drill_path = drill_path + [drill_label]

    # Step 3: Build refined query from drill_path
    drill_context = " -> ".join(new_drill_path)
    refined_query = f"Drilldown of '{original_query}' with focus on {drill_context}"

    # Step 4: Ensure agent is queryable
    queryable_info = is_agent_queryable(agent)
    if not queryable_info.get("status"):
        return jsonify({
            "code": 400,
            "status": "error",
            "message": f"❌ Agent not queryable: {queryable_info.get('reason', 'Unknown reason')}"
        }), 400

    # Step 5: Generate new SQL + result
    try:
        result = generate_sql_and_graph_query(
            agent,
            refined_query,
            source_type=queryable_info["type"],
            table_names=queryable_info.get("table_names")
        )
    except Exception as e:
        return jsonify({
            "code": 500,
            "status": "error",
            "message": f"❌ Drilldown query failed: {str(e)}"
        }), 500

    sql = result.get("sql")
    rows = result.get("data")

    if not rows:
        return jsonify({
            "code": 204,
            "status": "success",
            "message": "✅ No drilldown data found.",
            "sql": sql,
            "query": refined_query,
            "drill_path": new_drill_path
        }), 200

    keys = list(rows[0].keys())
    if len(keys) < 2:
        return jsonify({
            "code": 400,
            "status": "error",
            "message": "❌ Expected at least 2 columns in drilldown data."
        }), 400

    label_key, value_key = keys[0], keys[1]

    labels = [str(row[label_key]) for row in rows]
    values = [float(row[value_key]) for row in rows]
    colors = [f"#{random.randint(0x111111, 0xFFFFFF):06x}" for _ in labels]

    unique_keys = set()

    for item in rows:
        unique_keys.update(item.keys())

    label_str = list(unique_keys)[0]
    value_str = list(unique_keys)[1]

    return jsonify({
        "code": 200,
        "status": "success",
        "message": "✅ Drilldown data generated.",
        "chart_type": "bar",
        "chart_labels": labels,
        "chart_values": values,
        "chart_colors": colors,
        "query": refined_query,
        "drill_path": new_drill_path,
        "label_key": label_str,
        "value_key": value_str,
    }), 200


@jwt_required()
def sql_graph_controller(agent_id):
    """Handles SQL execution for a given agent and returns chart-friendly data."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    sql = data.get("sql")

    if not sql:
        return jsonify({"error": "SQL query required"}), 400

    try:
        # Fetch and validate agent
        agent = Agent.query.get_or_404(agent_id)
        if agent.user_id != int(user_id):
            return jsonify({
                "code": 403,
                "status": "error",
                "message": "❌ Unauthorized access to the agent."
            }), 403

        # Check if agent can be queried
        queryable_info = is_agent_queryable(agent)
        if not queryable_info.get("status"):
            return jsonify({
                "code": 400,
                "status": "error",
                "message": f"❌ Agent not queryable: {queryable_info.get('reason', 'No datasource connected')}"
            }), 400

        # Execute SQL
        result_data = execute_sql(sql, source_type=queryable_info["type"], agent=agent)
        if result_data.get("error"):
            return jsonify({
                "code": 500,
                "status": "error",
                "message": f"❌ SQL Execution Failed: {result_data['error']}"
            }), 500

        result = result_data.get("data", [])
        if not result:
            return jsonify({
                "chart_labels": [],
                "chart_values": [],
                "value_key": "Values",
                "query": sql,
                "chart_type": "bar"
            })

        # Detect label & value keys
        keys = list(result[0].keys())
        label_key = next((k for k in keys if k.lower() in ["label", "name", "category"]), keys[0])
        value_key = next((k for k in keys if k.lower() in ["value", "count", "total", "amount"]),
                         keys[1] if len(keys) > 1 else keys[0])

        # Prepare chart data
        chart_labels = [str(row[label_key]) for row in result]
        chart_values = [float(row[value_key]) if row[value_key] is not None else 0 for row in result]
        chart_colors = [f"#{random.randint(0, 0xFFFFFF):06x}" for _ in chart_labels]

        return jsonify({
            "chart_labels": chart_labels,
            "chart_values": chart_values,
            "value_key": value_key,
            "query": sql,
            "chart_type": "bar",
            "chart_colors": chart_colors
        })

    except Exception as e:
        print(f"[ERROR] SQL Graph Controller: {e}")
        return jsonify({"error": str(e)}), 500


def execute_sql(sql, source_type, agent):
    try:
        print(f"[INFO] Executing SQL: {sql}")

        if source_type == 'tables':
            with db.engine.connect() as conn:
                result = conn.execute(text(sql))
                data = [dict(row._mapping) for row in result]
            return {"data": data, "error": None}

        conn = agent.data_connection
        conn.password = quote_plus(base64.b64decode(conn.password).decode('utf-8'))
        db_type = conn.source_type

        db_uri_map = {
            "postgresql": f"postgresql://{conn.username}:{conn.password}@{conn.host}:{conn.port}/{conn.database}",
            "mysql": f"mysql+pymysql://{conn.username}:{conn.password}@{conn.host}:{conn.port}/{conn.database}",
            "sqlite": f"sqlite:///{conn.database}",
            "mssql": f"mssql+pyodbc://{conn.username}:{conn.password}@{conn.host}:{conn.port}/{conn.database}?driver=ODBC+Driver+17+for+SQL+Server",
            "snowflake": (
                f"snowflake://{conn.username}:{conn.password}@{conn.snowflake_account}.snowflakecomputing.com/"
                f"{conn.database}/{conn.snowflake_schema}?warehouse={conn.snowflake_warehouse}"
            )
        }

        if db_type not in db_uri_map:
            return {"data": [], "error": f"Unsupported DB type: {db_type}"}

        engine = create_engine(db_uri_map[db_type])
        print(f"[INFO] Connected to {db_type} database")

        with engine.connect() as db_conn:
            result = db_conn.execute(text(sql))
            data = [dict(row._mapping) for row in result]

        return {"data": data, "error": None}

    except Exception as e:
        print(f"[ERROR] SQL Execution failed: {e}")
        return {"data": [], "error": str(e)}

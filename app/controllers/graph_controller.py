from flask import request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity, jwt_required
from app.models.agent import Agent
from app.services.graph_query_agent import generate_sql_and_graph_query
from app.services.report_queries import execute_report_query
from app.utils.agent_utils import is_agent_queryable
from app.utils.chart_data import chart_payload, chart_type_for


def owned_agent(agent_id):
    return Agent.query.filter_by(id=agent_id, user_id=int(get_jwt_identity()), is_deleted=False).first_or_404()


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('A JSON object is required.')
    return data


def generated_chart(agent, query):
    if not isinstance(query, str) or not query.strip():
        raise ValueError('Enter a non-empty graph query.')
    kind = chart_type_for(query)
    info = is_agent_queryable(agent)
    if not info['status'] or info['type'] not in ('tables', 'db'):
        raise ValueError('Connect a structured data source to this agent.')
    result = generate_sql_and_graph_query(agent, query, info['type'], info.get('table_names'))
    if result.get('error'):
        raise RuntimeError(result['error'])
    payload = chart_payload(result.get('data') or [], kind)
    return dict(payload, code=200, status='success', sql=result.get('sql'), query=query,
                message='No data to plot.' if not payload['rows'] else 'Chart generated.')


def query_error(exc):
    if isinstance(exc, ValueError):
        return jsonify(status='error', message=str(exc)), 400
    current_app.logger.exception('Reporting query failed')
    return jsonify(status='error', message='Unable to run this query. Check its columns and data source.'), 502


@jwt_required()
def graph_query_controller(agent_id):
    agent = owned_agent(agent_id)
    try:
        data = body()
        query = next((data.get(k) for k in ('message', 'nlq', 'query', 'question', 'graph_query') if data.get(k)), None)
        return jsonify(generated_chart(agent, query))
    except Exception as exc:
        return query_error(exc)


@jwt_required()
def graph_drilldown_controller():
    try:
        data = body()
    except ValueError as exc:
        return query_error(exc)
    agent = owned_agent(data.get('agent_id'))
    try:
        original = data.get('original_query')
        label = data.get('drill_label')
        path = data.get('drill_path', [])
        if not isinstance(original, str) or not original.strip() or label is None or not isinstance(path, list) or not all(isinstance(p, str) for p in path):
            raise ValueError('Original query, drill label and a valid drill path are required.')
        path = path + [str(label)]
        query = f"Drilldown of '{original}' with focus on {' -> '.join(path)}"
        return jsonify(dict(generated_chart(agent, query), drill_path=path))
    except Exception as exc:
        return query_error(exc)


@jwt_required()
def sql_graph_controller(agent_id):
    agent = owned_agent(agent_id)
    try:
        data = body()
        rows = execute_report_query(agent, data.get('sql'))
        return jsonify(dict(chart_payload(rows, data.get('chart_type', 'bar')), query=data['sql']))
    except Exception as exc:
        return query_error(exc)

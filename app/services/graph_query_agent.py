import json
from app.models.table_metadata import TableMetadata
from app.models.user import User
from app.services.query_sql_agent import execute_sql_query, format_datasource_table_metadata, format_table_metadata
from app.utils.db_connections import (
    DISPLAY_NAMES,
    ConnectionConfigError,
    create_source_engine,
    reflect_schema,
    sql_dialect_name,
)
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from sqlalchemy import text
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
import os

def generate_sql_and_graph_query(agent, nl_query, source_type, table_names):

    if not nl_query:
        return {"sql": "", "data": []}

    if agent.llm_provider == "OpenAI":
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise EnvironmentError("Missing OPENAI_API_KEY")

        llm = ChatOpenAI(
            temperature=0,
            model='gpt-4',
            openai_api_key=openai_key
        )

    # elif agent.llm_provider == "claude":
    #     llm = AzureChatOpenAI(
    #         azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    #         azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    #         openai_api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    #     )

    else:
        raise Exception(f"Unsupported LLM provider: {agent.llm_provider}")
    

    try:
        if source_type == 'tables':
            print(f"[generate_sql_and_query] Generating SQL for tables: {table_names}")
            if not table_names:
                raise ValueError("No tables provided for table-based query")
            sql_query = table_query(llm, nl_query, table_names, agent.user_id)
            print(f"[generate_sql_and_query] Executing SQL query: {sql_query}")
            query_result = execute_sql_query(sql_query)
            print(f"[generate_sql_and_query] Query result: {query_result}")
        else:
            sql_info = data_source_query(llm, agent, nl_query)
            sql_query = sql_info["sql"]
            query_result = sql_info["data"]

    except Exception as e:
        print(f"[generate_sql_and_query] Query execution failed: {e}")
        return {
            "sql": "",
            "data": [],
            "error": str(e)
        }

    return {
        "sql": sql_query,
        "data": query_result
    }


GENERIC_GRAPH_PROMPT_TEMPLATE = """
You are a SQL Assistant designed to generate data queries that support visualizations like charts, graphs, and dashboards.

Your job is to translate natural language questions into optimized **{db_type} SQL queries** suitable for plotting data.

📌 Key Guidelines:
- Identify whether the question asks for **trends over time**, **comparisons between categories**, or **key metrics (KPIs)**.
- Use **aggregations** (`SUM`, `COUNT`, `AVG`, `MIN`, `MAX`) if the question implies summarization.
- Use **GROUP BY** for comparisons across fields (e.g., categories, dates).
- Use **DATE functions** for filtering or grouping by time periods (e.g., months, years).
- Apply **ORDER BY** where sorted data is needed (e.g., chronological order).
- Perform **JOINs** if required using the schema structure.
- Use `LOWER(column)` for text-based filters or comparisons.

📦 Table Schema:
{schema}

👤 User Question:
{nlq}

✅ Output Format:
Respond ONLY in the following valid JSON format:
```json
{{ "sql": "<valid SQLite SQL query>" }}
"""

def data_source_query(llm, agent, nlq):
    conn = agent.data_connection

    # Shared URL building: see app/utils/db_connections.py. Object stores are
    # rejected with a readable message instead of a TypeError.
    try:
        engine = create_source_engine(conn)
        print(f"[INFO] Connected to {DISPLAY_NAMES.get(conn.source_type, conn.source_type)}")
    except ConnectionConfigError as e:
        return {"sql": "", "data": [], "error": str(e)}
    except Exception as e:
        print(f"[ERROR] Engine creation failed: {e}")
        return {"sql": "", "data": [], "error": f"Engine creation failed: {str(e)}"}

    # Reflect schema
    try:
        table_metadata = reflect_schema(engine)
        print("[INFO] Schema reflected successfully")
    except Exception as e:
        engine.dispose()
        print(f"[ERROR] Failed to reflect schema: {e}")
        return {"sql": "", "data": [], "error": f"Failed to reflect schema: {str(e)}"}

    if not table_metadata:
        engine.dispose()
        return {"sql": "", "data": [], "error": "No tables were found in this data source."}

    schema = format_datasource_table_metadata(table_metadata)

    parser = JsonOutputParser()
    prompt = ChatPromptTemplate.from_template(GENERIC_GRAPH_PROMPT_TEMPLATE)
    chain = prompt | llm | parser

    try:
        response = chain.invoke({
            "nlq": nlq,
            "schema": schema,
            "db_type": sql_dialect_name(conn)
        })
        sql_query = (response or {}).get("sql", "").strip()
        print(f"[INFO] Generated SQL: {sql_query}")
    except Exception as e:
        engine.dispose()
        return {"sql": "", "data": [], "error": f"LLM failed to generate SQL: {str(e)}"}

    if not sql_query.lower().startswith("select"):
        engine.dispose()
        return {"sql": sql_query, "data": [], "error": "Generated SQL is not a SELECT statement"}

    try:
        with engine.connect() as connection:
            result = connection.execute(text(sql_query))
            data = [dict(row._mapping) for row in result]
        return {"sql": sql_query, "data": data}
    except Exception as e:
        return {"sql": sql_query, "data": [], "error": f"Query execution failed: {str(e)}"}
    finally:
        engine.dispose()


def table_query(llm, nlq, table_names, user_id):

    tables = TableMetadata.query.filter(TableMetadata.table_name.in_(table_names)).all()

    user = User.query.get(user_id)

    # Parse schema JSON and build the metadata dictionary
    table_metadata = {
        f"org_{user.organization_id}_{table.table_name}": json.loads(table.schema) if isinstance(table.schema, str) else table.schema
        for table in tables
    }

    # Format the metadata into a prompt-ready string
    schema = format_table_metadata(table_metadata)

    parser = JsonOutputParser()
    prompt = ChatPromptTemplate.from_template(GENERIC_GRAPH_PROMPT_TEMPLATE)


    chain = prompt | llm | parser

    try:
        response = chain.invoke({
            "nlq": nlq,
            "schema": schema,
            "db_type": 'SQLITE'
        })
        print("LLM Response:", response)
    except Exception as e:
        print("[ERROR] table_query failed at chain.invoke:", e)
        raise


    print(response)

    sql_query = response["sql"]

    return sql_query

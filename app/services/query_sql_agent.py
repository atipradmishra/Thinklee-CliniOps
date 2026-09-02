import json
from app.models.table_metadata import TableMetadata
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
from app.extensions import db
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import SQLAlchemyError


def generate_sql_and_query(agent, nl_query, source_type, table_names, glossary_text, chat_history=None, few_shot_examples=None):
    if not nl_query:
        return {"sql": "", "data": []}

    if agent.llm_provider.lower() == "openai":
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
            if not table_names:
                raise ValueError("No tables provided for table-based query")

            sql_query = table_query(llm, agent, nl_query, table_names,glossary_text, few_shot_examples, chat_history)
            query_result = execute_sql_query(sql_query)
        else:
            print(f"[generate_sql_and_query] Generating SQL for data source: {agent.data_connection.source_name}")
            sql_info = data_source_query(llm, agent, nl_query,glossary_text, few_shot_examples, chat_history)
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


def execute_sql_query(query):
    try:
        # Execute the query
        result = db.session.execute(text(query))
        
        # Extract column names
        if result.returns_rows:
            columns = result.keys()
            rows = result.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        else:
            db.session.commit()  # for INSERT/UPDATE/DELETE
            return [{"message": "Query executed successfully."}]
            
    except Exception as e:
        # Return error in a consistent structure
        return [{"error": str(e)}]
        
    finally:
        db.session.close()

def data_source_query(llm, agent, nlq, glossary_text, few_shot_examples=None, chat_history=None):
    conn = agent.data_connection

    print(f'[INFO] Querying data source: {conn.source_name}')

    # Step 1: Build the engine.
    # URL construction lives in app.utils.db_connections so the copilot, the
    # graph agent and the connection tester all agree on how a source is
    # reached. Object stores (S3) raise ConnectionConfigError here rather than
    # crashing on a NULL password further down.
    try:
        engine = create_source_engine(conn)
        db_type = DISPLAY_NAMES.get(conn.source_type, conn.source_type)
        print(f"[INFO] Connected to {db_type}")
    except ConnectionConfigError as e:
        return {"sql": "", "data": [], "error": str(e)}
    except Exception as e:
        return {"sql": "", "data": [], "error": f"Engine creation failed: {str(e)}"}

    # Step 2: Reflect schema
    try:
        table_metadata = reflect_schema(engine)
        print(f"[INFO] Schema reflected: {len(table_metadata)} tables")
    except Exception as e:
        engine.dispose()
        return {"sql": "", "data": [], "error": f"Failed to reflect schema: {str(e)}"}

    if not table_metadata:
        engine.dispose()
        return {"sql": "", "data": [], "error": "No tables were found in this data source."}

    # Step 3: Format metadata
    schema = format_datasource_table_metadata(table_metadata)

    # Step 4: Fetch similar past feedback to enhance the prompt
    feedback_section = ""
    if few_shot_examples:
        for i, (log, score) in enumerate(few_shot_examples):
            feedback_section += f"""
            🧠 Related Past Query #{i + 1}:
            - Question: "{log.user_query}"
            - SQL Query: "{log.generated_sql}"
            - LLM Response: "{log.ai_response}"
            - User Feedback: "{log.feedback_comment}"
            """

    # Step 5: Build the history string
    history_section = ""
    if chat_history:
        for i, turn in enumerate(chat_history[-3:]):
            history_section += f"""
            🔄 Past Turn #{i+1}:
            - User: {turn.get("user")}
            - AI: {turn.get("ai")}
            """

    # Step 6: Build Prompt
    sql_dialect = sql_dialect_name(conn)
    parser = JsonOutputParser()
    prompt = ChatPromptTemplate.from_template(r"""
    {sql_system_prompt}

    You are a highly accurate AI assistant trained to generate **{db_type} SQL queries** from natural language questions using ONLY the given table schema.

    📚 Business Glossary (use terms exactly as defined here when interpreting user questions):
    {business_glossary}

    ✅ DO:
    - Use ONLY the table and column names from the schema below.
    - Use proper JOINs if required.
    - Use column types or enum values to infer constraints.

    ❌ DO NOT:
    - Invent new table names or column names.
    - Output markdown, comments, or explanations.

    ---

    🧠 Conversation History (Use it for additional context if needed):
    {history_section}

    📦 Table Schema:
    {schema}

    🎯 Task:
    {sql_task}

    📌 Instruction:
    {sql_instruction}

    👤 User Question:
    {nlq}

    {feedback_section}

    Based on the above feedback from similar past queries, provide an improved SQL response to the current question.

    ---

    ✅ Output Format:
    ```json
    {{ "sql": "<valid {db_type} SQL query>" }}
    """)

    chain = prompt | llm | parser

    # Step 7: Run LLM for SQL generation
    try:
        response = chain.invoke({
            "nlq": nlq,
            "sql_system_prompt": agent.sql_system_prompt,
            "sql_task": agent.sql_task,
            "sql_instruction": agent.sql_instruction,
            "schema": schema,
            "db_type": sql_dialect,
            "feedback_section": feedback_section if feedback_section else "",
            "history_section": history_section if history_section else "",
            "business_glossary": glossary_text
        })
        sql_query = (response or {}).get("sql", "").strip()
        print(f"[INFO] Generated SQL: {sql_query}")
    except Exception as e:
        engine.dispose()
        return {"sql": "", "data": [], "error": f"LLM failed to generate SQL: {str(e)}"}

    # Step 8: Validate SQL
    if not sql_query.lower().startswith("select"):
        engine.dispose()
        return {"sql": sql_query, "data": [], "error": "Generated SQL is not a SELECT statement"}

    # Step 9: Run the SQL
    try:
        with engine.connect() as connection:
            result = connection.execute(text(sql_query))
            data = [dict(row._mapping) for row in result]
        return {"sql": sql_query, "data": data}
    except Exception as e:
        return {"sql": sql_query, "data": [], "error": f"Query execution failed: {str(e)}"}
    finally:
        engine.dispose()

@jwt_required()
def table_query(llm, agent, nlq, table_names, glossary_text, few_shot_examples=None, chat_history=None):

    # Step 1: Build feedback
    feedback_section = "\n".join([
        f"""
        🧠 Related Past Query #{i + 1}:
        - Question: "{log.user_query}"
        - SQL Query: "{log.generated_sql}"
        - LLM Response: "{log.ai_response}"
        - User Feedback: "{log.feedback_comment}"
        """
        for i, (log, score) in enumerate(few_shot_examples or [])
    ])

    # Step 2: Build conversation history
    history_section = "\n".join([
        f"""
        🔄 Past Turn #{i + 1}:
        - User: {turn.get("user")}
        - AI: {turn.get("ai")}
        """
        for i, turn in enumerate((chat_history or [])[-3:])
    ])

    # Step 3: Get table metadata
    try:
        tables = TableMetadata.query.filter(TableMetadata.table_name.in_(table_names)).all()
    except SQLAlchemyError as e:
        return {"sql": "", "data": [], "error": f"DB error: {str(e)}"}

    table_metadata = {}
    for table in tables:
        try:
            parsed_schema = json.loads(table.schema) if isinstance(table.schema, str) else table.schema
        except json.JSONDecodeError:
            parsed_schema = {}
        table_metadata[f"org_{agent.organization_id}_{table.table_name}"] = parsed_schema

    schema = format_table_metadata(table_metadata)

    # Step 4: Build prompt
    parser = JsonOutputParser()
    prompt = ChatPromptTemplate.from_template("""
    {sql_system_prompt}

    You are a highly accurate AI assistant trained to generate **SQLite SQL queries** from natural language questions using ONLY the given table schema.

    📚 Business Glossary:
    {business_glossary}

    ✅ DO:
    - Use ONLY the table and column names from the schema below and consider space between words as a underscore(_).
    - Use proper JOINs if required.
    - Use column types or enum values to infer constraints.

    ❌ DO NOT:
    - Invent new table names or column names.
    - Output markdown, comments, or explanations.

    {history_block}
    📦 Table Schema:
    {schema}

    🎯 Task:
    {sql_task}

    📌 Instruction:
    {sql_instruction}

    👤 User Question:
    {nlq}

    {feedback_block}

    ✅ Output Format:
    {{ "sql": "<valid SQLite SQL query>" }}
    """)

    history_block = f"🧠 Conversation History:\n{history_section}" if history_section else ""
    feedback_block = f"💡 Related Feedback:\n{feedback_section}" if feedback_section else ""

    # Step 5: Invoke LLM
    try:
        print("[INFO] Invoking LLM...")
        chain = prompt | llm | parser
        response = chain.invoke({
            "nlq": nlq,
            "sql_system_prompt": agent.sql_system_prompt,
            "sql_task": agent.sql_task,
            "sql_instruction": agent.sql_instruction,
            "schema": schema,
            "feedback_block": feedback_block,
            "history_block": history_block,
            "business_glossary": glossary_text or ""
        })
        sql_query = response.get("sql", "").strip()
    except Exception as e:
        print(f"[ERROR] LLM failed to generate SQL: {e}")
        return {"sql": "", "data": [], "error": str(e)}

    return sql_query


def format_datasource_table_metadata(table_metadata: dict) -> str:
    formatted = []
    for table, columns in table_metadata.items():
        column_defs = ", ".join([f"{col['name']} {col['type']}" for col in columns])
        formatted.append(f"{table}({column_defs})")
    return "\n".join(formatted)

def format_table_metadata(table_metadata: dict) -> str:
    formatted_tables = []
    
    for table_name, columns in table_metadata.items():
        formatted_tables.append(f"Table: {table_name}")
        for column_name, col_info in columns.items():
            data_type = col_info.get("data_type", "unknown")
            description = col_info.get("description", "")
            formatted_tables.append(f"  - {column_name} ({data_type}): {description}")
        formatted_tables.append("")

    return "\n".join(formatted_tables)

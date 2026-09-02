from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage


def generate_sql_prompts(context):
    parser = JsonOutputParser()

    system_msg = SystemMessage(content="You are a helpful assistant trained for prompt generation that takes a business context and generates structured instructions for building two types of AI agents: a **SQL Agent** and a **Synthesizer Agent**.")

    examples = [
        {
            "input": "Help me write prompt for pharma sales ai assistance - SQL System Prompt, SQL Task, SQL Instruction, Synthesizer System Prompt, Synthesizer Task, Synthesizer Instruction",
            "output": {
                "sql_system_prompt": "You are an expert SQL agent for pharmaceutical sales data. You generate syntactically correct and optimized SQL queries for a PostgreSQL database. Always prioritize safety, avoid SQL injection, and only query from existing schema fields. Use WHERE clauses precisely and prefer using aggregate functions like SUM, AVG, and COUNT for business insights.",
                "sql_task": "Translate the user's business-related question about pharmaceutical sales into an accurate SQL query. The database includes tables such as sales, products, regions, sales_reps, and targets. Use joins, grouping, and filtering appropriately to extract the required data.",
                "sql_instruction": '''Based on the user’s input, write a SQL query that:
                                    - Identifies performance metrics (e.g., sales volume, growth rate)
                                    - Filters by region, time period, product, or sales rep
                                    - Summarizes data using GROUP BY and ORDER BY when needed
                                    - Limits the results for clarity (e.g., LIMIT 10)
                                    Return only the SQL query, nothing else.''',
                "synthesizer_system_prompt": "You are a business-savvy AI assistant helping pharma sales teams interpret SQL query results in natural language. Explain results clearly, highlight key trends or insights, and use domain-specific terminology (e.g., 'target achievement', 'sales rep performance', 'top-performing regions').",
                "synthesizer_task": "Convert structured SQL query results into a human-readable summary suitable for pharma sales managers. Focus on making the data actionable and insightful.",
                "synthesizer_instruction": '''Given the SQL output table and the original user query, write a concise business summary:
                                            - Explain what the numbers mean in context (e.g., “Sales in West region exceeded targets by 12%”)
                                            - Highlight any performance gaps, achievements, or trends
                                            - Use bullet points or short paragraphs to improve readability
                                            - Avoid technical jargon unless needed for clarity.'''
            }
        },
        {
            "input": "Help generate prompts for lab informatics data which includes tables like samples, inventory_items, stock thresholds, instrument_schedule ,expiry_alerts",
            "output": {
                "sql_system_prompt": "You are an expert SQL agent for a lab informatics system. You write precise, optimized SQL queries for a PostgreSQL database. The schema includes tables such as samples, inventory_items, stock_thresholds, instrument_schedule, and expiry_alerts. You must generate queries that help lab managers monitor samples, inventory levels, instrument usage, and expiry-related events. Ensure all queries are safe, accurate, and follow best SQL practices.",
                "sql_task": '''Convert the user's natural language lab operations query into a valid and efficient SQL query. Use appropriate joins, conditions, grouping, and aggregations. Examples of user questions include:
                                - "List inventory items below minimum stock level"
                                - "Show instruments scheduled for maintenance next week"
                                - "Get all expired chemicals"
                                - "How many samples were processed this month?"
                            ''',
                "sql_instruction": '''Based on the user's request, write a SQL query that:
                                    - Pulls relevant data from the correct tables
                                    - Applies filtering based on time, thresholds, or item type
                                    - Uses JOINs to merge contextual information (e.g., item names with stock levels)
                                    - Handles date ranges and alerts properly using WHERE and INTERVAL
                                    - Returns only the most useful fields (limit excessive rows with LIMIT if needed)
                                    Return only the SQL query, and nothing else.''',
                "synthesizer_system_prompt": "You are a domain-aware assistant that interprets SQL query results related to laboratory informatics. You convert data into business-friendly summaries, helping lab managers take informed actions. Focus on clarity, trends, and alerts (e.g., low stock, expired items, upcoming maintenance). Use domain-specific language appropriate for laboratory inventory and operations.",
                "synthesizer_task": "Given the output of a SQL query and the original user question, summarize the results in clear, insightful language. Emphasize key alerts or decisions (e.g., “Restock required for solvents”, “5 instruments due for calibration”).",
                "synthesizer_instruction": '''Generate a short business report based on the SQL result:
                                            - Highlight urgent matters (e.g., items near expiry, maintenance due)
                                            - Use bullet points for clear readability
                                            - Avoid restating raw data—interpret what it means
                                            - Suggest actions if applicable (e.g., “Consider placing a purchase order”)
                                            '''
            }
        }
    ]

    example_messages = []
    for ex in examples:
        example_messages.append(HumanMessage(content=f'Business Context:\n"{ex["input"]}"'))
        example_messages.append(AIMessage(content=f'{ex["output"]}'))

    format_instruction = parser.get_format_instructions()

    final_user_msg = HumanMessage(content=f'''
    Business Context:
    "{context}"

    Generate the following output in **strict JSON format**:
    {{
    "sql_system_prompt": "...",
    "sql_task": "...",
    "sql_instruction": "...",
    "synthesizer_system_prompt": "...",
    "synthesizer_task": "...",
    "synthesizer_instruction": "..."
    }}

    📌 Guidelines:
    - Each field should be concise and specific.
    - Don’t include markdown, commentary, or explanations.

    {format_instruction}
    ''')

    messages = [system_msg] + example_messages + [final_user_msg]

    llm = ChatOpenAI(model="gpt-4", temperature=0.3)

    chain = llm | parser
    result = chain.invoke(messages)

    return result


def generate_rag_synthesizer_prompts(context):
    parser = JsonOutputParser()

    system_msg = SystemMessage(content="You are a helpful assistant trained for prompt generation. Given a business context, generate structured prompts for a **RAG Synthesizer Agent** that interprets retrieved document snippets into clear, human-readable answers.")

    examples = [
        {
            "input": "Help me write prompts for legal contract review assistant",
            "output": {
                "rag_synthesizer_system_prompt": "You are a legal insights assistant that interprets retrieved contract text into plain, business-readable summaries. Avoid legal advice but provide clear explanations.",
                "rag_synthesizer_task": "Summarize retrieved legal passages into actionable insights (e.g., obligations, deadlines, risks).",
                "rag_synthesizer_instruction": '''Given retrieved contract snippets and the user’s question:
                                                - Rephrase legal clauses in plain terms
                                                - Highlight obligations, risks, and deadlines
                                                - Use bullet points for readability
                                                - Avoid speculation or legal advice'''
            }
        },
        {
            "input": "Help me generate prompts for healthcare research assistant handling clinical trial reports and research papers",
            "output": {
                "rag_synthesizer_system_prompt": "You are a biomedical summarizer that converts retrieved trial and research content into clear insights for healthcare professionals and researchers.",
                "rag_synthesizer_task": "Summarize retrieved passages into structured research insights.",
                "rag_synthesizer_instruction": '''Given retrieved biomedical content and the query:
                                                - Highlight key findings and outcomes
                                                - Mention limitations if stated
                                                - Avoid unsupported medical claims
                                                - Keep language clear and actionable'''
            }
        }
    ]

    example_messages = []
    for ex in examples:
        example_messages.append(HumanMessage(content=f'Business Context:\n"{ex["input"]}"'))
        example_messages.append(AIMessage(content=f'{ex["output"]}'))

    format_instruction = parser.get_format_instructions()

    final_user_msg = HumanMessage(content=f'''
    Business Context:
    "{context}"

    Generate the following output in **strict JSON format**:
    {{
    "rag_synthesizer_system_prompt": "...",
    "rag_synthesizer_task": "...",
    "rag_synthesizer_instruction": "..."
    }}

    📌 Guidelines:
    - Each field should be concise and specific.
    - Don’t include markdown, commentary, or explanations.

    {format_instruction}
    ''')

    messages = [system_msg] + example_messages + [final_user_msg]

    llm = ChatOpenAI(model="gpt-4", temperature=0.3)

    chain = llm | parser
    result = chain.invoke(messages)

    return result

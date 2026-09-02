from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, AzureChatOpenAI
import os

def synthesize_result(agent, nl_query, data,glossary_text, few_shot_examples=None):

    # Initialize LLM
    if agent.llm_provider == "OpenAI":
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise EnvironmentError("Missing OPENAI_API_KEY")

        llm = ChatOpenAI(
            temperature=agent.temperature,
            model=agent.llm_model,
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

    
    # Step 1: Build the feedback section from past examples
    feedback_section = ""
    if few_shot_examples:
        for i, (log, score) in enumerate(few_shot_examples):
            feedback_section += f"""
            🧠 Related Past Query #{i + 1}:
            - Question: "{log.user_query}"
            - LLM Response: "{log.ai_response}"
            - User Feedback: "{log.feedback}"
            """

    # Step 2: Add glossary context if available
    glossary_section = ""
    if glossary_text:
        glossary_section = f"""
        📖 Business Glossary:
        {glossary_text}
        """

    # Step 3: Build the final prompt
    prompt = ChatPromptTemplate.from_template("""
    {system_prompt}

    You are a helpful and precise response synthesizer agent AI assistant. Your task is to interpret SQL query results
    and explain them in clear, natural language based on the user's original question.

    ---                                      
    
    Your role:
    - Generate a clear, natural, user-facing answer using the information already provided to you.
    - Assume all provided information is factual and sufficient.
    - Speak with confidence, as if the knowledge is inherently yours.

    Strict rules:
    - NEVER mention or imply:
    - "retrieved context"
    - "SQL query"
    - "database"
    - "agent"
    - "tool"
    - "based on the data"
    - "according to the query results"
    - DO NOT describe how the information was obtained.
    - DO NOT reference intermediate steps, pipelines, or system processes.

    Tone & style:
    - Professional, concise, and domain-aware
    - Directly answer the user’s question
    - If numbers or tables are provided, explain insights naturally
                                              
    Language rule (STRICT):
    - Detect the language of the user's question.
    - Respond ONLY in the same language.
    - Do NOT translate the question.
    - Do NOT mix languages.
    - If unsure about the language, default to the user's language.

    If information is insufficient:
    - Ask a clarifying question WITHOUT mentioning missing context or data sources.
    - If the information is still insufficient, respond with "I'm sorry, I don't have enough information to answer that."

    {glossary_section}

    🧠 User Query:
    {user_query}

    📊 SQL Result:
    {sql_result}

    🎯 Task:
    {task}

    📌 Instruction:
    {instruction}

    {feedback_section}

    Based on the business glossary, past feedback, and query context, 
    provide an improved and accurate response that satisfies the user's intent.

    ---

    ✅ Output Format:
    Do not restate the SQL or show any raw SQL data.
    Provide clear, concise explanations with specific numbers if available.
    Do not include markdown, technical explanations, or extra commentary.
    """)

    # Step 4: Run the chain
    chain = prompt | llm | StrOutputParser()

    summary = chain.invoke({
        "system_prompt": agent.synthesizer_system_prompt.strip(),
        "task": agent.synthesizer_task.strip(),
        "instruction": agent.synthesizer_instruction.strip(),
        "user_query": nl_query,
        "sql_result": data,
        "feedback_section": feedback_section,
        "glossary_section": glossary_section
    })

    return summary
